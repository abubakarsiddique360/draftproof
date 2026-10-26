"""Application service: owns configuration and drives runs end to end."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

from draftproof.config import Settings
from draftproof.domain.errors import (
    CancelledError,
    ConflictError,
    DraftProofError,
    RunNotFoundError,
)
from draftproof.domain.models import (
    Brief,
    ProviderInfo,
    Review,
    ReviewDecision,
    RunRecord,
    RunStatus,
    utc_now,
)
from draftproof.pipeline.context import PipelineContext
from draftproof.pipeline.events import EventSink, RepositoryEventSink, TeeEventSink
from draftproof.pipeline.executor import Pipeline, default_stages, revision_stages
from draftproof.providers.base import Provider
from draftproof.providers.registry import build_providers, describe_providers
from draftproof.providers.router import ModelRouter, UsageLedger
from draftproof.quality.rubric import Rubric, default_rubric, load_rubric
from draftproof.research.fetchers import SafeFetcher
from draftproof.research.retrievers import LocalCorpusRetriever, Retriever, build_retriever
from draftproof.research.verifier import Verifier, build_verifier
from draftproof.storage.db import Database
from draftproof.storage.files import ArtifactStore
from draftproof.storage.repository import Repository

logger = logging.getLogger(__name__)


class RunService:
    """Coordinates storage, providers, research and the pipeline."""

    def __init__(
        self,
        *,
        settings: Settings,
        repo: Repository,
        artifacts: ArtifactStore,
        providers: Mapping[str, Provider],
        retriever: Retriever,
        verifier: Verifier,
        rubric: Rubric,
        fetcher: SafeFetcher | None = None,
        database: Database | None = None,
        extra_sinks: Sequence[EventSink] = (),
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.artifacts = artifacts
        self.providers = dict(providers)
        self.retriever = retriever
        self.verifier = verifier
        self.rubric = rubric
        self._fetcher = fetcher
        self._database = database
        self._extra_sinks = list(extra_sinks)
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def build(
        cls,
        settings: Settings | None = None,
        *,
        rubric_path: Path | str | None = None,
        extra_sinks: Sequence[EventSink] = (),
    ) -> RunService:
        """Create a fully wired service from settings."""
        resolved = settings or Settings()
        resolved.ensure_dirs()
        database = Database(resolved.db_path)
        database.migrate()
        repo = Repository(database)
        artifacts = ArtifactStore(resolved.artifacts_dir)

        providers = build_providers(resolved)
        retriever = build_retriever(resolved)

        corpus_index = (
            retriever.corpus_index() if isinstance(retriever, LocalCorpusRetriever) else None
        )
        fetcher: SafeFetcher | None = None
        if resolved.verification_mode == "live":
            fetcher = SafeFetcher(
                timeout=resolved.fetch_timeout,
                max_bytes=resolved.fetch_max_bytes,
                max_redirects=3,
            )
        verifier = build_verifier(
            resolved.verification_mode,
            fetcher=fetcher,
            corpus_index=corpus_index,
            min_overlap=resolved.verification_min_overlap,
            blocked_domains=resolved.blocked_domains,
            allowed_domains=resolved.allowed_domains,
        )
        rubric = load_rubric(rubric_path) if rubric_path else default_rubric()
        return cls(
            settings=resolved,
            repo=repo,
            artifacts=artifacts,
            providers=providers,
            retriever=retriever,
            verifier=verifier,
            rubric=rubric,
            fetcher=fetcher,
            database=database,
            extra_sinks=extra_sinks,
        )

    def close(self) -> None:
        """Release the fetcher and database handles."""
        if self._fetcher is not None:
            self._fetcher.close()
        if self._database is not None:
            self._database.close()

    def __enter__(self) -> RunService:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    def create_run(self, brief: Brief) -> RunRecord:
        """Persist a queued run without starting it."""
        provider = self.settings.provider
        configured = self.providers.get(provider)
        model = getattr(configured, "model", None) or self.settings.model or provider
        return self.repo.create_run(
            brief,
            provider=provider,
            model=model,
            settings_snapshot=self.settings.snapshot(),
        )

    def execute(
        self,
        run_id: str,
        *,
        resume: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> RunRecord:
        """Run the pipeline for an existing run and return the final record."""
        run = self.repo.get_run(run_id)
        cancel = cancel_event or self._event_for(run_id)
        context = self._context_for(run, cancel)
        self.repo.set_status(run_id, RunStatus.RUNNING)
        context.sink.emit(
            "run_started",
            {
                "run_id": run_id,
                "topic": run.brief.topic,
                "provider": run.provider,
                "model": run.model,
                "resume": resume,
                "verification": self.verifier.name,
            },
        )
        try:
            Pipeline(default_stages(), resume=resume).execute(context)
        except CancelledError as exc:
            self.repo.set_status(run_id, RunStatus.CANCELLED, error=exc.message)
            context.sink.emit("run_finished", {"status": RunStatus.CANCELLED.value})
        except DraftProofError as exc:
            logger.warning("Run %s failed: %s", run_id, exc.message)
            self.repo.set_status(run_id, RunStatus.FAILED, error=exc.message)
            context.sink.emit(
                "run_finished",
                {
                    "status": RunStatus.FAILED.value,
                    "error": exc.message,
                    "hint": exc.hint,
                    "code": exc.code,
                },
            )
        except Exception:
            logger.exception("Unexpected failure in run %s", run_id)
            self.repo.set_status(run_id, RunStatus.FAILED, error="Unexpected internal error")
            context.sink.emit(
                "run_finished",
                {
                    "status": RunStatus.FAILED.value,
                    "error": "Unexpected internal error",
                },
            )
        else:
            latest = self.repo.get_run(run_id)
            if latest.status is RunStatus.RUNNING:
                final_status = (
                    RunStatus.AWAITING_REVIEW
                    if self.settings.review_required and not latest.reviews
                    else RunStatus.COMPLETED
                )
                self.repo.set_status(run_id, final_status)
                context.sink.emit(
                    "run_finished",
                    {"status": final_status.value, "resumed": resume},
                )
        finally:
            self.repo.set_usage(run_id, context.router.ledger.snapshot())
            self._forget(run_id)
        return self.repo.get_run(run_id)

    def resume(self, run_id: str) -> RunRecord:
        """Resume a run, skipping stages that already completed."""
        return self.execute(run_id, resume=True)

    def cancel(self, run_id: str) -> bool:
        """Signal cancellation for a run that is still active."""
        run = self.repo.get_run(run_id)
        if run.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return False
        with self._lock:
            event = self._cancel_events.setdefault(run_id, threading.Event())
        event.set()
        return True

    def approve(self, run_id: str, *, notes: str = "", reviewer: str = "editor") -> RunRecord:
        """Approve a run that is waiting for human review."""
        run = self.repo.get_run(run_id)
        if run.status is not RunStatus.AWAITING_REVIEW:
            raise ConflictError(
                f"Run '{run_id}' is {run.status.value}, not awaiting review",
                hint="Only runs in the awaiting_review state can be approved.",
            )
        self.repo.add_review(
            run_id,
            Review(decision=ReviewDecision.APPROVE, notes=notes, reviewer=reviewer),
        )
        self.repo.set_status(run_id, RunStatus.COMPLETED)
        RepositoryEventSink(self.repo, run_id).emit(
            "run_status", {"status": RunStatus.COMPLETED.value, "reviewer": reviewer}
        )
        return self.repo.get_run(run_id)

    def request_changes(
        self,
        run_id: str,
        *,
        notes: str,
        reviewer: str = "editor",
        section_ids: list[str] | None = None,
    ) -> RunRecord:
        """Apply editorial notes by re-drafting, re-verifying and re-publishing."""
        run = self.repo.get_run(run_id)
        if run.status not in {RunStatus.AWAITING_REVIEW, RunStatus.COMPLETED}:
            raise ConflictError(f"Run '{run_id}' is {run.status.value} and cannot be revised")
        if run.outline is None or not run.sections:
            raise ConflictError(f"Run '{run_id}' has no draft to revise")

        self.repo.add_review(
            run_id,
            Review(
                decision=ReviewDecision.REQUEST_CHANGES,
                notes=notes,
                reviewer=reviewer,
            ),
        )
        self.repo.set_status(run_id, RunStatus.REVISING)
        cancel = self._event_for(run_id)
        context = self._context_for(run, cancel)
        context.auto_complete = True
        context.review_directives = {"*": [notes]} if notes.strip() else {}
        context.revision_attempts = max((section.attempt for section in run.sections), default=0)
        if section_ids:
            known = {section.plan.id for section in run.sections}
            context.target_section_ids = {item for item in section_ids if item in known} or None
        context.sink.emit(
            "run_status",
            {"status": RunStatus.REVISING.value, "reviewer": reviewer, "notes": notes[:500]},
        )
        try:
            Pipeline(revision_stages()).execute(context)
        except CancelledError as exc:
            self.repo.set_status(run_id, RunStatus.CANCELLED, error=exc.message)
        except DraftProofError as exc:
            logger.warning("Revision of %s failed: %s", run_id, exc.message)
            self.repo.set_status(run_id, RunStatus.FAILED, error=exc.message)
            context.sink.emit(
                "run_finished", {"status": RunStatus.FAILED.value, "error": exc.message}
            )
        finally:
            self.repo.set_usage(run_id, context.router.ledger.snapshot())
            self._forget(run_id)
        return self.repo.get_run(run_id)

    def regenerate_section(
        self,
        run_id: str,
        section_id: str,
        *,
        notes: str = "",
        reviewer: str = "editor",
    ) -> RunRecord:
        """Rewrite a single section after human feedback."""
        message = notes.strip() or "Regenerate this section with tighter, better-sourced writing."
        return self.request_changes(
            run_id,
            notes=message,
            reviewer=reviewer,
            section_ids=[section_id],
        )

    def describe_providers(self) -> list[ProviderInfo]:
        """Advertise provider availability."""
        return describe_providers(self.settings)

    def get_run(self, run_id: str) -> RunRecord:
        """Return a run or raise ``RunNotFoundError``."""
        return self.repo.get_run(run_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _event_for(self, run_id: str) -> threading.Event:
        with self._lock:
            return self._cancel_events.setdefault(run_id, threading.Event())

    def _router(self) -> ModelRouter:
        """Build a router with a fresh ledger so budgets are per run."""
        return ModelRouter(
            self.providers,
            self.settings.provider_chain,
            UsageLedger(self.settings.max_cost_usd),
            max_retries=self.settings.max_retries,
        )

    def _forget(self, run_id: str) -> None:
        with self._lock:
            self._cancel_events.pop(run_id, None)

    def _context_for(self, run: RunRecord, cancel: threading.Event) -> PipelineContext:
        sink: EventSink = RepositoryEventSink(self.repo, run.id)
        if self._extra_sinks:
            sink = TeeEventSink([sink, *self._extra_sinks])
        return PipelineContext(
            run_id=run.id,
            brief=run.brief,
            settings=self.settings,
            router=self._router(),
            repo=self.repo,
            artifacts=self.artifacts,
            sink=sink,
            retriever=self.retriever,
            verifier=self.verifier,
            rubric=self.rubric,
            cancel=cancel,
            outline=run.outline,
            evidence=list(run.evidence),
            sections=list(run.sections),
            quality=run.quality,
            model_name=run.model,
        )


def load_service(
    settings: Settings | None = None, *, rubric_path: Path | str | None = None
) -> RunService:
    """Convenience wrapper around :meth:`RunService.build`."""
    return RunService.build(settings, rubric_path=rubric_path)


def ensure_run(service: RunService, run_id: str) -> RunRecord:
    """Fetch a run, translating unknown ids into ``RunNotFoundError``."""
    return service.repo.get_run(run_id)


def now_iso() -> str:
    """Timestamp helper used by callers that need a stable format."""
    return utc_now().isoformat()


__all__ = [
    "RunNotFoundError",
    "RunService",
    "ensure_run",
    "load_service",
    "now_iso",
]
