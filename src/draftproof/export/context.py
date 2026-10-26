"""Shared context object for every exporter."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from draftproof.domain.models import (
    Brief,
    Claim,
    Evidence,
    Outline,
    QualityReport,
    Section,
    Usage,
)


@dataclass(frozen=True, slots=True)
class ExportContext:
    """Everything an exporter needs to render one run."""

    run_id: str
    brief: Brief
    outline: Outline
    sections: Sequence[Section]
    evidence: Sequence[Evidence]
    claims: Sequence[Claim]
    quality: QualityReport
    usage: Usage
    provider: str
    model: str
    verification: str
    generated_at: datetime
    generator_version: str
    revision_attempts: int = 0

    @property
    def body_markdown(self) -> str:
        return "\n\n".join(section.markdown.strip() for section in self.sections).strip()

    @property
    def total_words(self) -> int:
        return sum(len(section.markdown.split()) for section in self.sections)

    def evidence_by_id(self) -> dict[str, Evidence]:
        return {item.id: item for item in self.evidence}
