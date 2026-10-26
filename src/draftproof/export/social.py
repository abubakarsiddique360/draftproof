"""Social distribution pack derived from the finished article."""

from __future__ import annotations

import json
import re
from typing import Any

from draftproof.export.context import ExportContext
from draftproof.research.text import sentences, truncate

MAX_POST = 280


def _first_insight(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            return stripped[2:].strip()
    prose = " ".join(
        line.strip()
        for line in markdown.splitlines()
        if line.strip() and not line.startswith("#") and not line.startswith("```")
    )
    found = sentences(prose)
    return found[0] if found else prose


def _hashtag(tag: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", tag.title())
    return f"#{cleaned}" if cleaned else ""


def build_social_pack(context: ExportContext) -> dict[str, Any]:
    """Build ready-to-post copy for X and LinkedIn."""
    outline = context.outline
    raw_posts: list[str] = [truncate(f"{outline.title}\n\n{outline.thesis}", MAX_POST)]

    for section in context.sections:
        insight = _first_insight(section.markdown)
        raw_posts.append(truncate(f"{section.plan.title}\n\n{insight}", MAX_POST - 8))

    raw_posts.append(
        truncate(
            f"Full article: {outline.title}. {len(context.evidence)} sources, "
            f"quality score {context.quality.score:.1f}/100.",
            MAX_POST - 8,
        )
    )

    total = len(raw_posts)
    posts = [f"{text}\n\n{i}/{total}"[:MAX_POST] for i, text in enumerate(raw_posts, start=1)]

    bullets = [
        f"- {section.plan.title}: {_first_insight(section.markdown)}"
        for section in context.sections[:3]
    ]
    linkedin = truncate(
        "\n".join([outline.title, "", outline.thesis, "", *bullets]), 700, suffix="..."
    )

    return {
        "platform": "x",
        "thread_length": total,
        "posts": posts,
        "linkedin": linkedin,
        "hashtags": [tag for tag in (_hashtag(item) for item in outline.tags) if tag],
        "quality_score": context.quality.score,
        "claims_verified": sum(1 for claim in context.claims if claim.verified),
    }


def render_social(context: ExportContext) -> str:
    """Return the social pack as formatted JSON."""
    return json.dumps(build_social_pack(context), ensure_ascii=False, indent=2)
