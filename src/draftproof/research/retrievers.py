"""Source retrieval: a bundled offline corpus, Tavily, or nothing at all."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx

from draftproof.config import Settings, secret_value
from draftproof.domain.errors import ProviderError
from draftproof.research.text import terms

logger = logging.getLogger(__name__)

_CORPUS_PACKAGE = "draftproof.data"
_CORPUS_FILE = "corpus/seed.json"


@dataclass(frozen=True, slots=True)
class RetrievedDoc:
    """One raw search hit, before canonicalisation and verification."""

    title: str
    url: str
    snippet: str
    published_at: str | None = None
    source: str = "corpus"
    score: float = 0.0
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class Retriever(Protocol):
    """Search backend used by the research stage."""

    name: str

    def search(self, query: str, *, limit: int) -> list[RetrievedDoc]:
        """Return up to ``limit`` documents for a query."""
        ...


class NullRetriever:
    """Retriever that never returns evidence (closed-book runs)."""

    name = "none"

    def search(self, query: str, *, limit: int) -> list[RetrievedDoc]:
        return []


class LocalCorpusRetriever:
    """Offline retriever that ranks a bundled corpus by term overlap."""

    name = "local_corpus"

    def __init__(self, docs: Sequence[RetrievedDoc]) -> None:
        self._docs = list(docs)

    @property
    def documents(self) -> list[RetrievedDoc]:
        return list(self._docs)

    @classmethod
    def from_package(cls) -> LocalCorpusRetriever:
        return cls(load_corpus())

    def search(self, query: str, *, limit: int) -> list[RetrievedDoc]:
        query_terms = terms(query)
        if not query_terms:
            return []
        scored: list[RetrievedDoc] = []
        for doc in self._docs:
            haystack = f"{doc.title} {doc.title} {doc.snippet}"
            doc_terms = terms(haystack)
            shared = query_terms & doc_terms
            if not shared:
                continue
            coverage = len(shared) / min(len(query_terms), 8)
            title_bonus = 0.15 if query_terms & terms(doc.title) else 0.0
            scored.append(
                RetrievedDoc(
                    title=doc.title,
                    url=doc.url,
                    snippet=doc.snippet,
                    published_at=doc.published_at,
                    source=doc.source,
                    score=round(min(1.0, coverage + title_bonus), 4),
                    metadata=dict(doc.metadata),
                )
            )
        scored.sort(key=lambda item: (-item.score, item.title))
        return scored[: max(1, limit)]

    def corpus_index(self) -> dict[str, str]:
        """Map canonical URLs to their bundled text for offline verification."""
        return {doc.url: f"{doc.title}\n{doc.snippet}" for doc in self._docs}


class TavilyRetriever:
    """Web search through the Tavily search API."""

    name = "tavily"

    def __init__(
        self,
        api_key: str | None,
        *,
        endpoint: str = "https://api.tavily.com/search",
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout = timeout
        self._client = client

    def search(self, query: str, *, limit: int) -> list[RetrievedDoc]:
        payload: dict[str, object] = {
            "query": query,
            "max_results": max(1, min(limit, 10)),
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
            payload["api_key"] = self._api_key
        client = self._client or httpx.Client(timeout=self._timeout)
        owned = self._client is None
        try:
            try:
                response = client.post(self._endpoint, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                raise ProviderError(f"tavily: transport error: {exc}") from exc
        finally:
            if owned:
                client.close()
        if response.status_code >= 400:
            raise ProviderError(f"tavily: HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("tavily: response was not JSON") from exc
        results = data.get("results")
        if not isinstance(results, list):
            return []
        docs: list[RetrievedDoc] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            docs.append(
                RetrievedDoc(
                    title=str(item.get("title") or url)[:240],
                    url=url,
                    snippet=str(item.get("content") or item.get("snippet") or "")[:1200],
                    published_at=item.get("published_date") or None,
                    source="tavily",
                    score=float(item.get("score") or 0.0),
                )
            )
        return docs


def load_corpus() -> list[RetrievedDoc]:
    """Load the bundled offline corpus from package data."""
    text = ""
    try:
        text = resources.files(_CORPUS_PACKAGE).joinpath(_CORPUS_FILE).read_text(encoding="utf-8")
    except (OSError, ModuleNotFoundError):  # pragma: no cover - filesystem fallback
        path = Path(__file__).resolve().parent.parent / "data" / _CORPUS_FILE
        text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    docs: list[RetrievedDoc] = []
    for item in payload:
        docs.append(
            RetrievedDoc(
                title=str(item["title"]),
                url=str(item["url"]),
                snippet=str(item["snippet"]),
                published_at=item.get("published_at"),
                source=str(item.get("source") or "bundled-corpus"),
                metadata={"license": str(item.get("license") or "original")},
            )
        )
    return docs


def build_retriever(settings: Settings, *, client: httpx.Client | None = None) -> Retriever:
    """Construct the configured retriever."""
    if settings.retriever == "none":
        return NullRetriever()
    if settings.retriever == "tavily":
        return TavilyRetriever(
            secret_value(settings.tavily_api_key),
            endpoint=settings.search_endpoint or "https://api.tavily.com/search",
            timeout=settings.request_timeout,
            client=client,
        )
    return LocalCorpusRetriever.from_package()
