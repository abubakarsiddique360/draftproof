"""End-to-end pipeline behaviour against the deterministic mock provider."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from draftproof.config import Settings
from draftproof.domain.errors import ConflictError
from draftproof.domain.models import Brief, RunStatus
from draftproof.pipeline.service import RunService


def _service(settings: Settings) -> RunService:
    return RunService.build(settings)


def test_full_pipeline_completes(service: RunService, brief: Brief) -> None:
    run = service.create_run(brief)
    final = service.execute(run.id)

    assert final.status is RunStatus.COMPLETED
    assert final.quality is not None
    assert final.quality.passed is True
    assert final.finished_at is not None
    assert len(final.sections) >= 3
    claims = [claim for section in final.sections for claim in section.claims]
    assert claims and all(claim.verified for claim in claims)
    assert all(item.status.value == "verified" for item in final.evidence)
    assert {artifact.kind for artifact in final.artifacts} >= {
        "markdown",
        "html",
        "jsonld",
        "social",
        "manifest",
        "quality",
        "outline",
    }
    assert final.usage.calls >= 5
    assert final.usage.total_tokens > 0

    event_types = [event["type"] for event in service.repo.events_since(run.id)]
    assert "run_started" in event_types
    assert "outline_ready" in event_types
    assert "verification_ready" in event_types
    assert "quality_scored" in event_types
    assert "run_finished" in event_types

    markdown = service.artifacts.read_text(run.id, "markdown")
    assert markdown.startswith("---\n")
    assert "## Sources" in markdown


def test_resume_skips_completed_stages(service: RunService, brief: Brief) -> None:
    run = service.create_run(brief)
    service.execute(run.id)
    resumed = service.execute(run.id, resume=True)

    assert resumed.status is RunStatus.COMPLETED
    messages = [
        event["data"].get("message", "")
        for event in service.repo.events_since(run.id)
        if event["type"] == "log"
    ]
    assert any("skipped" in message for message in messages)


def test_cancel_before_start(service: RunService, brief: Brief) -> None:
    run = service.create_run(brief)
    assert service.cancel(run.id) is True
    final = service.execute(run.id)
    assert final.status is RunStatus.CANCELLED
    assert final.finished_at is not None


def test_cancel_finished_run_is_noop(service: RunService, brief: Brief) -> None:
    run = service.create_run(brief)
    service.execute(run.id)
    assert service.cancel(run.id) is False


def test_missing_evidence_fails_citation_gate(settings: Settings, brief: Brief) -> None:
    offline = settings.model_copy(update={"retriever": "none"})
    with _service(offline) as service:
        run = service.create_run(brief)
        final = service.execute(run.id)
        event_types = [event["type"] for event in service.repo.events_since(run.id)]
        assert "warning" in event_types
    assert final.status is RunStatus.COMPLETED
    assert final.quality is not None
    assert final.quality.passed is False
    assert "citation_coverage" in final.quality.failed_gates
    assert final.evidence == []


def test_review_required_then_approve(settings: Settings, brief: Brief) -> None:
    review_settings = settings.model_copy(update={"review_required": True})
    with _service(review_settings) as service:
        run = service.create_run(brief)
        final = service.execute(run.id)
        assert final.status is RunStatus.AWAITING_REVIEW

        approved = service.approve(run.id, notes="ship it", reviewer="editor")
        assert approved.status is RunStatus.COMPLETED
        assert approved.reviews[-1].notes == "ship it"

        with pytest.raises(ConflictError):
            service.approve(run.id)


def test_request_changes_revises_and_completes(settings: Settings, brief: Brief) -> None:
    review_settings = settings.model_copy(update={"review_required": True})
    with _service(review_settings) as service:
        run = service.create_run(brief)
        service.execute(run.id)
        revised = service.request_changes(
            run.id, notes="Tighten the introduction.", reviewer="editor"
        )
        assert revised.status is RunStatus.COMPLETED
        assert revised.reviews[-1].notes == "Tighten the introduction."


def test_regenerate_section_only_rewrites_target(settings: Settings, brief: Brief) -> None:
    no_revision = settings.model_copy(update={"max_revision_attempts": 0})
    with _service(no_revision) as service:
        run = service.create_run(brief)
        final = service.execute(run.id)
        first = final.sections[0]
        second = final.sections[1]

        revised = service.regenerate_section(run.id, first.plan.id, notes="Add a comparison table.")
    assert revised.status is RunStatus.COMPLETED
    updated_first = next(
        section for section in revised.sections if section.plan.id == first.plan.id
    )
    updated_second = next(
        section for section in revised.sections if section.plan.id == second.plan.id
    )
    assert updated_first.attempt > first.attempt
    assert updated_second.markdown == second.markdown


def test_request_changes_rejects_unknown_state(service: RunService, brief: Brief) -> None:
    run = service.create_run(brief)
    with pytest.raises(ConflictError):
        service.request_changes(run.id, notes="too early")


def test_threaded_cancel_event_stops_pipeline(service: RunService, brief: Brief) -> None:
    run = service.create_run(brief)
    cancel = threading.Event()
    cancel.set()
    final = service.execute(run.id, cancel_event=cancel)
    assert final.status is RunStatus.CANCELLED


def test_artifacts_are_written_under_the_data_dir(settings: Settings, brief: Brief) -> None:
    with _service(settings) as service:
        run = service.create_run(brief)
        service.execute(run.id)
        for artifact in service.get_run(run.id).artifacts:
            path = service.artifacts.resolve(artifact.relative_path)
            assert path.exists()
            assert Path(path).is_relative_to(settings.data_dir)
