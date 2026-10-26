"""Schema.org Article output for machine-readable publishing."""

from __future__ import annotations

import json
from typing import Any

from draftproof.export.context import ExportContext


def build_jsonld_dict(context: ExportContext) -> dict[str, Any]:
    """Build a schema.org ``Article`` document."""
    outline = context.outline
    payload: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": outline.title,
        "description": outline.meta_description,
        "datePublished": context.generated_at.date().isoformat(),
        "dateModified": context.generated_at.date().isoformat(),
        "inLanguage": context.brief.language,
        "wordCount": context.total_words,
        "keywords": outline.tags,
        "abstract": outline.thesis,
        "author": {"@type": "Organization", "name": "DraftProof (AI-assisted draft)"},
        "isAccessibleForFree": True,
        "creativeWorkStatus": "Draft" if not context.quality.passed else "Published",
    }
    if context.evidence:
        payload["citation"] = [
            {
                "@type": "CreativeWork",
                "name": item.title,
                "url": item.url,
                "datePublished": item.published_at,
            }
            for item in context.evidence
        ]
    return payload


def build_jsonld(context: ExportContext) -> str:
    """Return the JSON-LD document as a JSON string."""
    return json.dumps(build_jsonld_dict(context), ensure_ascii=False, indent=2)
