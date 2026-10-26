"""Mutable state carried through one pipeline execution."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from draftproof.config import Settings
from draftproof.domain.errors import CancelledError
from draftproof.domain.models import (
    Brief,
    Claim,
    Evidence,
    Outline,
    QualityReport,
    Section,
    SectionStatus,
)
from draftproof.quality.rubric import Rubric
from draftproof.research.retrievers import Retriever
from draftproof.research.verifier import Verifier
from draftproof.storage.files import ArtifactStore
from draftproof.storage.repository import Repository

if TYPE_CHECKING:
    from draftproof.pipeline.events import EventSink
    from draftproof.providers.router import ModelRouter


@dataclass(slots=True)
class PipelineContext:
    """Everything a stage may read or mutate for a single run."""

    run_id: str
    brief: Brief
    settings: Settings
    router: ModelRouter
    repo: Repository
    artifacts: ArtifactStore
    sink: EventSink
    retriever: Retriever
    verifier: Verifier
    rubric: Rubric
    cancel: threading.Event = field(default_factory=threading.Event)
    outline: Outline | None = None
    evidence: list[Evidence] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    quality: QualityReport | None = None
    revision_attempts: int = 0
    warnings: list[str] = field(default_factory=list)
    target_section_ids: set[str] | None = None
    review_directives: dict[str, list[str]] = field(default_factory=dict)
    auto_complete: bool = False
    model_name: str = ""

    def check_cancelled(self) -> None:
        if self.cancel.is_set():
            raise CancelledError("Run was cancelled")

    @property
    def claims(self) -> list[Claim]:
        return [claim for section in self.sections for claim in section.claims]

    def section(self, section_id: str) -> Section:
        for item in self.sections:
            if item.plan.id == section_id:
                return item
        raise KeyError(section_id)

    def set_section_claims(self, section_id: str, claims: list[Claim]) -> None:
        for index, item in enumerate(self.sections):
            if item.plan.id == section_id:
                self.sections[index] = item.model_copy(update={"claims": claims})
                return

    def replace_claims(self, claims: list[Claim]) -> None:
        grouped: dict[str, list[Claim]] = {}
        for claim in claims:
            grouped.setdefault(claim.section_id, []).append(claim)
        for index, item in enumerate(self.sections):
            self.sections[index] = item.model_copy(update={"claims": grouped.get(item.plan.id, [])})

    def mark_grounding(self) -> None:
        for index, item in enumerate(self.sections):
            total = len(item.claims)
            verified = sum(1 for claim in item.claims if claim.verified)
            grounding = round(verified / total, 4) if total else 1.0
            self.sections[index] = item.model_copy(update={"grounding": grounding})

    def targets(self) -> list[str]:
        if self.target_section_ids is None:
            return [section.plan.id for section in self.sections]
        return list(self.target_section_ids)

    def directives_for(self, section_id: str) -> list[str]:
        directives = list(self.review_directives.get(section_id, []))
        directives.extend(self.review_directives.get("*", []))
        return directives

    def set_section_status(self, section_id: str, status: SectionStatus, attempt: int) -> None:
        for index, item in enumerate(self.sections):
            if item.plan.id == section_id:
                self.sections[index] = item.model_copy(
                    update={"status": status, "attempt": attempt}
                )
                return

    def sort_sections(self) -> None:
        if self.outline is None:
            return
        order = {plan.id: index for index, plan in enumerate(self.outline.sections)}
        self.sections.sort(key=lambda section: order.get(section.plan.id, 999))
