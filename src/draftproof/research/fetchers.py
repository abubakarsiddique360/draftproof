"""SSRF-safe HTTP fetching with byte and redirect limits."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from draftproof.domain.errors import UnsafeURLError
from draftproof.research.urls import default_resolver, validate_public_url

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "DraftProof/0.1 (link verification; +https://github.com/abubakarsiddique360/draftproof)"
)
_TEXT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml",
    "application/ld+json",
)


@dataclass(frozen=True, slots=True)
class FetchResult:
    """The outcome of fetching one URL."""

    url: str
    final_url: str
    status_code: int | None
    ok: bool
    reason: str
    content_type: str = ""
    text: str = ""
    truncated: bool = False


class SafeFetcher:
    """Fetch public URLs while enforcing the outbound safety policy."""

    def __init__(
        self,
        *,
        timeout: float = 8.0,
        max_bytes: int = 200_000,
        max_redirects: int = 3,
        resolver: Callable[[str], Sequence[str]] = default_resolver,
        client: httpx.Client | None = None,
        allow_private: bool = False,
    ) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._max_redirects = max(0, max_redirects)
        self._resolver = resolver
        self._allow_private = allow_private
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.5",
            },
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> SafeFetcher:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch(self, url: str) -> FetchResult:
        current = url
        for _hop in range(self._max_redirects + 1):
            try:
                parsed = validate_public_url(
                    current, resolver=self._resolver, allow_private=self._allow_private
                )
            except UnsafeURLError as exc:
                return FetchResult(
                    url=url, final_url=current, status_code=None, ok=False, reason=str(exc)
                )

            try:
                with self._client.stream("GET", parsed.url) as response:
                    status = response.status_code
                    location = response.headers.get("location")
                    if status in {301, 302, 303, 307, 308} and location:
                        current = urljoin(current, location)
                        continue
                    content_type = response.headers.get("content-type", "")
                    if status in {401, 403, 405, 429}:
                        return FetchResult(
                            url=url,
                            final_url=current,
                            status_code=status,
                            ok=False,
                            reason="blocked",
                            content_type=content_type,
                        )
                    if status >= 400:
                        return FetchResult(
                            url=url,
                            final_url=current,
                            status_code=status,
                            ok=False,
                            reason=f"http_{status}",
                            content_type=content_type,
                        )
                    if not any(token in content_type.lower() for token in _TEXT_TYPES):
                        return FetchResult(
                            url=url,
                            final_url=current,
                            status_code=status,
                            ok=False,
                            reason="non_text",
                            content_type=content_type,
                        )
                    body, truncated = self._read_body(response)
            except httpx.HTTPError as exc:
                logger.debug("Fetch failed for %s: %s", current, exc)
                return FetchResult(
                    url=url,
                    final_url=current,
                    status_code=None,
                    ok=False,
                    reason="transport_error",
                )

            encoding = response.encoding or "utf-8"
            return FetchResult(
                url=url,
                final_url=current,
                status_code=status,
                ok=True,
                reason="ok",
                content_type=content_type,
                text=body.decode(encoding, errors="replace"),
                truncated=truncated,
            )

        return FetchResult(
            url=url,
            final_url=current,
            status_code=None,
            ok=False,
            reason="too_many_redirects",
        )

    def _read_body(self, response: httpx.Response) -> tuple[bytes, bool]:
        chunks: list[bytes] = []
        total = 0
        truncated = False
        for chunk in response.iter_bytes():
            chunks.append(chunk)
            total += len(chunk)
            if total >= self._max_bytes:
                truncated = True
                break
        return b"".join(chunks)[: self._max_bytes], truncated


def content_hash(text: str) -> str:
    """Stable hash of fetched evidence text."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:32]


def as_dict(result: FetchResult) -> dict[str, Any]:
    return {
        "url": result.url,
        "final_url": result.final_url,
        "status_code": result.status_code,
        "ok": result.ok,
        "reason": result.reason,
        "truncated": result.truncated,
    }
