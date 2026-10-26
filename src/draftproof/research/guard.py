"""Prompt-injection defence for untrusted retrieved text."""

from __future__ import annotations

import html
import re

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.IGNORECASE),
    re.compile(r"forget\s+(everything|your\s+instructions)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an|the)\b", re.IGNORECASE),
    re.compile(r"(reveal|print|repeat)\s+(your\s+)?(system\s+)?prompt", re.IGNORECASE),
    re.compile(r"<\|?\s*(im_start|im_end|system|endoftext)\s*\|?>", re.IGNORECASE),
    re.compile(r"^\s*system\s*:", re.IGNORECASE),
    re.compile(r"^\s*assistant\s*:", re.IGNORECASE),
    re.compile(r"###\s*(instructions|system)", re.IGNORECASE),
)
_TAG = re.compile(r"<[^>]{0,400}>")
_SCRIPT_BLOCK = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


def strip_html(text: str) -> str:
    """Remove markup and entities from untrusted text."""
    without_scripts = _SCRIPT_BLOCK.sub(" ", text)
    return html.unescape(_TAG.sub(" ", without_scripts))


def sanitize_untrusted(text: str, *, max_chars: int = 600) -> tuple[str, bool]:
    """Clean a snippet and report whether it contains injection attempts.

    Suspicious segments are removed rather than forwarded to the model, and the
    surrounding content is still usable.
    """
    cleaned = " ".join(strip_html(text).split())
    suspicious = False
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(cleaned):
            suspicious = True
            cleaned = pattern.sub("[removed instruction text]", cleaned)
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rsplit(" ", 1)[0] + "..."
    return cleaned, suspicious


def wrap_untrusted(identifier: str, text: str) -> str:
    """Fence untrusted text so the model can see its provenance."""
    return f'<evidence id="{identifier}">\n{text.strip()}\n</evidence>'
