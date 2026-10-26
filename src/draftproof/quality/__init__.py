"""Quality package: deterministic metrics, rubric gates and evaluation."""

from __future__ import annotations

from draftproof.quality.evaluator import evaluate, failing_section_ids, global_directives
from draftproof.quality.metrics import Measurements, measure
from draftproof.quality.rubric import (
    DEFAULT_GATES,
    DEFAULT_WEIGHTS,
    Gate,
    Rubric,
    default_rubric,
    grade_for,
    load_rubric,
)

__all__ = [
    "DEFAULT_GATES",
    "DEFAULT_WEIGHTS",
    "Gate",
    "Measurements",
    "Rubric",
    "default_rubric",
    "evaluate",
    "failing_section_ids",
    "global_directives",
    "grade_for",
    "load_rubric",
    "measure",
]
