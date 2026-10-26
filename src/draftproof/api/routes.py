"""HTTP routes for runs, streaming, artifacts and operations."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from draftproof import __version__
from draftproof.api.manager import RunManager
from draftproof.api.metrics import Metrics
from draftproof.api.schemas import (
    CancelResponse,
    CreateRunRequest,
    HealthResponse,
    RegenerateRequest,
    ReviewRequest,
    RubricResponse,
    RunCreated,
    RunPage,
)
from draftproof.api.security import ApiKeyGuard, TokenBucketLimiter, client_key
from draftproof.api.sse import format_comment, format_end, format_event
from draftproof.domain.errors import ConflictError, RunNotFoundError
from draftproof.domain.models import (
    TERMINAL_STATUSES,
    ProviderInfo,
    ReviewDecision,
    RunRecord,
    RunStatus,
    RunSummary,
    ServerMeta,
)
from draftproof.pipeline.service import RunService
from draftproof.storage.files import ARTIFACT_FILENAMES

router = APIRouter(prefix="/api/v1")

_MEDIA_TYPES: dict[str, str] = {
    "markdown": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "jsonld": "application/ld+json; charset=utf-8",
    "social": "application/json; charset=utf-8",
    "manifest": "application/json; charset=utf-8",
    "quality": "application/json; charset=utf-8",
    "outline": "application/json; charset=utf-8",
}


# ----------------------------------------------------------------------
# Dependencies
# ----------------------------------------------------------------------
def get_service(request: Request) -> RunService:
    """Resolve the run service from application state."""
    service: RunService = request.app.state.service
    return service


def get_manager(request: Request) -> RunManager:
    """Resolve the background run manager."""
    manager: RunManager = request.app.state.manager
    return manager


def get_metrics(request: Request) -> Metrics:
    """Resolve the metrics registry."""
    metrics: Metrics = request.app.state.metrics
    return metrics


def require_access(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Enforce API key authentication and rate limiting."""
    guard: ApiKeyGuard = request.app.state.guard
    limiter: TokenBucketLimiter = request.app.state.limiter
    guard.check(x_api_key)
    host = request.client.host if request.client else None
    limiter.check(client_key(host, x_api_key))


Protected = [Depends(require_access)]


# ----------------------------------------------------------------------
# Operational endpoints
# ----------------------------------------------------------------------
@router.get("/health", response_model=HealthResponse, tags=["ops"])
def health(request: Request) -> HealthResponse:
    """Report liveness, version and database status."""
    service = get_service(request)
    try:
        service.repo.count_runs()
        database = "ok"
    except Exception:  # pragma: no cover - defensive
        database = "error"
    started = getattr(request.app.state, "started_at", time.monotonic())
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        version=__version__,
        database=database,
        uptime_seconds=round(time.monotonic() - started, 1),
    )


@router.get("/meta", response_model=ServerMeta, tags=["ops"])
def meta(request: Request) -> ServerMeta:
    """Advertise runtime capabilities to the studio UI."""
    service = get_service(request)
    settings = service.settings
    providers: list[ProviderInfo] = service.describe_providers()
    return ServerMeta(
        version=__version__,
        provider_chain=settings.provider_chain,
        retriever=settings.retriever,
        verification=settings.verification_mode,
        review_required=settings.review_required,
        api_key_required=settings.api_key_required,
        limits={
            "max_body_bytes": settings.max_body_bytes,
            "rate_limit_per_minute": settings.rate_limit_per_minute,
            "max_cost_usd": settings.max_cost_usd,
            "concurrency": settings.concurrency,
            "evidence_limit": settings.evidence_limit,
            "max_revision_attempts": settings.max_revision_attempts,
        },
        providers=providers,
    )


@router.get("/rubric", response_model=RubricResponse, dependencies=Protected, tags=["ops"])
def rubric(request: Request) -> RubricResponse:
    """Expose the active rubric so the UI can explain every score."""
    active = get_service(request).rubric
    return RubricResponse(
        weights=active.weights,
        gates=[
            {"key": gate.key, "minimum": gate.minimum, "condition": gate.condition}
            for gate in active.gates
        ],
        flesch_target=[active.flesch_target[0], active.flesch_target[1]],
    )


@router.get("/metrics", response_class=PlainTextResponse, dependencies=Protected, tags=["ops"])
def metrics(request: Request) -> PlainTextResponse:
    """Expose Prometheus-style counters."""
    registry = get_metrics(request)
    registry.gauge("draftproof_active_runs", float(get_manager(request).active()))
    return PlainTextResponse(registry.render(), media_type="text/plain; version=0.0.4")


# ----------------------------------------------------------------------
# Runs
# ----------------------------------------------------------------------
@router.post(
    "/runs",
    response_model=RunCreated,
    status_code=202,
    dependencies=Protected,
    tags=["runs"],
)
def create_run(payload: CreateRunRequest, request: Request) -> RunCreated:
    """Queue a run and start it in the background."""
    manager = get_manager(request)
    run = manager.start(payload.to_brief())
    get_metrics(request).inc("draftproof_http_requests_total", {"route": "create_run"})
    return RunCreated(
        run_id=run.id,
        status=run.status,
        topic=run.brief.topic,
        stream_url=f"/api/v1/runs/{run.id}/events",
    )


@router.get("/runs", response_model=RunPage, dependencies=Protected, tags=["runs"])
def list_runs(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: RunStatus | None = None,
) -> RunPage:
    """List runs, newest first."""
    service = get_service(request)
    summaries: list[RunSummary] = service.repo.list_runs(limit=limit, offset=offset, status=status)
    total = service.repo.count_runs(status)
    get_metrics(request).inc("draftproof_http_requests_total", {"route": "list_runs"})
    return RunPage(items=summaries, total=total, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunRecord, dependencies=Protected, tags=["runs"])
def get_run(run_id: str, request: Request) -> RunRecord:
    """Return the full record of one run."""
    run = get_service(request).get_run(run_id)
    get_metrics(request).inc("draftproof_http_requests_total", {"route": "get_run"})
    return run


@router.delete(
    "/runs/{run_id}", response_model=CancelResponse, dependencies=Protected, tags=["runs"]
)
def cancel_run(run_id: str, request: Request) -> CancelResponse:
    """Request cancellation of a queued or running pipeline."""
    service = get_service(request)
    manager = get_manager(request)
    service.get_run(run_id)
    cancelled = manager.cancel(run_id)
    current = service.get_run(run_id)
    get_metrics(request).inc("draftproof_http_requests_total", {"route": "cancel_run"})
    return CancelResponse(run_id=run_id, cancelled=cancelled, status=current.status)


@router.post(
    "/runs/{run_id}/resume",
    response_model=RunCreated,
    status_code=202,
    dependencies=Protected,
    tags=["runs"],
)
def resume_run(run_id: str, request: Request) -> RunCreated:
    """Resume a failed or cancelled run from its last checkpoint."""
    service = get_service(request)
    manager = get_manager(request)
    run = service.get_run(run_id)
    if run.status not in {RunStatus.FAILED, RunStatus.CANCELLED}:
        raise ConflictError(
            f"Run '{run_id}' is {run.status.value}; only failed or cancelled runs can resume"
        )
    manager.submit(run_id, resume=True)
    return RunCreated(
        run_id=run_id,
        status=RunStatus.QUEUED,
        topic=run.brief.topic,
        stream_url=f"/api/v1/runs/{run_id}/events",
    )


@router.get("/runs/{run_id}/events", dependencies=Protected, tags=["runs"])
async def stream_events(
    run_id: str,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """Stream run events as Server-Sent Events, replayable via ``after``."""
    service = get_service(request)
    await asyncio.to_thread(service.get_run, run_id)

    async def generator() -> AsyncIterator[str]:
        last = after
        idle = 0
        yield format_comment(f"stream {run_id}")
        while True:
            rows = await asyncio.to_thread(service.repo.events_since, run_id, last, 200)
            if rows:
                idle = 0
                for row in rows:
                    last = int(row["seq"])
                    yield format_event(last, str(row["type"]), row["data"], str(row["created_at"]))
                continue
            current = await asyncio.to_thread(service.get_run, run_id)
            if current.status in TERMINAL_STATUSES or current.status is RunStatus.AWAITING_REVIEW:
                yield format_end(current.status.value)
                break
            idle += 1
            if idle % 20 == 0:
                yield format_comment()
            await asyncio.sleep(0.35)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/runs/{run_id}/artifacts/{kind}",
    dependencies=Protected,
    tags=["artifacts"],
    response_class=FileResponse,
)
def download_artifact(run_id: str, kind: str, request: Request) -> FileResponse:
    """Download a published artifact."""
    service = get_service(request)
    service.get_run(run_id)
    if kind not in ARTIFACT_FILENAMES:
        raise RunNotFoundError(
            f"Unknown artifact '{kind}'",
            hint=f"Available artifacts: {', '.join(sorted(ARTIFACT_FILENAMES))}.",
        )
    path: Path = service.artifacts.path_for(run_id, kind)
    if not path.exists():
        raise RunNotFoundError(f"Artifact '{kind}' is not ready for run '{run_id}'")
    inline = kind in {"html", "markdown"}
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(kind, "application/octet-stream"),
        filename=f"draftproof-{run_id}-{path.name}" if not inline else path.name,
        content_disposition_type="inline" if inline else "attachment",
    )


# ----------------------------------------------------------------------
# Editorial workflow
# ----------------------------------------------------------------------
@router.post(
    "/runs/{run_id}/review",
    response_model=RunRecord,
    dependencies=Protected,
    tags=["review"],
)
def review_run(
    run_id: str, payload: ReviewRequest, request: Request, response: Response
) -> RunRecord:
    """Approve a run, or request changes that trigger a revision."""
    service = get_service(request)
    manager = get_manager(request)
    if payload.decision is ReviewDecision.APPROVE:
        get_metrics(request).inc("draftproof_reviews_total", {"decision": "approve"})
        return service.approve(run_id, notes=payload.notes, reviewer=payload.reviewer)

    manager.submit_revision(
        run_id,
        notes=payload.notes,
        reviewer=payload.reviewer,
        section_ids=payload.section_ids,
    )
    get_metrics(request).inc("draftproof_reviews_total", {"decision": "request_changes"})
    response.status_code = 202
    return service.get_run(run_id)


@router.post(
    "/runs/{run_id}/sections/{section_id}/regenerate",
    response_model=RunRecord,
    status_code=202,
    dependencies=Protected,
    tags=["review"],
)
def regenerate_section(
    run_id: str,
    section_id: str,
    payload: RegenerateRequest,
    request: Request,
) -> RunRecord:
    """Rewrite a single section after editorial feedback."""
    service = get_service(request)
    manager = get_manager(request)
    run = service.get_run(run_id)
    known = {section.plan.id for section in run.sections}
    if section_id not in known:
        raise RunNotFoundError(f"Section '{section_id}' does not exist in run '{run_id}'")
    manager.submit_revision(
        run_id,
        notes=payload.notes or f"Regenerate section {section_id}",
        reviewer=payload.reviewer,
        section_ids=[section_id],
    )
    get_metrics(request).inc("draftproof_reviews_total", {"decision": "regenerate"})
    return service.get_run(run_id)


def api_metadata() -> dict[str, Any]:
    """Return OpenAPI metadata shared by the app factory."""
    return {
        "title": "DraftProof API",
        "description": (
            "Evidence-first publishing pipeline: plan, research, draft, verify claims, "
            "score against a rubric, revise and publish with a provenance manifest."
        ),
        "version": __version__,
    }
