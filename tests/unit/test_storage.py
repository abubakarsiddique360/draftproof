"""SQLite storage: migrations, repository round-trips and events."""

from __future__ import annotations

from pathlib import Path

import pytest

from draftproof.domain.errors import RunNotFoundError
from draftproof.domain.models import (
    Artifact,
    Brief,
    Claim,
    Evidence,
    EvidenceStatus,
    Review,
    ReviewDecision,
    RunStatus,
    Section,
    SectionPlan,
    Usage,
    utc_now,
)
from draftproof.storage.db import Database
from draftproof.storage.repository import Repository


@pytest.fixture()
def repo(tmp_path: Path) -> Repository:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return Repository(database)


def _brief() -> Brief:
    return Brief(topic="A testable topic", target_words=600)


def _section() -> Section:
    plan = SectionPlan(
        id="s1",
        title="A section",
        goal="Explain the section clearly for the reader.",
        key_points=["one", "two"],
        target_words=200,
    )
    return Section(plan=plan, markdown="## A section\n\nBody text.", attempt=1)


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    database = Database(tmp_path / "idempotent.db")
    first = database.migrate()
    second = database.migrate()
    assert first == ["001_init.sql"]
    assert second == []
    tables = {
        row["name"]
        for row in database.query_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"runs", "sections", "claims", "evidence", "events", "artifacts"} <= tables
    database.close()


def test_run_roundtrip(repo: Repository) -> None:
    run = repo.create_run(_brief(), provider="mock", model="mock-writer-1", settings_snapshot={})
    assert run.status is RunStatus.QUEUED
    repo.set_status(run.id, RunStatus.COMPLETED)
    loaded = repo.get_run(run.id)
    assert loaded.status is RunStatus.COMPLETED
    assert loaded.finished_at is not None
    assert loaded.brief.topic == "A testable topic"


def test_missing_run_raises(repo: Repository) -> None:
    with pytest.raises(RunNotFoundError):
        repo.get_run("run_missing")
    assert repo.try_get_run("run_missing") is None


def test_sections_claims_and_evidence(repo: Repository) -> None:
    run = repo.create_run(_brief(), provider="mock", model="m", settings_snapshot={})
    section = _section()
    repo.upsert_section(run.id, 0, section)

    claim = Claim(id="s1c1", section_id="s1", text="A claim about the world.")
    repo.replace_claims(run.id, [claim])

    evidence = Evidence(
        id="ev1",
        title="A source",
        url="https://docs.example.com/a",
        domain="docs.example.com",
        snippet="Some text",
        retrieved_at=utc_now(),
    )
    repo.replace_evidence(run.id, [evidence])
    evidence = evidence.model_copy(update={"status": EvidenceStatus.VERIFIED})
    repo.update_evidence(run.id, [evidence])

    loaded = repo.get_run(run.id)
    assert len(loaded.sections) == 1
    assert loaded.sections[0].claims[0].text == "A claim about the world."
    assert loaded.evidence[0].status.value == "verified"


def test_replace_claims_is_scoped_to_sections(repo: Repository) -> None:
    run = repo.create_run(_brief(), provider="mock", model="m", settings_snapshot={})
    repo.replace_claims(
        run.id,
        [
            Claim(id="s1c1", section_id="s1", text="First claim text."),
            Claim(id="s2c1", section_id="s2", text="Second claim text."),
        ],
    )
    repo.replace_claims(
        run.id, [Claim(id="s1c1", section_id="s1", text="Updated claim.")], section_ids=["s1"]
    )
    claims = repo.db.query_all("SELECT claim_id, text FROM claims WHERE run_id = ?", (run.id,))
    mapping = {row["claim_id"]: row["text"] for row in claims}
    assert mapping["s1c1"] == "Updated claim."
    assert mapping["s2c1"] == "Second claim text."


def test_events_and_checkpoints(repo: Repository) -> None:
    run = repo.create_run(_brief(), provider="mock", model="m", settings_snapshot={})
    first = repo.append_event(run.id, "log", {"message": "hello"})
    second = repo.append_event(run.id, "warning", {"message": "careful"})
    assert second > first
    assert [event["type"] for event in repo.events_since(run.id, 0)] == ["log", "warning"]
    assert [event["type"] for event in repo.events_since(run.id, first)] == ["warning"]
    assert repo.last_event_seq(run.id) == second

    repo.save_checkpoint(run.id, "plan", {"completed": True})
    assert "plan" in repo.load_checkpoints(run.id)
    repo.clear_checkpoints(run.id, stages=["plan"])
    assert repo.load_checkpoints(run.id) == {}


def test_artifacts_and_reviews(repo: Repository) -> None:
    run = repo.create_run(_brief(), provider="mock", model="m", settings_snapshot={})
    artifact = Artifact(
        kind="markdown",
        relative_path=f"{run.id}/article.md",
        sha256="abc",
        bytes=12,
    )
    repo.add_artifact(run.id, artifact)
    repo.add_review(
        run.id, Review(decision=ReviewDecision.APPROVE, notes="looks good", reviewer="editor")
    )
    loaded = repo.get_run(run.id)
    assert loaded.artifacts[0].kind == "markdown"
    assert loaded.reviews[0].decision is ReviewDecision.APPROVE


def test_list_and_count(repo: Repository) -> None:
    first = repo.create_run(_brief(), provider="mock", model="m", settings_snapshot={})
    repo.create_run(_brief(), provider="mock", model="m", settings_snapshot={})
    repo.set_status(first.id, RunStatus.COMPLETED)
    assert repo.count_runs() == 2
    assert repo.count_runs(RunStatus.COMPLETED) == 1
    summaries = repo.list_runs(limit=10)
    assert len(summaries) == 2
    assert summaries[0].topic == "A testable topic"
    assert repo.stats()["completed"] == 1


def test_usage_persisted(repo: Repository) -> None:
    run = repo.create_run(_brief(), provider="mock", model="m", settings_snapshot={})
    repo.set_usage(run.id, Usage(prompt_tokens=100, completion_tokens=50, calls=2, cost_usd=0.02))
    loaded = repo.get_run(run.id)
    assert loaded.usage.total_tokens == 150
    assert loaded.usage.calls == 2
