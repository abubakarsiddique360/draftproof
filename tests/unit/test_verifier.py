"""Claim verification strategies."""

from __future__ import annotations

from draftproof.domain.models import Claim, Evidence, EvidenceStatus, utc_now
from draftproof.research.fetchers import FetchResult
from draftproof.research.verifier import (
    CorpusVerifier,
    LiveVerifier,
    OffVerifier,
    build_verifier,
)

CORPUS_URL = "https://docs.example.com/rag/evaluating-retrieval-augmented-generation"
CORPUS_TEXT = (
    "Evaluating retrieval augmented generation systems depends on retrieval recall and "
    "answer faithfulness. Measure retrieval recall by checking whether the gold passage "
    "appears in the top results, then measure faithfulness for each answer sentence."
)


def _evidence(evidence_id: str = "ev1", **overrides: object) -> Evidence:
    payload = {
        "id": evidence_id,
        "title": "Evaluating retrieval-augmented generation systems",
        "url": CORPUS_URL,
        "domain": "docs.example.com",
        "snippet": "Retrieval recall and answer faithfulness are the two scores that matter.",
        "retrieved_at": utc_now(),
    }
    payload.update(overrides)
    return Evidence(**payload)  # type: ignore[arg-type]


def _claim(text: str, evidence_ids: list[str], section_id: str = "s1") -> Claim:
    return Claim(id="s1c1", section_id=section_id, text=text, evidence_ids=evidence_ids)


class _StubFetcher:
    def __init__(self, result: FetchResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        return self.result


def test_corpus_verifier_verifies_supported_claim() -> None:
    verifier = CorpusVerifier({CORPUS_URL: CORPUS_TEXT})
    claim = _claim(
        "Measuring retrieval recall and answer faithfulness is how retrieval augmented "
        "generation systems are evaluated.",
        ["ev1"],
    )
    result = verifier.verify([_evidence()], [claim])
    assert result.evidence[0].status is EvidenceStatus.VERIFIED
    assert result.claims[0].verified is True
    assert result.claims[0].confidence > 0.2
    assert result.coverage == 1.0


def test_corpus_verifier_marks_unknown_source_unreachable() -> None:
    verifier = CorpusVerifier({})
    result = verifier.verify([_evidence()], [_claim("Something specific about recall.", ["ev1"])])
    assert result.evidence[0].status is EvidenceStatus.UNREACHABLE
    assert result.claims[0].verified is False
    assert "unreachable" in (result.claims[0].note or "")


def test_claim_without_citation_is_flagged() -> None:
    verifier = CorpusVerifier({CORPUS_URL: CORPUS_TEXT})
    result = verifier.verify([_evidence()], [_claim("An uncited claim about the world.", [])])
    assert result.claims[0].verified is False
    assert result.claims[0].note == "no citation attached"


def test_weak_overlap_is_not_verified() -> None:
    verifier = CorpusVerifier({CORPUS_URL: CORPUS_TEXT}, min_overlap=0.9)
    claim = _claim("Retrieval recall matters a lot for evaluation.", ["ev1"])
    result = verifier.verify([_evidence()], [claim])
    assert result.claims[0].verified is False
    assert "weak textual support" in (result.claims[0].note or "")


def test_blocked_domain_is_not_verified() -> None:
    verifier = CorpusVerifier({CORPUS_URL: CORPUS_TEXT}, blocked_domains=["example.com"])
    result = verifier.verify([_evidence()], [_claim("Retrieval recall matters.", ["ev1"])])
    assert result.evidence[0].status is EvidenceStatus.BLOCKED


def test_live_verifier_uses_fetched_text() -> None:
    fetcher = _StubFetcher(
        FetchResult(
            url=CORPUS_URL,
            final_url=CORPUS_URL,
            status_code=200,
            ok=True,
            reason="ok",
            text=CORPUS_TEXT,
        )
    )
    verifier = LiveVerifier(fetcher)  # type: ignore[arg-type]
    claim = _claim("Retrieval recall and answer faithfulness are measured per release.", ["ev1"])
    result = verifier.verify([_evidence()], [claim])
    assert result.evidence[0].status is EvidenceStatus.VERIFIED
    assert result.claims[0].verified is True
    assert fetcher.calls == [CORPUS_URL]


def test_live_verifier_handles_blocked_and_missing() -> None:
    blocked = _StubFetcher(
        FetchResult(
            url=CORPUS_URL, final_url=CORPUS_URL, status_code=403, ok=False, reason="blocked"
        )
    )
    result = LiveVerifier(blocked).verify([_evidence()], [_claim("Recall matters.", ["ev1"])])
    assert result.evidence[0].status is EvidenceStatus.BLOCKED

    missing = _StubFetcher(
        FetchResult(
            url=CORPUS_URL,
            final_url=CORPUS_URL,
            status_code=None,
            ok=False,
            reason="transport_error",
        )
    )
    result = LiveVerifier(missing).verify([_evidence()], [_claim("Recall matters.", ["ev1"])])
    assert result.evidence[0].status is EvidenceStatus.UNREACHABLE


def test_live_verifier_respects_check_limit() -> None:
    fetcher = _StubFetcher(
        FetchResult(
            url=CORPUS_URL,
            final_url=CORPUS_URL,
            status_code=200,
            ok=True,
            reason="ok",
            text=CORPUS_TEXT,
        )
    )
    evidence = [_evidence(f"ev{index}") for index in range(1, 5)]
    verifier = LiveVerifier(fetcher, max_checks=2)  # type: ignore[arg-type]
    result = verifier.verify(evidence, [])
    assert len(fetcher.calls) == 2
    assert sum(1 for item in result.evidence if item.status is EvidenceStatus.UNCHECKED) == 2


def test_off_verifier_marks_claims_unverified() -> None:
    result = OffVerifier().verify([_evidence()], [_claim("A claim.", ["ev1"])])
    assert result.claims[0].verified is False
    assert result.claims[0].note == "verification disabled for this run"


def test_build_verifier_modes() -> None:
    assert build_verifier("off").name == "off"
    assert build_verifier("corpus", corpus_index={}).name == "corpus"
    assert build_verifier("live", fetcher=None).name == "live"
