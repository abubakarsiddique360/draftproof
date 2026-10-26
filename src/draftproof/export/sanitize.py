"""HTML sanitisation and Markdown rendering.

Raw HTML is disabled in the Markdown renderer and the output is then passed
through an allow-list sanitiser, so untrusted model output cannot introduce
scripts, event handlers or dangerous URL schemes into a published page.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "br",
        "code",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "em",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "s",
        "span",
        "strong",
        "sub",
        "summary",
        "sup",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
VOID_TAGS: frozenset[str] = frozenset({"br", "hr", "img"})
ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "title"}),
    "img": frozenset({"src", "alt", "title", "width", "height"}),
    "td": frozenset({"colspan", "rowspan"}),
    "th": frozenset({"colspan", "rowspan", "scope"}),
    "details": frozenset({"open"}),
    "div": frozenset({"class"}),
    "span": frozenset({"class"}),
    "code": frozenset({"class"}),
}
SAFE_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto"})
_ALLOWED_CLASSES: frozenset[str] = frozenset(
    {
        "quality-badge",
        "quality-pass",
        "quality-fail",
        "callout",
        "toc",
        "lede",
        "sources",
        "report",
        "metric",
        "metric-pass",
        "metric-fail",
    }
)


def _safe_url(value: str) -> bool:
    candidate = value.strip()
    if not candidate or candidate.startswith("//"):
        return False
    if candidate.startswith(("/", "#", "./", "../")):
        return True
    parts = urlsplit(candidate)
    if not parts.scheme:
        return True
    return parts.scheme.lower() in SAFE_SCHEMES


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self._stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            return
        allowed = ALLOWED_ATTRIBUTES.get(tag, frozenset())
        rendered: list[str] = []
        seen: set[str] = set()
        for key, value in attrs:
            name = key.lower()
            if name.startswith("on") or name not in allowed or value is None:
                continue
            if name in {"href", "src"} and not _safe_url(value):
                continue
            if name == "class":
                classes = [
                    item
                    for item in value.split()
                    if item in _ALLOWED_CLASSES
                    or re.fullmatch(r"language-[a-z0-9+#_.-]{1,20}", item)
                ]
                if not classes:
                    continue
                value = " ".join(classes)
            if name in seen:
                continue
            seen.add(name)
            rendered.append(f'{name}="{escape(value, quote=True)}"')

        if tag == "img" and "alt" not in seen:
            rendered.append('alt=""')
        if tag == "a" and "href" in seen:
            rendered.append('rel="noopener noreferrer nofollow"')

        attributes = (" " + " ".join(rendered)) if rendered else ""
        self.output.append(f"<{tag}{attributes}>")
        if tag not in VOID_TAGS:
            self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        if tag not in self._stack:
            return
        while self._stack:
            current = self._stack.pop()
            self.output.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data: str) -> None:
        self.output.append(escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        return

    def close(self) -> None:
        super().close()
        while self._stack:
            self.output.append(f"</{self._stack.pop()}>")


def sanitize_html(markup: str) -> str:
    """Return ``markup`` with every unsafe tag and attribute removed."""
    parser = _Sanitizer()
    parser.feed(markup)
    parser.close()
    return "".join(parser.output)


def _renderer() -> MarkdownIt:
    renderer = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    renderer.enable(["table", "strikethrough"])
    return renderer


def markdown_to_html(markdown: str) -> str:
    """Render Markdown to sanitised HTML."""
    return sanitize_html(_renderer().render(markdown))
