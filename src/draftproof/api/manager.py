"""Background execution of pipelines for the HTTP API."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from draftproof.api.metrics import Metrics
from draftproof.domain.models import Brief, RunRecord
from draftproof.pipeline.service import RunService

logger = logging.getLogger(__name__)


class RunManager:
    """Runs pipelines on a bounded thread pool."""

    def __init__(
        self,
        service: RunService,
        *,
        max_workers: int = 2,
        metrics: Metrics | None = None,
    ) -> None:
        self.service = service
        self.metrics = metrics or Metrics()
        self._pool = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="run")
        self._futures: dict[str, Future[None]] = {}
        self._lock = threading.Lock()

    def start(self, brief: Brief) -> RunRecord:
        """Create a run and schedule it immediately."""
        run = self.service.create_run(brief)
        self.submit(run.id)
        self.metrics.inc("draftproof_runs_created_total")
        return run

    def submit(self, run_id: str, *, resume: bool = False) -> None:
        """Schedule execution of an existing run."""
        with self._lock:
            if run_id in self._futures:
                return
            future = self._pool.submit(self._execute, run_id, resume)
            self._futures[run_id] = future
        future.add_done_callback(lambda _future: self._forget(run_id))

    def submit_revision(
        self,
        run_id: str,
        *,
        notes: str,
        reviewer: str,
        section_ids: list[str] | None = None,
    ) -> None:
        """Schedule an editorial revision in the background."""
        self._submit_callable(
            run_id,
            lambda: self.service.request_changes(
                run_id, notes=notes, reviewer=reviewer, section_ids=section_ids
            ),
        )

    def cancel(self, run_id: str) -> bool:
        """Signal cancellation; returns whether the run was still active."""
        return self.service.cancel(run_id)

    def active(self) -> int:
        """Number of pipelines currently scheduled or running."""
        with self._lock:
            return len(self._futures)

    def shutdown(self) -> None:
        """Stop accepting work and wait briefly for running pipelines."""
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _execute(self, run_id: str, resume: bool) -> None:
        try:
            run = self.service.execute(run_id, resume=resume)
        except Exception:  # pragma: no cover - service already records failures
            logger.exception("Run %s crashed", run_id)
            return
        labels = {"status": run.status.value}
        self.metrics.inc("draftproof_runs_finished_total", labels)
        if run.usage.total_tokens:
            self.metrics.inc("draftproof_tokens_total", value=float(run.usage.total_tokens))

    def _submit_callable(self, run_id: str, fn: Callable[[], object]) -> None:
        with self._lock:
            if run_id in self._futures:
                return
            future = self._pool.submit(self._guarded, fn)
            self._futures[run_id] = future
        future.add_done_callback(lambda _future: self._forget(run_id))

    def _guarded(self, fn: Callable[[], object]) -> None:
        try:
            fn()
        except Exception:  # pragma: no cover - service already records failures
            logger.exception("Background task crashed")

    def _forget(self, run_id: str) -> None:
        with self._lock:
            self._futures.pop(run_id, None)
