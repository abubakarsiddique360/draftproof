"""Turn measurements into a scored, gated quality report."""

from __future__ import annotations

from collections.abc import Sequence

from draftproof.domain.models import (
    Brief,
    Claim,
    Issue,
    MetricResult,
    Outline,
    QualityReport,
    Section,
    Severity,
)
from draftproof.quality.metrics import Measurements, measure
from draftproof.quality.rubric import Rubric, default_rubric, grade_for

_LABELS = {
    "structure": "Document structure",
    "readability": "Readability (Flesch)",
    "citation_coverage": "Citation coverage",
    "repetition": "Cross-section repetition",
    "code_validity": "Code block validity",
    "word_budget": "Word budget fit",
    "seo": "Discoverability",
    "hedging": "Assertiveness",
}

_GUIDANCE: dict[str, tuple[Severity, str, str]] = {
    "structure": (
        Severity.MEDIUM,
        "Some sections are thin, unheaded or contain placeholders.",
        "Give every flagged section a '## ' heading, at least two substantial paragraphs and "
        "remove any placeholder text.",
    ),
    "readability": (
        Severity.LOW,
        "Sentences are long or dense for the target audience.",
        "Split sentences longer than 25 words and replace nominalisations with concrete verbs.",
    ),
    "citation_coverage": (
        Severity.HIGH,
        "Factual claims are not supported by verified evidence.",
        "Attach an evidence id to every factual claim and delete claims that no source supports.",
    ),
    "repetition": (
        Severity.MEDIUM,
        "Sections repeat the same passages.",
        "Rewrite repeated paragraphs so each section contributes new information.",
    ),
    "code_validity": (
        Severity.HIGH,
        "A code block does not parse.",
        "Fix the broken code block so it parses cleanly, or remove it.",
    ),
    "word_budget": (
        Severity.LOW,
        "The draft misses the requested word budget.",
        "Expand or trim flagged sections to reach the requested length.",
    ),
    "seo": (
        Severity.LOW,
        "The title, description or tags are not optimised for discovery.",
        "Keep the title between 30 and 65 characters, the description between 50 and 160, "
        "and include the primary topic keyword.",
    ),
    "hedging": (
        Severity.MEDIUM,
        "The draft hedges where it should state a position.",
        "Replace hedged wording with specific, verifiable statements.",
    ),
}


def _readability_score(flesch: float, target: tuple[float, float]) -> float:
    low, high = target
    if low <= flesch <= high:
        return 100.0
    distance = low - flesch if flesch < low else flesch - high
    return round(max(0.0, 100 - distance * 2.5), 2)


def _metrics(measurements: Measurements, rubric: Rubric) -> list[MetricResult]:
    weights = rubric.normalized_weights()
    ratio = measurements.repetition_ratio
    repetition_score = round(max(0.0, 100 * (1 - min(1.0, ratio / 0.15))), 2)
    hedge_score = round(max(0.0, 100 * (1 - min(1.0, measurements.hedge_density / 2.0))), 2)

    raw: list[tuple[str, float, str, float, str, float]] = [
        (
            "structure",
            measurements.structure,
            measurements.structure_detail,
            measurements.structure,
            "score",
            weights["structure"],
        ),
        (
            "readability",
            measurements.flesch,
            f"target {rubric.flesch_target[0]:.0f}-{rubric.flesch_target[1]:.0f}",
            _readability_score(measurements.flesch, rubric.flesch_target),
            "flesch",
            weights["readability"],
        ),
        (
            "citation_coverage",
            measurements.citation_coverage,
            f"{measurements.verified_claims}/{measurements.total_claims} claims verified",
            measurements.citation_coverage,
            "%",
            weights["citation_coverage"],
        ),
        (
            "repetition",
            round(ratio * 100, 2),
            "share of duplicated 12-word shingles",
            repetition_score,
            "%",
            weights["repetition"],
        ),
        (
            "code_validity",
            measurements.code_validity,
            measurements.code_detail,
            measurements.code_validity,
            "score",
            weights["code_validity"],
        ),
        (
            "word_budget",
            float(measurements.total_words),
            f"{measurements.total_words} of {measurements.target_words} words",
            measurements.word_budget,
            "words",
            weights["word_budget"],
        ),
        (
            "seo",
            measurements.seo,
            measurements.seo_detail,
            measurements.seo,
            "score",
            weights["seo"],
        ),
        (
            "hedging",
            measurements.hedge_density,
            f"{measurements.hedge_density:.2f} hedge words per 100",
            hedge_score,
            "per100",
            weights["hedging"],
        ),
    ]

    metrics: list[MetricResult] = []
    for key, value, detail, score, unit, weight in raw:
        gate = rubric.gate_for(key)
        threshold = gate.minimum if gate else 60.0
        metrics.append(
            MetricResult(
                key=key,
                label=_LABELS[key],
                value=round(value, 2),
                unit=unit,
                score=round(score, 2),
                weight=round(weight, 4),
                passed=score >= threshold,
                detail=detail,
            )
        )
    return metrics


def _section_issues(sections: Sequence[Section]) -> list[Issue]:
    issues: list[Issue] = []
    for section in sections:
        if not section.claims:
            continue
        verified = sum(1 for claim in section.claims if claim.verified)
        if verified / len(section.claims) >= 0.6:
            continue
        unsupported = [claim.id for claim in section.claims if not claim.verified]
        issues.append(
            Issue(
                code="section_grounding",
                message=(
                    f"Section '{section.plan.title}' has {verified}/{len(section.claims)} "
                    "verified claims."
                ),
                severity=Severity.HIGH,
                section_id=section.plan.id,
                directive=(
                    "Rewrite this section so every factual sentence cites a verified source, "
                    f"or remove the unsupported claims ({', '.join(unsupported[:4])})."
                ),
            )
        )
    return issues


def evaluate(
    *,
    outline: Outline,
    sections: Sequence[Section],
    claims: Sequence[Claim],
    brief: Brief,
    rubric: Rubric | None = None,
    revision_attempts: int = 0,
) -> QualityReport:
    """Evaluate a draft and return a scored report with gates and directives."""
    rubric = rubric or default_rubric()
    measurements = measure(outline=outline, sections=sections, claims=claims, brief=brief)
    metrics = _metrics(measurements, rubric)
    by_key = {metric.key: metric for metric in metrics}

    score = round(sum(metric.score * metric.weight for metric in metrics), 2)
    has_claims = bool(claims)
    failed: list[str] = []
    issues: list[Issue] = []

    for gate in rubric.gates:
        if not rubric.applies(gate, sources_required=brief.sources_required, has_claims=has_claims):
            continue
        actual = (
            score
            if gate.key == "score"
            else (by_key[gate.key].score if gate.key in by_key else 0.0)
        )
        if actual + 1e-9 >= gate.minimum:
            continue
        failed.append(gate.key)
        if gate.key == "score":
            continue
        severity, message, directive = _GUIDANCE.get(
            gate.key, (Severity.MEDIUM, f"{gate.key} gate failed.", "Improve this metric.")
        )
        issues.append(
            Issue(
                code=f"{gate.key}_gate",
                message=f"{message} ({actual:.1f} < {gate.minimum:.1f})",
                severity=severity,
                directive=directive,
            )
        )

    for metric in metrics:
        if metric.key in failed or metric.passed:
            continue
        if metric.key in _GUIDANCE:
            severity, message, directive = _GUIDANCE[metric.key]
            issues.append(
                Issue(
                    code=f"{metric.key}_below_target",
                    message=f"{message} ({metric.score:.1f})",
                    severity=severity,
                    directive=directive,
                )
            )

    issues.extend(_section_issues(sections))
    passed = not failed
    grade = grade_for(score)
    summary = f"Score {score:.1f} ({grade})"
    if failed:
        summary += f" - failed gates: {', '.join(failed)}"
    else:
        summary += " - all gates passed"
    if revision_attempts:
        summary += f" after {revision_attempts} revision attempt(s)"

    return QualityReport(
        score=score,
        grade=grade,
        passed=passed,
        metrics=metrics,
        failed_gates=failed,
        issues=issues,
        summary=summary,
    )


def failing_section_ids(report: QualityReport) -> list[str]:
    """Return the ids of sections flagged by the report."""
    seen: list[str] = []
    for issue in report.issues:
        if issue.section_id and issue.section_id not in seen:
            seen.append(issue.section_id)
    return seen


def global_directives(report: QualityReport) -> list[str]:
    """Return directives that apply to the whole document."""
    directives: list[str] = []
    for issue in report.issues:
        if issue.section_id is None and issue.directive and issue.directive not in directives:
            directives.append(issue.directive)
    return directives
