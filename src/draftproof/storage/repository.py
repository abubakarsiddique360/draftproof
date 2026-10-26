"""Repository: the single place that knows how runs are persisted."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from draftproof.domain.errors import RunNotFoundError
from draftproof.domain.models import (
    TERMINAL_STATUSES,
    Artifact,
    Brief,
    Claim,
    Evidence,
    EvidenceStatus,
    Outline,
    QualityReport,
    Review,
    RunRecord,
    RunStatus,
    RunSummary,
    Section,
    SectionPlan,
    SectionStatus,
    Usage,
    utc_now,
)
from draftproof.storage.db import Database
from draftproof.storage.files import new_run_id


def _now() -> str:
    return utc_now().isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Repository:
    """Persistence facade for runs, content, events and reviews."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    def create_run(
        self,
        brief: Brief,
        *,
        provider: str,
        model: str,
        settings_snapshot: dict[str, Any],
        parent_run_id: str | None = None,
        run_id: str | None = None,
    ) -> RunRecord:
        identifier = run_id or new_run_id()
        now = _now()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO runs (id, created_at, updated_at, status, topic, brief_json,"
                " settings_json, provider, model, parent_run_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    now,
                    now,
                    RunStatus.QUEUED.value,
                    brief.topic,
                    brief.model_dump_json(),
                    _dumps(settings_snapshot),
                    provider,
                    model,
                    parent_run_id,
                ),
            )
        return self.get_run(identifier)

    def get_run(self, run_id: str) -> RunRecord:
        row = self.db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
        if row is None:
            raise RunNotFoundError(f"Run '{run_id}' was not found")
        return self._assemble(row)

    def try_get_run(self, run_id: str) -> RunRecord | None:
        try:
            return self.get_run(run_id)
        except RunNotFoundError:
            return None

    def list_runs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: RunStatus | None = None,
    ) -> list[RunSummary]:
        clauses = ""
        params: list[Any] = []
        if status is not None:
            clauses = " WHERE status = ?"
            params.append(status.value)
        params.extend([max(1, min(limit, 100)), max(0, offset)])
        rows = self.db.query_all(
            "SELECT id, topic, status, provider, model, quality_json, created_at, cost_usd"  # noqa: S608
            f" FROM runs{clauses} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            params,
        )
        summaries: list[RunSummary] = []
        for row in rows:
            quality = (
                QualityReport.model_validate_json(row["quality_json"])
                if row["quality_json"]
                else None
            )
            summaries.append(
                RunSummary(
                    id=row["id"],
                    topic=row["topic"],
                    status=RunStatus(row["status"]),
                    provider=row["provider"],
                    model=row["model"],
                    score=quality.score if quality else None,
                    passed=quality.passed if quality else None,
                    created_at=_parse_dt(row["created_at"]) or utc_now(),
                    cost_usd=row["cost_usd"],
                )
            )
        return summaries

    def set_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
    ) -> None:
        finished = status in TERMINAL_STATUSES
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, updated_at = ?, error = ?,"
                " finished_at = CASE WHEN ? THEN ? ELSE finished_at END WHERE id = ?",
                (
                    status.value,
                    _now(),
                    error,
                    1 if finished else 0,
                    _now(),
                    run_id,
                ),
            )

    def set_error(self, run_id: str, message: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE runs SET error = ?, updated_at = ? WHERE id = ?",
                (message[:2000], _now(), run_id),
            )

    def set_usage(self, run_id: str, usage: Usage) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE runs SET prompt_tokens = ?, completion_tokens = ?, cost_usd = ?,"
                " llm_calls = ?, updated_at = ? WHERE id = ?",
                (
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    usage.cost_usd,
                    usage.calls,
                    _now(),
                    run_id,
                ),
            )

    def save_outline(self, run_id: str, outline: Outline) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE runs SET outline_json = ?, updated_at = ? WHERE id = ?",
                (outline.model_dump_json(), _now(), run_id),
            )

    def save_quality(self, run_id: str, report: QualityReport) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE runs SET quality_json = ?, updated_at = ? WHERE id = ?",
                (report.model_dump_json(), _now(), run_id),
            )

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------
    def upsert_section(self, run_id: str, position: int, section: Section) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO sections (run_id, section_id, position, title, plan_json, markdown,"
                " attempt, status, grounding, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(run_id, section_id) DO UPDATE SET position = excluded.position,"
                " title = excluded.title, plan_json = excluded.plan_json,"
                " markdown = excluded.markdown, attempt = excluded.attempt,"
                " status = excluded.status, grounding = excluded.grounding,"
                " updated_at = excluded.updated_at",
                (
                    run_id,
                    section.plan.id,
                    position,
                    section.plan.title,
                    section.plan.model_dump_json(),
                    section.markdown,
                    section.attempt,
                    section.status.value,
                    section.grounding,
                    _now(),
                ),
            )

    def replace_evidence(self, run_id: str, evidence: Sequence[Evidence]) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM evidence WHERE run_id = ?", (run_id,))
            for item in evidence:
                self._insert_evidence(conn, run_id, item)

    def update_evidence(self, run_id: str, evidence: Sequence[Evidence]) -> None:
        with self.db.transaction() as conn:
            for item in evidence:
                conn.execute(
                    "UPDATE evidence SET status = ?, http_status = ?, overlap = ?,"
                    " content_hash = ?, injection_suspected = ?"
                    " WHERE run_id = ? AND evidence_id = ?",
                    (
                        item.status.value,
                        item.http_status,
                        item.overlap,
                        item.content_hash,
                        1 if item.injection_suspected else 0,
                        run_id,
                        item.id,
                    ),
                )

    def replace_claims(
        self,
        run_id: str,
        claims: Sequence[Claim],
        *,
        section_ids: Sequence[str] | None = None,
    ) -> None:
        with self.db.transaction() as conn:
            if section_ids is None:
                conn.execute("DELETE FROM claims WHERE run_id = ?", (run_id,))
            else:
                for section_id in section_ids:
                    conn.execute(
                        "DELETE FROM claims WHERE run_id = ? AND section_id = ?",
                        (run_id, section_id),
                    )
            for claim in claims:
                conn.execute(
                    "INSERT INTO claims (run_id, claim_id, section_id, text, evidence_ids_json,"
                    " verified, confidence, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        claim.id,
                        claim.section_id,
                        claim.text,
                        _dumps(claim.evidence_ids),
                        1 if claim.verified else 0,
                        claim.confidence,
                        claim.note,
                    ),
                )

    # ------------------------------------------------------------------
    # Stages and checkpoints
    # ------------------------------------------------------------------
    def start_stage(self, run_id: str, stage: str, attempt: int = 1) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO stages (run_id, stage, attempt, status, started_at)"
                " VALUES (?, ?, ?, 'running', ?)"
                " ON CONFLICT(run_id, stage, attempt) DO UPDATE SET status = 'running',"
                " started_at = excluded.started_at, finished_at = NULL, detail = NULL",
                (run_id, stage, attempt, _now()),
            )

    def finish_stage(
        self, run_id: str, stage: str, attempt: int = 1, detail: str | None = None
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE stages SET status = 'completed', finished_at = ?, detail = ?"
                " WHERE run_id = ? AND stage = ? AND attempt = ?",
                (_now(), detail, run_id, stage, attempt),
            )

    def fail_stage(self, run_id: str, stage: str, error: str, attempt: int = 1) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE stages SET status = 'failed', finished_at = ?, detail = ?"
                " WHERE run_id = ? AND stage = ? AND attempt = ?",
                (_now(), error[:2000], run_id, stage, attempt),
            )

    def save_checkpoint(self, run_id: str, stage: str, state: dict[str, Any]) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO checkpoints (run_id, stage, created_at, state_json)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(run_id, stage) DO UPDATE SET created_at = excluded.created_at,"
                " state_json = excluded.state_json",
                (run_id, stage, _now(), _dumps(state)),
            )

    def load_checkpoints(self, run_id: str) -> dict[str, dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT stage, state_json FROM checkpoints WHERE run_id = ?", (run_id,)
        )
        return {row["stage"]: json.loads(row["state_json"]) for row in rows}

    def clear_checkpoints(self, run_id: str, *, stages: Iterable[str] | None = None) -> None:
        with self.db.transaction() as conn:
            if stages is None:
                conn.execute("DELETE FROM checkpoints WHERE run_id = ?", (run_id,))
                return
            for stage in stages:
                conn.execute(
                    "DELETE FROM checkpoints WHERE run_id = ? AND stage = ?", (run_id, stage)
                )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def append_event(self, run_id: str, event_type: str, data: dict[str, Any]) -> int:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO events (run_id, created_at, type, data_json) VALUES (?, ?, ?, ?)",
                (run_id, _now(), event_type, _dumps(data)),
            )
            return int(cursor.lastrowid or 0)

    def events_since(self, run_id: str, after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT seq, created_at, type, data_json FROM events"
            " WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (run_id, after, max(1, min(limit, 500))),
        )
        return [
            {
                "seq": row["seq"],
                "created_at": row["created_at"],
                "type": row["type"],
                "data": json.loads(row["data_json"]),
            }
            for row in rows
        ]

    def last_event_seq(self, run_id: str) -> int:
        value = self.db.scalar(
            "SELECT COALESCE(MAX(seq), 0) FROM events WHERE run_id = ?", (run_id,)
        )
        return int(value or 0)

    # ------------------------------------------------------------------
    # Artifacts and reviews
    # ------------------------------------------------------------------
    def add_artifact(self, run_id: str, artifact: Artifact) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO artifacts (run_id, kind, relative_path, sha256, bytes, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(run_id, kind) DO UPDATE SET"
                " relative_path = excluded.relative_path, sha256 = excluded.sha256,"
                " bytes = excluded.bytes, created_at = excluded.created_at",
                (
                    run_id,
                    artifact.kind,
                    artifact.relative_path,
                    artifact.sha256,
                    artifact.bytes,
                    artifact.created_at.isoformat(),
                ),
            )

    def add_review(self, run_id: str, review: Review) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO reviews (run_id, decision, notes, reviewer, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    review.decision.value,
                    review.notes,
                    review.reviewer,
                    review.created_at.isoformat(),
                ),
            )

    def stats(self) -> dict[str, int]:
        rows = self.db.query_all("SELECT status, COUNT(*) AS total FROM runs GROUP BY status")
        return {row["status"]: int(row["total"]) for row in rows}

    def count_runs(self, status: RunStatus | None = None) -> int:
        if status is None:
            return int(self.db.scalar("SELECT COUNT(*) FROM runs") or 0)
        return int(
            self.db.scalar("SELECT COUNT(*) FROM runs WHERE status = ?", (status.value,)) or 0
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _insert_evidence(self, conn: Any, run_id: str, item: Evidence) -> None:
        conn.execute(
            "INSERT INTO evidence (run_id, evidence_id, title, url, domain, snippet,"
            " published_at, retrieved_at, status, http_status, overlap, content_hash, source,"
            " injection_suspected) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                item.id,
                item.title,
                item.url,
                item.domain,
                item.snippet,
                item.published_at,
                item.retrieved_at.isoformat(),
                item.status.value,
                item.http_status,
                item.overlap,
                item.content_hash,
                item.source,
                1 if item.injection_suspected else 0,
            ),
        )

    def _assemble(self, row: Any) -> RunRecord:
        run_id = row["id"]
        section_rows = self.db.query_all(
            "SELECT * FROM sections WHERE run_id = ? ORDER BY position", (run_id,)
        )
        claim_rows = self.db.query_all(
            "SELECT * FROM claims WHERE run_id = ? ORDER BY claim_id", (run_id,)
        )
        claims_by_section: dict[str, list[Claim]] = {}
        for claim_row in claim_rows:
            claim = Claim(
                id=claim_row["claim_id"],
                section_id=claim_row["section_id"],
                text=claim_row["text"],
                evidence_ids=json.loads(claim_row["evidence_ids_json"]),
                verified=bool(claim_row["verified"]),
                confidence=claim_row["confidence"],
                note=claim_row["note"],
            )
            claims_by_section.setdefault(claim.section_id, []).append(claim)

        sections: list[Section] = []
        for section_row in section_rows:
            sections.append(
                Section(
                    plan=SectionPlan.model_validate_json(section_row["plan_json"]),
                    markdown=section_row["markdown"],
                    attempt=section_row["attempt"],
                    status=SectionStatus(section_row["status"]),
                    grounding=section_row["grounding"],
                    claims=claims_by_section.get(section_row["section_id"], []),
                )
            )

        evidence = [
            Evidence(
                id=item["evidence_id"],
                title=item["title"],
                url=item["url"],
                domain=item["domain"],
                snippet=item["snippet"],
                published_at=item["published_at"],
                retrieved_at=_parse_dt(item["retrieved_at"]) or utc_now(),
                status=EvidenceStatus(item["status"]),
                http_status=item["http_status"],
                overlap=item["overlap"],
                content_hash=item["content_hash"],
                source=item["source"],
                injection_suspected=bool(item["injection_suspected"]),
            )
            for item in self.db.query_all(
                "SELECT * FROM evidence WHERE run_id = ? ORDER BY evidence_id", (run_id,)
            )
        ]

        artifacts = [
            Artifact(
                kind=item["kind"],
                relative_path=item["relative_path"],
                sha256=item["sha256"],
                bytes=item["bytes"],
                created_at=_parse_dt(item["created_at"]) or utc_now(),
            )
            for item in self.db.query_all(
                "SELECT * FROM artifacts WHERE run_id = ? ORDER BY kind", (run_id,)
            )
        ]

        reviews = [
            Review(
                decision=item["decision"],
                notes=item["notes"],
                reviewer=item["reviewer"],
                created_at=_parse_dt(item["created_at"]) or utc_now(),
            )
            for item in self.db.query_all(
                "SELECT * FROM reviews WHERE run_id = ? ORDER BY id", (run_id,)
            )
        ]

        return RunRecord(
            id=run_id,
            created_at=_parse_dt(row["created_at"]) or utc_now(),
            updated_at=_parse_dt(row["updated_at"]) or utc_now(),
            finished_at=_parse_dt(row["finished_at"]),
            status=RunStatus(row["status"]),
            brief=Brief.model_validate_json(row["brief_json"]),
            provider=row["provider"],
            model=row["model"],
            parent_run_id=row["parent_run_id"],
            outline=Outline.model_validate_json(row["outline_json"])
            if row["outline_json"]
            else None,
            quality=QualityReport.model_validate_json(row["quality_json"])
            if row["quality_json"]
            else None,
            usage=Usage(
                prompt_tokens=row["prompt_tokens"],
                completion_tokens=row["completion_tokens"],
                calls=row["llm_calls"],
                cost_usd=row["cost_usd"],
            ),
            artifacts=artifacts,
            sections=sections,
            evidence=evidence,
            reviews=reviews,
            error=row["error"],
        )
