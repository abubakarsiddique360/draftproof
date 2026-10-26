"""Weighted quality rubric with explicit publish gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from draftproof.domain.errors import ConfigurationError

DEFAULT_WEIGHTS: dict[str, float] = {
    "structure": 0.18,
    "readability": 0.14,
    "citation_coverage": 0.18,
    "repetition": 0.10,
    "code_validity": 0.10,
    "word_budget": 0.12,
    "seo": 0.08,
    "hedging": 0.10,
}


@dataclass(frozen=True, slots=True)
class Gate:
    """A minimum score that must be met before publishing.

    ``condition`` restricts when the gate applies:

    * ``always``            - every run
    * ``sources_required``  - runs that asked for a sourced article
    * ``has_claims``        - runs where claims were extracted
    """

    key: str
    minimum: float
    condition: str = "always"


DEFAULT_GATES: tuple[Gate, ...] = (
    Gate("score", 75.0),
    Gate("structure", 70.0),
    Gate("word_budget", 60.0),
    Gate("repetition", 60.0),
    Gate("code_validity", 90.0),
    Gate("readability", 40.0),
    Gate("citation_coverage", 70.0, "sources_required"),
)


@dataclass(frozen=True, slots=True)
class Rubric:
    """Weights, gates and readability targets for evaluation."""

    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    gates: tuple[Gate, ...] = DEFAULT_GATES
    flesch_target: tuple[float, float] = (40.0, 65.0)

    def normalized_weights(self) -> dict[str, float]:
        total = sum(self.weights.values())
        if total <= 0:
            raise ConfigurationError("Rubric weights must sum to a positive value")
        return {key: value / total for key, value in self.weights.items()}

    def gate_for(self, key: str) -> Gate | None:
        return next((gate for gate in self.gates if gate.key == key), None)

    def applies(self, gate: Gate, *, sources_required: bool, has_claims: bool) -> bool:
        if gate.condition == "always":
            return True
        if gate.condition == "sources_required":
            return sources_required
        if gate.condition == "has_claims":
            return has_claims
        return True


def default_rubric() -> Rubric:
    """Return the built-in rubric."""
    return Rubric()


def load_rubric(path: Path | str) -> Rubric:
    """Load a rubric override from a YAML file."""
    file_path = Path(path)
    if not file_path.exists():
        raise ConfigurationError(f"Rubric file not found: {file_path}")
    try:
        payload = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid rubric YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError("Rubric file must contain a mapping")

    weights = dict(DEFAULT_WEIGHTS)
    overrides = payload.get("weights")
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if key not in DEFAULT_WEIGHTS:
                raise ConfigurationError(f"Unknown rubric metric in weights: {key}")
            weights[key] = float(value)

    gates = DEFAULT_GATES
    raw_gates = payload.get("gates")
    if isinstance(raw_gates, list) and raw_gates:
        parsed: list[Gate] = []
        for raw in raw_gates:
            if not isinstance(raw, dict) or "key" not in raw:
                raise ConfigurationError("Each gate needs a key and a minimum")
            parsed.append(
                Gate(
                    key=str(raw["key"]),
                    minimum=float(raw.get("minimum", 0)),
                    condition=str(raw.get("condition", "always")),
                )
            )
        gates = tuple(parsed)

    flesch = payload.get("flesch_target", (40, 65))
    if not isinstance(flesch, list | tuple) or len(flesch) != 2:
        raise ConfigurationError("flesch_target must be a two element range")
    return Rubric(weights=weights, gates=gates, flesch_target=(float(flesch[0]), float(flesch[1])))


def grade_for(score: float) -> str:
    """Map a numeric score onto a letter grade."""
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"
