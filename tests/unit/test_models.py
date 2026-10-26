"""Domain model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from draftproof.domain.models import (
    TERMINAL_STATUSES,
    Brief,
    Outline,
    RunStatus,
    SectionPlan,
    Usage,
)


def test_brief_normalizes_whitespace_and_lists() -> None:
    brief = Brief(
        topic="  Vector   search  ",
        key_points=["  first  ", "first", "", "second"],
        must_avoid=["  fluff "],
    )
    assert brief.topic == "Vector search"
    assert brief.key_points == ["first", "second"]
    assert brief.must_avoid == ["fluff"]


def test_brief_rejects_short_topic() -> None:
    with pytest.raises(ValidationError):
        Brief(topic="ai")


def test_brief_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Brief(topic="Valid topic", unknown_field=1)  # type: ignore[call-arg]


def _section(section_id: str, title: str = "A section") -> SectionPlan:
    return SectionPlan(
        id=section_id,
        title=title,
        goal="Explain the section clearly for the reader.",
        key_points=["one", "two"],
        target_words=200,
    )


def test_outline_requires_unique_section_ids() -> None:
    with pytest.raises(ValidationError):
        Outline(
            title="A valid article title",
            thesis="A thesis long enough to satisfy the model constraints.",
            meta_description="A description that is long enough to satisfy the minimum length.",
            sections=[_section("s1"), _section("s1")],
        )


def test_outline_rejects_too_few_sections() -> None:
    with pytest.raises(ValidationError):
        Outline(
            title="A valid article title",
            thesis="A thesis long enough to satisfy the model constraints.",
            meta_description="A description that is long enough to satisfy the minimum length.",
            sections=[_section("s1"), _section("s2")],
        )


def test_usage_addition() -> None:
    left = Usage(prompt_tokens=10, completion_tokens=5, calls=1, cost_usd=0.01)
    right = Usage(prompt_tokens=20, completion_tokens=15, calls=2, cost_usd=0.02)
    total = left + right
    assert total.prompt_tokens == 30
    assert total.total_tokens == 50
    assert total.calls == 3
    assert total.cost_usd == pytest.approx(0.03)


def test_terminal_statuses() -> None:
    assert RunStatus.COMPLETED in TERMINAL_STATUSES
    assert RunStatus.AWAITING_REVIEW not in TERMINAL_STATUSES


def test_section_plan_rejects_bad_id() -> None:
    with pytest.raises(ValidationError):
        SectionPlan(
            id="section-1",
            title="A title",
            goal="A goal that is long enough to pass validation.",
            target_words=200,
        )
