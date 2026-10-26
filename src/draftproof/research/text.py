"""Small, dependency-free text utilities used by research and quality."""

from __future__ import annotations

import re

STOPWORDS: frozenset[str] = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "also",
        "am",
        "an",
        "and",
        "any",
        "are",
        "aren't",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "cannot",
        "could",
        "couldn't",
        "did",
        "didn't",
        "do",
        "does",
        "doesn't",
        "doing",
        "don't",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "hadn't",
        "has",
        "hasn't",
        "have",
        "haven't",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "isn't",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "mustn't",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "ought",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "shan't",
        "she",
        "should",
        "shouldn't",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "wasn't",
        "we",
        "were",
        "weren't",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "with",
        "won't",
        "would",
        "wouldn't",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "via",
        "get",
        "got",
        "make",
        "makes",
        "made",
        "use",
        "uses",
        "used",
        "using",
        "one",
        "two",
        "three",
    ]
)

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_VOWELS = re.compile(r"[aeiouy]+")


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def tokenize(text: str) -> list[str]:
    """Return content-bearing lowercase tokens."""
    return [
        token.lower().strip("'-")
        for token in _TOKEN.findall(text)
        if token.lower() not in STOPWORDS
    ]


def terms(text: str) -> set[str]:
    """Return the unique content terms of ``text``."""
    return set(tokenize(text))


def sentences(text: str) -> list[str]:
    """Split prose into sentences without external dependencies."""
    return [part.strip() for part in _SENTENCE.split(text) if part.strip()]


def word_count(text: str) -> int:
    """Count word-like tokens in ``text``."""
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text))


def syllables(word: str) -> int:
    """Approximate syllable count for readability scoring."""
    cleaned = re.sub(r"[^a-z]", "", word.lower())
    if not cleaned:
        return 0
    groups = _VOWELS.findall(cleaned)
    count = len(groups)
    if cleaned.endswith("e") and count > 1 and not cleaned.endswith(("le", "ee")):
        count -= 1
    return max(1, count)


def jaccard(left: str, right: str) -> float:
    """Jaccard similarity between the content terms of two strings."""
    a, b = terms(left), terms(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def support_score(claim: str, evidence_text: str) -> float:
    """How much of a claim is covered by a piece of evidence.

    The denominator is capped so long claims are not unfairly penalised, and
    rarer, longer terms carry slightly more weight than short ones.
    """
    claim_terms = terms(claim)
    evidence_terms = terms(evidence_text)
    if not claim_terms or not evidence_terms:
        return 0.0
    shared = claim_terms & evidence_terms
    if not shared:
        return 0.0
    weighted = sum(len(term) for term in shared)
    total = sum(len(term) for term in sorted(claim_terms)[:12])
    return min(1.0, weighted / total) if total else 0.0


def shingles(text: str, size: int = 12) -> set[str]:
    """Return the set of word n-grams for duplicate detection."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    if len(words) < size:
        return set()
    return {" ".join(words[index : index + size]) for index in range(len(words) - size + 1)}


def truncate(text: str, limit: int, *, suffix: str = "...") -> str:
    """Truncate text on a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - len(suffix))]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + suffix
