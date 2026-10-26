"""Checkpointed stage executor."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from draftproof.domain.errors import CancelledError
from draftproof.pipeline import stages as stage_impl
from draftproof.pipeline.telemetry import emit_usage

if TYPE_CHECKING:
    from draftproof.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Stage:
    """One named unit of work."""

    name: str
    run: Callable[[PipelineContext], None]


def default_stages() -> tuple[Stage, ...]:
    """The full publishing pipeline."""
    return (
        Stage("brief", stage_impl.brief_stage),
        Stage("plan", stage_impl.plan_stage),
        Stage("research", stage_impl.research_stage),
        Stage("draft", stage_impl.draft_stage),
        Stage("claims", stage_impl.claims_stage),
        Stage("verify", stage_impl.verify_stage),
        Stage("critique", stage_impl.critique_stage),
        Stage("revise", stage_impl.revise_stage),
        Stage("publish", stage_impl.publish_stage),
    )


def revision_stages() -> tuple[Stage, ...]:
    """Stages re-run after a human requests changes."""
    return (
        Stage("draft", stage_impl.draft_stage),
        Stage("claims", stage_impl.claims_stage),
        Stage("verify", stage_impl.verify_stage),
        Stage("critique", stage_impl.critique_stage),
        Stage("revise", stage_impl.revise_stage),
        Stage("publish", stage_impl.publish_stage),
    )


class Pipeline:
    """Execute stages in order, recording progress and checkpoints."""

    def __init__(self, stages: Sequence[Stage], *, resume: bool = False) -> None:
        if not stages:
            raise ValueError("A pipeline needs at least one stage")
        self._stages = list(stages)
        self._resume = resume

    @property
    def stage_names(self) -> list[str]:
        return [stage.name for stage in self._stages]

    def execute(self, context: PipelineContext) -> None:
        """Run every stage, skipping completed ones when resuming."""
        completed = set(context.repo.load_checkpoints(context.run_id)) if self._resume else set()
        for stage in self._stages:
            context.check_cancelled()
            if stage.name in completed:
                context.sink.emit(
                    "log",
                    {"stage": stage.name, "message": "skipped: checkpoint already exists"},
                )
                continue

            attempt = max(1, context.revision_attempts + 1)
            context.repo.start_stage(context.run_id, stage.name, attempt)
            context.sink.emit("stage_started", {"stage": stage.name, "attempt": attempt})
            started = time.perf_counter()
            try:
                stage.run(context)
            except CancelledError:
                context.repo.fail_stage(context.run_id, stage.name, "cancelled", attempt)
                raise
            except Exception as exc:
                context.repo.fail_stage(
                    context.run_id, stage.name, f"{type(exc).__name__}: {exc}", attempt
                )
                context.sink.emit(
                    "log",
                    {
                        "stage": stage.name,
                        "level": "error",
                        "message": f"{type(exc).__name__}: {str(exc)[:400]}",
                    },
                )
                logger.exception("Stage %s failed", stage.name)
                raise

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            context.repo.finish_stage(context.run_id, stage.name, attempt, f"{elapsed_ms} ms")
            context.repo.save_checkpoint(
                context.run_id, stage.name, {"completed": True, "duration_ms": elapsed_ms}
            )
            context.sink.emit(
                "stage_finished",
                {"stage": stage.name, "attempt": attempt, "duration_ms": elapsed_ms},
            )
            emit_usage(context)
