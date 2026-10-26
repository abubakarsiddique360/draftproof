"""Provenance manifest: the auditable record of how a draft was produced."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from draftproof.domain.models import Artifact
from draftproof.export.context import ExportContext


def build_manifest_dict(context: ExportContext, artifacts: Sequence[Artifact]) -> dict[str, Any]:
    """Assemble the manifest payload."""
    warnings: list[str] = []
    if not context.quality.passed:
        warnings.append("Quality gates failed: " + ", ".join(context.quality.failed_gates))
    if not context.evidence:
        warnings.append("No evidence was retrieved; factual claims are unsupported")
    if context.verification == "corpus":
        warnings.append(
            "Evidence was verified against the bundled offline corpus, not the public web"
        )
    suspicious = [item.id for item in context.evidence if item.injection_suspected]
    if suspicious:
        warnings.append(
            "Prompt-injection markers were removed from evidence: " + ", ".join(suspicious)
        )

    return {
        "schema_version": "1.0",
        "generator": {"name": "DraftProof", "version": context.generator_version},
        "run": {
            "id": context.run_id,
            "generated_at": context.generated_at.isoformat(),
            "provider": context.provider,
            "model": context.model,
            "verification": context.verification,
            "revision_attempts": context.revision_attempts,
        },
        "brief": context.brief.model_dump(mode="json"),
        "outline": context.outline.model_dump(mode="json"),
        "document": {
            "title": context.outline.title,
            "word_count": context.total_words,
            "sections": len(context.sections),
            "claims": len(context.claims),
            "verified_claims": sum(1 for claim in context.claims if claim.verified),
        },
        "evidence": [
            {
                "id": item.id,
                "title": item.title,
                "url": item.url,
                "domain": item.domain,
                "status": item.status.value,
                "http_status": item.http_status,
                "content_hash": item.content_hash,
                "overlap": item.overlap,
                "injection_suspected": item.injection_suspected,
                "published_at": item.published_at,
            }
            for item in context.evidence
        ],
        "claims": [claim.model_dump(mode="json") for claim in context.claims],
        "quality": context.quality.model_dump(mode="json"),
        "usage": context.usage.model_dump(mode="json"),
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
        "warnings": warnings,
    }


def render_manifest(context: ExportContext, artifacts: Sequence[Artifact]) -> str:
    """Serialize the manifest to JSON."""
    return json.dumps(build_manifest_dict(context, artifacts), ensure_ascii=False, indent=2)
