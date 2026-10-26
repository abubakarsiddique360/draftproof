"""Shared telemetry helpers for pipeline stages."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from draftproof.pipeline.context import PipelineContext


def emit_usage(context: PipelineContext) -> None:
    """Persist the current usage counters and publish them as an event."""
    usage = context.router.ledger.snapshot()
    context.repo.set_usage(context.run_id, usage)
    context.sink.emit("usage", usage.model_dump())
