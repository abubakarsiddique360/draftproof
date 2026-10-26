"""Deterministic content measurements.

Every metric here is computed from the text itself. No model is asked to grade
its own output, which makes scores reproducible and diffable between runs.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from draftproof.domain.models import Brief, Claim, Outline, Section
from draftproof.research.text import sentences, shingles, syllables, terms, word_count

_CODE_BLOCK = re.compile(r"```(?P<lang>[A-Za-z0-9_+-]*)\n(?P<body>.*?)```", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)
_PLACEHOLDERS = ("[[IMAGE", "TODO", "TBD", "lorem ipsum", "{{", "}}")
_HEDGES = (
    "might",
    "may",
    "could",
    "possibly",
    "perhaps",
    "arguably",
    "seems",
    "somewhat",
    "probably",
    "presumably",
    "tends to",
    "roughly",
)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\S", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Measurements:
    """All raw numbers the rubric needs."""

    total_words: int
    target_words: int
    flesch: float
    structure: float
    structure_detail: str
    citation_coverage: float
    verified_claims: int
    total_claims: int
    repetition_ratio: float
    code_validity: float
    code_detail: str
    word_budget: float
    seo: float
    seo_detail: str
    hedge_density: float


def prose_only(markdown: str) -> str:
    """Remove fenced code blocks and headings from Markdown."""
    without_code = _CODE_BLOCK.sub(" ", markdown)
    without_headings = re.sub(r"^#{1,6}.*$", " ", without_code, flags=re.MULTILINE)
    return " ".join(without_headings.split())


def flesch_reading_ease(text: str) -> float:
    """Compute the Flesch reading ease score for prose."""
    cleaned = prose_only(text)
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", cleaned)
    if not words:
        return 0.0
    sentence_count = max(1, len(sentences(cleaned)))
    syllable_count = sum(syllables(word) for word in words)
    score = 206.835 - 1.015 * (len(words) / sentence_count) - 84.6 * (syllable_count / len(words))
    return round(max(0.0, min(120.0, score)), 2)


def _structure(sections: Sequence[Section]) -> tuple[float, str]:
    if not sections:
        return 0.0, "no sections were drafted"
    total = len(sections)
    headings = sum(1 for section in sections if section.markdown.lstrip().startswith("## "))
    substantial = sum(1 for section in sections if word_count(prose_only(section.markdown)) >= 60)
    rich = sum(
        1
        for section in sections
        if _LIST_ITEM.search(section.markdown) or "```" in section.markdown
    )
    no_placeholders = all(
        marker.lower() not in section.markdown.lower()
        for section in sections
        for marker in _PLACEHOLDERS
    )
    fences_balanced = all(section.markdown.count("```") % 2 == 0 for section in sections)
    shallow = all(
        not re.search(r"^#{4,6}\s", section.markdown, re.MULTILINE) for section in sections
    )
    long_enough = total >= 3
    framed = sum(1 for section in (sections[0], sections[-1]) if section.markdown.strip())

    score = 0.0
    score += 20 * headings / total
    score += 15 * substantial / total
    score += 15 * rich / total
    score += 10 if no_placeholders else 0
    score += 15 if fences_balanced else 0
    score += 10 if shallow else 0
    score += 5 if long_enough else 0
    score += 10 * framed / 2

    detail = (
        f"{headings}/{total} sections headed, {substantial}/{total} substantial, "
        f"{rich}/{total} with lists or code"
    )
    return round(score, 2), detail


def _code_validity(sections: Sequence[Section]) -> tuple[float, str]:
    blocks: list[tuple[str, str]] = []
    for section in sections:
        for match in _CODE_BLOCK.finditer(section.markdown):
            blocks.append((match.group("lang").lower(), match.group("body")))
    if not blocks:
        return 100.0, "no code blocks to validate"

    valid = 0
    failures: list[str] = []
    for index, (lang, body) in enumerate(blocks, start=1):
        try:
            if lang in {"python", "py"}:
                ast.parse(body)
            elif lang in {"json"}:
                json.loads(body)
            elif lang in {"javascript", "js", "ts", "typescript"}:
                _assert_balanced(body)
            elif lang in {"bash", "sh", "shell", "text", ""}:
                pass
            else:
                _assert_balanced(body)
        except (SyntaxError, ValueError) as exc:
            failures.append(f"block {index}: {exc}")
            continue
        valid += 1
    score = round(100 * valid / len(blocks), 2)
    detail = f"{valid}/{len(blocks)} code blocks parsed"
    if failures:
        detail += " (" + "; ".join(failures[:2]) + ")"
    return score, detail


def _assert_balanced(source: str) -> None:
    pairs = {"{": "}", "(": ")", "[": "]"}
    stack: list[str] = []
    for char in source:
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values() and (not stack or stack.pop() != char):
            raise ValueError("unbalanced brackets")
    if stack:
        raise ValueError("unbalanced brackets")


def _repetition(sections: Sequence[Section]) -> float:
    """Share of long passages and sentences that repeat across sections."""
    if len(sections) < 2:
        return 0.0

    shingle_sets: list[set[str]] = []
    sentence_sets: list[set[str]] = []
    for section in sections:
        prose = prose_only(section.markdown)
        shingle_sets.append(shingles(prose, size=12))
        sentence_sets.append(
            {
                " ".join(sentence.lower().split())
                for sentence in sentences(prose)
                if len(sentence.split()) >= 6
            }
        )

    def _duplicate_ratio(groups: list[set[str]]) -> float:
        total = sum(len(group) for group in groups)
        if not total:
            return 0.0
        seen: set[str] = set()
        duplicated: set[str] = set()
        for group in groups:
            duplicated |= seen & group
            seen |= group
        return len(duplicated) / total

    return round(max(_duplicate_ratio(shingle_sets), _duplicate_ratio(sentence_sets)), 4)


def _seo(outline: Outline, brief: Brief) -> tuple[float, str]:
    score = 0.0
    title_len = len(outline.title)
    if 30 <= title_len <= 65:
        score += 30
    elif 20 <= title_len <= 80:
        score += 18
    meta_len = len(outline.meta_description)
    if 50 <= meta_len <= 160:
        score += 30
    elif 30 <= meta_len <= 200:
        score += 18
    if len(outline.tags) >= 3:
        score += 10
    keywords = list(terms(brief.topic))[:4]
    haystack = (
        outline.title + " " + " ".join(section.title for section in outline.sections)
    ).lower()
    if keywords and any(keyword in haystack for keyword in keywords):
        score += 30
    detail = f"title {title_len} chars, description {meta_len} chars, {len(outline.tags)} tags"
    return round(min(100.0, score), 2), detail


def _hedge_density(sections: Sequence[Section]) -> float:
    prose = " ".join(prose_only(section.markdown) for section in sections).lower()
    words = max(1, word_count(prose))
    hits = sum(prose.count(hedge) for hedge in _HEDGES)
    return round(hits * 100 / words, 3)


def measure(
    *,
    outline: Outline,
    sections: Sequence[Section],
    claims: Sequence[Claim],
    brief: Brief,
) -> Measurements:
    """Compute every measurement for a drafted document."""
    body = "\n\n".join(section.markdown for section in sections)
    total_words = word_count(prose_only(body))
    target = max(1, brief.target_words)
    budget_delta = abs(total_words - target) / target

    structure, structure_detail = _structure(sections)
    code_validity, code_detail = _code_validity(sections)
    seo, seo_detail = _seo(outline, brief)

    total_claims = len(claims)
    verified = sum(1 for claim in claims if claim.verified)
    if total_claims:
        citation_coverage = round(100 * verified / total_claims, 2)
    else:
        citation_coverage = 0.0 if brief.sources_required else 100.0

    return Measurements(
        total_words=total_words,
        target_words=target,
        flesch=flesch_reading_ease(body),
        structure=structure,
        structure_detail=structure_detail,
        citation_coverage=citation_coverage,
        verified_claims=verified,
        total_claims=total_claims,
        repetition_ratio=_repetition(sections),
        code_validity=code_validity,
        code_detail=code_detail,
        word_budget=round(max(0.0, 100 * (1 - min(1.0, budget_delta / 0.35))), 2),
        seo=seo,
        seo_detail=seo_detail,
        hedge_density=_hedge_density(sections),
    )
