"""Research package: retrieval, URL safety, fetching and verification."""

from __future__ import annotations

from draftproof.research.fetchers import FetchResult, SafeFetcher
from draftproof.research.guard import sanitize_untrusted, wrap_untrusted
from draftproof.research.retrievers import (
    LocalCorpusRetriever,
    NullRetriever,
    RetrievedDoc,
    Retriever,
    TavilyRetriever,
    build_retriever,
    load_corpus,
)
from draftproof.research.urls import canonicalize, domain_of, validate_public_url
from draftproof.research.verifier import (
    CorpusVerifier,
    LiveVerifier,
    OffVerifier,
    VerificationResult,
    Verifier,
    build_verifier,
)

__all__ = [
    "CorpusVerifier",
    "FetchResult",
    "LiveVerifier",
    "LocalCorpusRetriever",
    "NullRetriever",
    "OffVerifier",
    "RetrievedDoc",
    "Retriever",
    "SafeFetcher",
    "TavilyRetriever",
    "VerificationResult",
    "Verifier",
    "build_retriever",
    "build_verifier",
    "canonicalize",
    "domain_of",
    "load_corpus",
    "sanitize_untrusted",
    "validate_public_url",
    "wrap_untrusted",
]
