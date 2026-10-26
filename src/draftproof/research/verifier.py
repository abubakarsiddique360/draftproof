"""Claim-to-evidence verification.

Verification is deterministic: it does not ask a model whether a claim is true.
It checks that a cited source is reachable (or present in the trusted corpus),
extracts its text, and measures whether the claim's content terms are actually
supported by that text.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from draftproof.domain.models import Claim, Evidence, EvidenceStatus
from draftproof.research.fetchers import SafeFetcher, content_hash
from draftproof.research.guard import sanitize_untrusted
from draftproof.research.text import support_score
from draftproof.research.urls import canonicalize, host_matches

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VerificationResult:
    """Evidence and claims after verification."""

    evidence: list[Evidence]
    claims: list[Claim]
    checked: int = 0

    @property
    def total_claims(self) -> int:
        return len(self.claims)

    @property
    def verified_claims(self) -> int:
        return sum(1 for claim in self.claims if claim.verified)

    @property
    def coverage(self) -> float:
        if not self.claims:
            return 1.0
        return round(self.verified_claims / len(self.claims), 4)


@runtime_checkable
class Verifier(Protocol):
    """Strategy that annotates evidence with a status and scores claims."""

    name: str

    def verify(self, evidence: Sequence[Evidence], claims: Sequence[Claim]) -> VerificationResult:
        """Verify claims against the supplied evidence."""
        ...


def _score_claims(
    evidence: Sequence[Evidence],
    claims: Sequence[Claim],
    texts: Mapping[str, str],
    *,
    min_overlap: float,
) -> list[Claim]:
    by_id = {item.id: item for item in evidence}
    scored: list[Claim] = []
    for claim in claims:
        candidates = [evidence_id for evidence_id in claim.evidence_ids if evidence_id in by_id]
        best_id: str | None = None
        best = 0.0
        for evidence_id in candidates:
            score = support_score(claim.text, texts.get(evidence_id, ""))
            if score > best:
                best, best_id = score, evidence_id

        if not candidates:
            note = "no citation attached"
            verified = False
        elif best_id is None:
            note = "cited evidence was not retrieved"
            verified = False
        elif by_id[best_id].status is not EvidenceStatus.VERIFIED:
            note = f"cited source is {by_id[best_id].status.value}"
            verified = False
        elif best < min_overlap:
            note = f"weak textual support ({best:.2f} < {min_overlap:.2f})"
            verified = False
        else:
            note = None
            verified = True

        scored.append(
            claim.model_copy(
                update={
                    "verified": verified,
                    "confidence": round(best, 4),
                    "note": note,
                }
            )
        )
    return scored


def _merge_overlap(evidence: Sequence[Evidence], claims: Sequence[Claim]) -> list[Evidence]:
    maxima: dict[str, float] = {}
    for claim in claims:
        for evidence_id in claim.evidence_ids:
            maxima[evidence_id] = max(maxima.get(evidence_id, 0.0), claim.confidence)
    return [
        item.model_copy(update={"overlap": round(maxima.get(item.id, item.overlap), 4)})
        for item in evidence
    ]


class LiveVerifier:
    """Fetch every cited URL and verify claims against the fetched text."""

    name = "live"

    def __init__(
        self,
        fetcher: SafeFetcher,
        *,
        min_overlap: float = 0.18,
        max_checks: int = 12,
        blocked_domains: Sequence[str] = (),
        allowed_domains: Sequence[str] = (),
        max_text_chars: int = 4000,
    ) -> None:
        self._fetcher = fetcher
        self._min_overlap = min_overlap
        self._max_checks = max(1, max_checks)
        self._blocked = tuple(blocked_domains)
        self._allowed = tuple(allowed_domains)
        self._max_text_chars = max_text_chars

    def verify(self, evidence: Sequence[Evidence], claims: Sequence[Claim]) -> VerificationResult:
        cited = {evidence_id for claim in claims for evidence_id in claim.evidence_ids}
        ordered = sorted(evidence, key=lambda item: (item.id not in cited, item.id))
        texts: dict[str, str] = {}
        updated: dict[str, Evidence] = {}
        checked = 0

        for index, item in enumerate(ordered):
            if index >= self._max_checks:
                updated[item.id] = item.model_copy(
                    update={"status": EvidenceStatus.UNCHECKED, "http_status": None}
                )
                texts[item.id] = f"{item.title}\n{item.snippet}"
                continue
            if self._blocked and host_matches(item.domain, self._blocked):
                updated[item.id] = item.model_copy(
                    update={"status": EvidenceStatus.BLOCKED, "http_status": None}
                )
                texts[item.id] = f"{item.title}\n{item.snippet}"
                continue
            if self._allowed and not host_matches(item.domain, self._allowed):
                updated[item.id] = item.model_copy(
                    update={"status": EvidenceStatus.BLOCKED, "http_status": None}
                )
                texts[item.id] = f"{item.title}\n{item.snippet}"
                continue

            result = self._fetcher.fetch(item.url)
            checked += 1
            if result.ok and result.text:
                body, suspicious = sanitize_untrusted(result.text, max_chars=self._max_text_chars)
                updated[item.id] = item.model_copy(
                    update={
                        "status": EvidenceStatus.VERIFIED,
                        "http_status": result.status_code,
                        "content_hash": content_hash(body),
                        "injection_suspected": item.injection_suspected or suspicious,
                    }
                )
                texts[item.id] = f"{item.title}\n{item.snippet}\n{body}"
            elif result.reason == "blocked":
                updated[item.id] = item.model_copy(
                    update={"status": EvidenceStatus.BLOCKED, "http_status": result.status_code}
                )
                texts[item.id] = f"{item.title}\n{item.snippet}"
            else:
                updated[item.id] = item.model_copy(
                    update={"status": EvidenceStatus.UNREACHABLE, "http_status": result.status_code}
                )
                texts[item.id] = f"{item.title}\n{item.snippet}"

        verified_evidence = [updated[item.id] for item in evidence]
        scored_claims = _score_claims(
            verified_evidence, claims, texts, min_overlap=self._min_overlap
        )
        return VerificationResult(
            evidence=_merge_overlap(verified_evidence, scored_claims),
            claims=scored_claims,
            checked=checked,
        )


class CorpusVerifier:
    """Verify against a trusted local index instead of the network."""

    name = "corpus"

    def __init__(
        self,
        index: Mapping[str, str],
        *,
        min_overlap: float = 0.18,
        blocked_domains: Sequence[str] = (),
    ) -> None:
        self._index = {canonicalize(url): text for url, text in index.items()}
        self._min_overlap = min_overlap
        self._blocked = tuple(blocked_domains)

    def verify(self, evidence: Sequence[Evidence], claims: Sequence[Claim]) -> VerificationResult:
        texts: dict[str, str] = {}
        verified: list[Evidence] = []
        for item in evidence:
            if self._blocked and host_matches(item.domain, self._blocked):
                verified.append(item.model_copy(update={"status": EvidenceStatus.BLOCKED}))
                texts[item.id] = f"{item.title}\n{item.snippet}"
                continue
            text = self._index.get(canonicalize(item.url))
            if text is None:
                verified.append(item.model_copy(update={"status": EvidenceStatus.UNREACHABLE}))
                texts[item.id] = f"{item.title}\n{item.snippet}"
                continue
            verified.append(
                item.model_copy(
                    update={
                        "status": EvidenceStatus.VERIFIED,
                        "content_hash": content_hash(text),
                    }
                )
            )
            texts[item.id] = f"{item.title}\n{item.snippet}\n{text}"

        scored_claims = _score_claims(verified, claims, texts, min_overlap=self._min_overlap)
        return VerificationResult(
            evidence=_merge_overlap(verified, scored_claims),
            claims=scored_claims,
            checked=len(verified),
        )


class OffVerifier:
    """Explicit opt-out: claims stay unverified and the report says so."""

    name = "off"

    def verify(self, evidence: Sequence[Evidence], claims: Sequence[Claim]) -> VerificationResult:
        texts = {item.id: f"{item.title}\n{item.snippet}" for item in evidence}
        stamped = [
            claim.model_copy(
                update={
                    "verified": False,
                    "confidence": 0.0,
                    "note": "verification disabled for this run",
                }
            )
            for claim in claims
        ]
        del texts
        return VerificationResult(evidence=list(evidence), claims=stamped, checked=0)


def build_verifier(
    mode: str,
    *,
    fetcher: SafeFetcher | None = None,
    corpus_index: Mapping[str, str] | None = None,
    min_overlap: float = 0.18,
    blocked_domains: Sequence[str] = (),
    allowed_domains: Sequence[str] = (),
) -> Verifier:
    """Construct a verifier for the requested mode."""
    if mode == "live":
        if fetcher is None:
            fetcher = SafeFetcher()
        return LiveVerifier(
            fetcher,
            min_overlap=min_overlap,
            blocked_domains=blocked_domains,
            allowed_domains=allowed_domains,
        )
    if mode == "corpus":
        return CorpusVerifier(
            corpus_index or {}, min_overlap=min_overlap, blocked_domains=blocked_domains
        )
    return OffVerifier()
