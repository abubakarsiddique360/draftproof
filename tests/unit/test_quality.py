"""Deterministic quality metrics and rubric gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from draftproof.domain.errors import ConfigurationError
from draftproof.domain.models import Brief, Claim, Outline, Section, SectionPlan
from draftproof.quality.evaluator import (
    evaluate,
    failing_section_ids,
    global_directives,
)
from draftproof.quality.metrics import flesch_reading_ease, measure, prose_only
from draftproof.quality.rubric import (
    DEFAULT_WEIGHTS,
    Gate,
    Rubric,
    default_rubric,
    grade_for,
    load_rubric,
)


def _plan(section_id: str, title: str, *, code: bool = False) -> SectionPlan:
    return SectionPlan(
        id=section_id,
        title=title,
        goal=f"Explain {title.lower()} for a technical reader.",
        key_points=["first point", "second point"],
        target_words=200,
        requires_code=code,
    )


def _body(seed: int, *, sentences: int = 15) -> str:
    bank = [
        "keep the surface small because branches become incidents",
        "name the invariant first so changes stay cheap",
        "measure before you optimise since tails matter most",
        "write the failure case down before the feature ships",
        "set an explicit budget and enforce it in code",
        "prefer boring building blocks with visible costs",
        "record the decision, the owner and the date",
        "roll out behind a flag with a known owner",
        "keep vocabulary stable across code and dashboards",
        "retire the old path once the new one is proven",
        "log the identifier on every hop for cheaper debugging",
        "bound the retry count and surface the final failure",
    ]
    topics = ["latency", "cost", "rollback", "observability"]
    topic = topics[(seed - 1) % len(topics)]
    return " ".join(
        f"For {topic} note {index}, {bank[(seed + index) % len(bank)]}."
        for index in range(sentences)
    )


def _document(
    *,
    sections: int = 4,
    sources_required: bool = False,
    verified_ratio: float = 1.0,
    bad_code: bool = False,
    duplicate: bool = False,
) -> tuple[Outline, list[Section], list[Claim], Brief]:
    brief = Brief(topic="Production readiness", target_words=700, sources_required=sources_required)
    plans = [_plan(f"s{index}", f"Section {index}") for index in range(1, sections + 1)]
    outline = Outline(
        title="A practical production readiness guide",
        subtitle="What to check before launch",
        thesis="Production readiness comes from explicit invariants and measurable failure modes.",
        meta_description=(
            "A practical production readiness guide covering invariants, budgets, "
            "observability and rollback."
        ),
        tags=["production", "reliability", "engineering"],
        sections=plans,
    )

    built: list[Section] = []
    claims: list[Claim] = []
    for index, plan in enumerate(plans, start=1):
        body = _body(index)
        if duplicate:
            body = _body(1)
        markdown = f"## {plan.title}\n\n{body}\n"
        if bad_code:
            markdown += "\n```python\ndef broken(:\n    pass\n```\n"
        claim = Claim(
            id=f"s{index}c1",
            section_id=plan.id,
            text="Keep the surface area small because every extra branch is a future incident.",
            evidence_ids=["ev1"],
            verified=index <= round(sections * verified_ratio),
            confidence=0.8,
        )
        claims.append(claim)
        built.append(Section(plan=plan, markdown=markdown, claims=[claim]))
    return outline, built, claims, brief


def test_flesch_scales_with_complexity() -> None:
    simple = "The cat sat on the mat. The dog ran fast. We like this plan."
    complex_ = (
        "Notwithstanding the aforementioned considerations, the operationalisation of "
        "observability instrumentation necessitates comprehensive infrastructural remediation."
    )
    assert flesch_reading_ease(simple) > flesch_reading_ease(complex_)


def test_prose_only_removes_code_and_headings() -> None:
    cleaned = prose_only("# Heading\n\nText here.\n\n```python\nprint('x')\n```")
    assert "Heading" not in cleaned
    assert "print" not in cleaned
    assert "Text here." in cleaned


def test_measure_reports_expected_fields() -> None:
    outline, sections, claims, brief = _document()
    measurements = measure(outline=outline, sections=sections, claims=claims, brief=brief)
    assert measurements.total_words > 100
    assert measurements.structure >= 70
    assert measurements.citation_coverage == 100.0
    assert measurements.code_validity == 100.0
    assert measurements.repetition_ratio == 0.0


def test_repetition_detects_duplicate_sections() -> None:
    outline, sections, claims, brief = _document(duplicate=True)
    measurements = measure(outline=outline, sections=sections, claims=claims, brief=brief)
    assert measurements.repetition_ratio > 0.2


def test_code_validity_flags_broken_python() -> None:
    outline, sections, claims, brief = _document(bad_code=True)
    measurements = measure(outline=outline, sections=sections, claims=claims, brief=brief)
    assert measurements.code_validity < 100


def test_evaluate_passes_clean_document() -> None:
    outline, sections, claims, brief = _document()
    report = evaluate(outline=outline, sections=sections, claims=claims, brief=brief)
    assert report.passed is True
    assert report.failed_gates == []
    assert report.grade in {"A", "B", "C"}
    assert len(report.metrics) == len(DEFAULT_WEIGHTS)
    assert report.metric("structure") is not None


def test_evaluate_fails_when_citations_missing() -> None:
    outline, sections, claims, brief = _document(verified_ratio=0.0, sources_required=True)
    report = evaluate(outline=outline, sections=sections, claims=claims, brief=brief)
    assert report.passed is False
    assert "citation_coverage" in report.failed_gates
    assert any(issue.code == "section_grounding" for issue in report.issues)
    assert failing_section_ids(report)
    assert global_directives(report)


def test_evaluate_fails_thin_document() -> None:
    brief = Brief(topic="Thin content", target_words=1200)
    outline = Outline(
        title="A thin draft",
        thesis="A thesis that is long enough to satisfy the outline validator.",
        meta_description="A description that is long enough to satisfy the minimum length rule.",
        sections=[_plan("s1", "Only section"), _plan("s2", "Second section"), _plan("s3", "Third")],
    )
    sections = [
        Section(plan=plan, markdown=f"## {plan.title}\n\nShort.\n") for plan in outline.sections
    ]
    report = evaluate(outline=outline, sections=sections, claims=[], brief=brief)
    assert report.passed is False
    assert {"structure", "word_budget"} & set(report.failed_gates)


def test_rubric_weights_are_normalized() -> None:
    rubric = default_rubric()
    weights = rubric.normalized_weights()
    assert sum(weights.values()) == pytest.approx(1.0)


def test_rubric_gate_conditions() -> None:
    rubric = default_rubric()
    gate = Gate("citation_coverage", 70.0, "sources_required")
    assert rubric.applies(gate, sources_required=True, has_claims=True)
    assert not rubric.applies(gate, sources_required=False, has_claims=True)


def test_grades() -> None:
    assert grade_for(95) == "A"
    assert grade_for(85) == "B"
    assert grade_for(75) == "C"
    assert grade_for(65) == "D"
    assert grade_for(10) == "F"


def test_load_rubric_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "rubric.yml"
    path.write_text(
        "weights:\n  structure: 0.5\n  seo: 0.5\ngates:\n  - key: score\n    minimum: 80\n"
        "flesch_target: [30, 60]\n",
        encoding="utf-8",
    )
    rubric = load_rubric(path)
    assert rubric.weights["structure"] == 0.5
    assert rubric.gates[0].minimum == 80
    assert rubric.flesch_target == (30.0, 60.0)


def test_load_rubric_rejects_unknown_metric(tmp_path: Path) -> None:
    path = tmp_path / "bad.yml"
    path.write_text("weights:\n  mystery: 1\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_rubric(path)


def test_load_rubric_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        load_rubric(tmp_path / "nope.yml")


def test_custom_rubric_changes_outcome() -> None:
    outline, sections, claims, brief = _document()
    strict = Rubric(
        weights=dict(DEFAULT_WEIGHTS),
        gates=(Gate("structure", 100.0), Gate("score", 99.9)),
        flesch_target=(40.0, 65.0),
    )
    report = evaluate(outline=outline, sections=sections, claims=claims, brief=brief, rubric=strict)
    assert report.passed is False
    assert "score" in report.failed_gates
