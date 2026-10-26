"""Golden-case evaluation harness.

Every case is a brief plus explicit expectations. The suite runs the real
pipeline (with the deterministic mock provider by default) and produces a
pass/fail report, which makes prompt and rubric changes measurable.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from draftproof.domain.models import Brief, ContentType, Tone
from draftproof.pipeline.service import RunService


@dataclass(frozen=True, slots=True)
class Expectations:
    """Assertions applied to one run."""

    min_score: float = 70.0
    max_score: float = 100.0
    gates_passed: bool | None = True
    min_sections: int = 3
    min_verified_claims: int = 0
    max_cost_usd: float | None = None
    required_artifacts: tuple[str, ...] = ("markdown", "html", "manifest")
    max_duration_s: float | None = None


@dataclass(frozen=True, slots=True)
class EvalCase:
    """One golden case."""

    id: str
    brief: Brief
    expectations: Expectations


@dataclass(slots=True)
class EvalOutcome:
    """Result of running one case."""

    case_id: str
    passed: bool
    score: float
    grade: str
    sections: int
    verified_claims: int
    duration_s: float
    cost_usd: float
    failures: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvalReport:
    """Aggregate result of a suite."""

    outcomes: list[EvalOutcome]

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def passed(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def mean_score(self) -> float:
        if not self.outcomes:
            return 0.0
        return round(sum(outcome.score for outcome in self.outcomes) / self.total, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "mean_score": self.mean_score,
            "cases": [
                {
                    "case": outcome.case_id,
                    "passed": outcome.passed,
                    "score": outcome.score,
                    "grade": outcome.grade,
                    "sections": outcome.sections,
                    "verified_claims": outcome.verified_claims,
                    "duration_s": outcome.duration_s,
                    "cost_usd": outcome.cost_usd,
                    "failures": outcome.failures,
                }
                for outcome in self.outcomes
            ],
        }


def load_cases(directory: Path | str) -> list[EvalCase]:
    """Load every ``*.json`` case from a directory."""
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"Case directory not found: {root}")
    cases: list[EvalCase] = []
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        expectations = payload.get("expect", {})
        brief = Brief(
            topic=payload["topic"],
            audience=payload.get("audience", "software engineers"),
            content_type=ContentType(payload.get("content_type", "explainer")),
            tone=Tone(payload.get("tone", "practical")),
            target_words=int(payload.get("target_words", 1200)),
            key_points=list(payload.get("key_points", [])),
            sources_required=bool(payload.get("sources_required", True)),
            seed=int(payload.get("seed", 7)),
        )
        cases.append(
            EvalCase(
                id=str(payload.get("id") or path.stem),
                brief=brief,
                expectations=Expectations(
                    min_score=float(expectations.get("min_score", 70.0)),
                    max_score=float(expectations.get("max_score", 100.0)),
                    gates_passed=expectations.get("gates_passed", True),
                    min_sections=int(expectations.get("min_sections", 3)),
                    min_verified_claims=int(expectations.get("min_verified_claims", 0)),
                    max_cost_usd=expectations.get("max_cost_usd"),
                    required_artifacts=tuple(
                        expectations.get("required_artifacts", ("markdown", "html", "manifest"))
                    ),
                    max_duration_s=expectations.get("max_duration_s"),
                ),
            )
        )
    if not cases:
        raise FileNotFoundError(f"No cases found in {root}")
    return cases


def run_case(service: RunService, case: EvalCase) -> EvalOutcome:
    """Execute one case and check its expectations."""
    started = time.perf_counter()
    run = service.create_run(case.brief)
    final = service.execute(run.id)
    duration = round(time.perf_counter() - started, 2)
    failures: list[str] = []
    quality = final.quality

    if quality is None:
        failures.append("no quality report")
        score = 0.0
        grade = "F"
    else:
        score = quality.score
        grade = quality.grade
        if score < case.expectations.min_score:
            failures.append(f"score {score:.1f} < {case.expectations.min_score:.1f}")
        if score > case.expectations.max_score:
            failures.append(f"score {score:.1f} > {case.expectations.max_score:.1f}")
        if (
            case.expectations.gates_passed is not None
            and quality.passed != case.expectations.gates_passed
        ):
            failures.append(
                "gates "
                + (
                    "failed: " + ", ".join(quality.failed_gates)
                    if quality.failed_gates
                    else "passed"
                )
            )

    sections = len(final.sections)
    if sections < case.expectations.min_sections:
        failures.append(f"sections {sections} < {case.expectations.min_sections}")

    verified = sum(1 for section in final.sections for claim in section.claims if claim.verified)
    if verified < case.expectations.min_verified_claims:
        failures.append(f"verified claims {verified} < {case.expectations.min_verified_claims}")

    if (
        case.expectations.max_cost_usd is not None
        and final.usage.cost_usd > case.expectations.max_cost_usd
    ):
        failures.append(f"cost ${final.usage.cost_usd:.4f} > ${case.expectations.max_cost_usd:.4f}")

    available = {artifact.kind for artifact in final.artifacts}
    missing = [kind for kind in case.expectations.required_artifacts if kind not in available]
    if missing:
        failures.append("missing artifacts: " + ", ".join(missing))

    if case.expectations.max_duration_s is not None and duration > case.expectations.max_duration_s:
        failures.append(f"duration {duration:.1f}s > {case.expectations.max_duration_s:.1f}s")

    if final.error:
        failures.append(f"run error: {final.error}")

    return EvalOutcome(
        case_id=case.id,
        passed=not failures,
        score=score,
        grade=grade,
        sections=sections,
        verified_claims=verified,
        duration_s=duration,
        cost_usd=round(final.usage.cost_usd, 6),
        failures=failures,
    )


def run_suite(service: RunService, cases: list[EvalCase]) -> EvalReport:
    """Run every case and collect the outcomes."""
    return EvalReport(outcomes=[run_case(service, case) for case in cases])
