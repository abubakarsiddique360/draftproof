"""Lenient intermediate schemas for model output.

Raw models tolerate messy real-world LLM output; normalisation into the strict
domain models happens in one place so the pipeline stays predictable.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from draftproof.domain.errors import InvalidModelOutputError
from draftproof.domain.models import Brief, Outline, SectionPlan


class RawSection(BaseModel):
    id: str = ""
    title: str = ""
    goal: str = ""
    key_points: list[str] = Field(default_factory=list)
    target_words: int = 240
    requires_evidence: bool = False
    requires_code: bool = False


class RawOutline(BaseModel):
    title: str = ""
    subtitle: str | None = None
    thesis: str = ""
    meta_description: str = ""
    tags: list[str] = Field(default_factory=list)
    sections: list[RawSection] = Field(default_factory=list)


class RawClaim(BaseModel):
    text: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class RawClaims(BaseModel):
    claims: list[RawClaim] = Field(default_factory=list)


def _fit(text: str, *, low: int, high: int, filler: str) -> str:
    cleaned = " ".join(str(text).split())
    if len(cleaned) < low:
        cleaned = f"{cleaned} {filler}".strip()
    if len(cleaned) > high:
        cleaned = cleaned[:high].rsplit(" ", 1)[0].rstrip(".,;:")
    return cleaned


def normalize_outline(raw: RawOutline, brief: Brief, *, evidence_available: bool) -> Outline:
    """Turn loose model output into a valid, word-balanced outline."""
    candidates = [section for section in raw.sections if section.title.strip()]
    if len(candidates) < 3:
        raise InvalidModelOutputError(
            f"Outline needs at least 3 sections, received {len(candidates)}",
            task="plan_outline",
        )
    candidates = candidates[:8]

    per_section = max(120, brief.target_words // len(candidates))
    sections: list[SectionPlan] = []
    for index, item in enumerate(candidates, start=1):
        title = _fit(item.title, low=3, high=140, filler=f"Part {index}")
        goal = _fit(
            item.goal,
            low=10,
            high=400,
            filler=f"Explain {title.lower()} so the reader can apply it immediately.",
        )
        points = [" ".join(point.split())[:240] for point in item.key_points if point.strip()]
        sections.append(
            SectionPlan(
                id=f"s{index}",
                title=title,
                goal=goal,
                key_points=points[:5],
                target_words=max(80, min(1200, item.target_words or per_section)),
                requires_evidence=bool(
                    item.requires_evidence or brief.sources_required or evidence_available
                ),
                requires_code=bool(item.requires_code),
            )
        )

    title = _fit(
        raw.title,
        low=5,
        high=120,
        filler=f"A practical guide to {brief.topic}",
    )
    thesis = _fit(
        raw.thesis,
        low=20,
        high=600,
        filler=f"{brief.topic} rewards teams that define invariants and measure outcomes.",
    )
    meta = _fit(
        raw.meta_description,
        low=40,
        high=200,
        filler=f"A practical, evidence-aware guide to {brief.topic} for {brief.audience}.",
    )
    tags = [" ".join(tag.split())[:40] for tag in raw.tags if tag.strip()][:8]
    subtitle = _fit(raw.subtitle, low=0, high=160, filler="") if raw.subtitle else None

    return Outline(
        title=title,
        subtitle=subtitle or None,
        thesis=thesis,
        meta_description=meta,
        tags=tags,
        sections=sections,
    )
