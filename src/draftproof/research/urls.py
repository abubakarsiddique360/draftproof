"""URL canonicalisation and outbound request safety policy.

The verifier fetches URLs that came from search results, which makes this
module the project's SSRF boundary: only ``http``/``https`` URLs that resolve
exclusively to public addresses are allowed.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from draftproof.domain.errors import UnsafeURLError

_TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "msclkid",
        "ref",
        "ref_src",
        "source",
        "spm",
        "yclid",
    }
)
_BLOCKED_HOSTS = frozenset({"localhost", "localhost.localdomain", "metadata.google.internal"})
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".onion")
_DEFAULT_PORTS = {"http": 80, "https": 443}
_IP_LITERAL = re.compile(r"^[0-9a-fA-F:.]+$")


@dataclass(frozen=True, slots=True)
class ParsedURL:
    """Canonical form of an outbound URL."""

    url: str
    scheme: str
    host: str
    port: int
    path: str


def canonicalize(url: str) -> str:
    """Normalize a URL so duplicates collapse to one evidence entry."""
    raw = url.strip()
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if not scheme or not host:
        return raw
    port = parts.port
    if port is not None and _DEFAULT_PORTS.get(scheme) == port:
        port = None
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
    ]
    query_pairs.sort()
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((scheme, netloc, path, urlencode(query_pairs), ""))


def domain_of(url: str) -> str:
    """Return the lowercase registrable host of a URL."""
    host = urlsplit(url).hostname or ""
    return host.lower().removeprefix("www.")


def scheme_of(url: str) -> str:
    return urlsplit(url).scheme.lower()


def is_private_ip(address: str) -> bool:
    """Return ``True`` for addresses that must never be fetched."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    return not parsed.is_global or any(
        (
            parsed.is_private,
            parsed.is_loopback,
            parsed.is_link_local,
            parsed.is_multicast,
            parsed.is_reserved,
            parsed.is_unspecified,
        )
    )


def default_resolver(host: str) -> Sequence[str]:
    """Resolve a host to every address family result."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


def validate_public_url(
    url: str,
    *,
    resolver: object = default_resolver,
    allow_private: bool = False,
) -> ParsedURL:
    """Validate an outbound URL against the SSRF policy."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UnsafeURLError(f"Blocked URL scheme: {scheme or 'missing'}")
    if parts.username or parts.password:
        raise UnsafeURLError("Blocked URL with embedded credentials")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeURLError("Blocked URL without a host")
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeURLError(f"Blocked internal host: {host}")
    port = parts.port or _DEFAULT_PORTS[scheme]
    if port <= 0:
        raise UnsafeURLError("Blocked URL with an invalid port")
    if allow_private:
        return ParsedURL(
            url=canonicalize(url), scheme=scheme, host=host, port=port, path=parts.path
        )

    addresses: list[str] = []
    if _IP_LITERAL.match(host):
        addresses = [host]
    else:
        try:
            addresses = list(resolver(host))  # type: ignore[operator]
        except (OSError, socket.gaierror) as exc:
            raise UnsafeURLError(f"Could not resolve host: {host}") from exc
    if not addresses:
        raise UnsafeURLError(f"Host did not resolve: {host}")
    if any(is_private_ip(address) for address in addresses):
        raise UnsafeURLError(f"Blocked non-public address for host: {host}")
    return ParsedURL(url=canonicalize(url), scheme=scheme, host=host, port=port, path=parts.path)


def host_matches(host: str, candidates: Sequence[str]) -> bool:
    """Return whether ``host`` equals or is a subdomain of any candidate."""
    lowered = host.lower()
    for candidate in candidates:
        entry = candidate.strip().lower().lstrip(".")
        if not entry:
            continue
        if lowered == entry or lowered.endswith("." + entry):
            return True
    return False
