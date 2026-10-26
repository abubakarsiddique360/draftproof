"""HTML sanitisation and every exporter."""

from __future__ import annotations

import json

from draftproof.domain.models import (
    Brief,
    Claim,
    Evidence,
    Outline,
    Section,
    SectionPlan,
    Usage,
    utc_now,
)
from draftproof.export.context import ExportContext
from draftproof.export.html import render_html
from draftproof.export.jsonld import build_jsonld, build_jsonld_dict
from draftproof.export.manifest import build_manifest_dict, render_manifest
from draftproof.export.markdown import render_markdown
from draftproof.export.sanitize import markdown_to_html, sanitize_html
from draftproof.export.social import build_social_pack
from draftproof.quality.evaluator import evaluate


def _context(*, title_suffix: str = "") -> ExportContext:
    brief = Brief(topic="Vector search", target_words=600, sources_required=True)
    plans = [
        SectionPlan(
            id=f"s{index}",
            title=f"Index trade-offs {index}",
            goal="Explain the trade-offs clearly for the reader.",
            key_points=["HNSW", "IVF"],
            target_words=200,
        )
        for index in range(1, 4)
    ]
    outline = Outline(
        title=f"A practical guide to vector search{title_suffix}",
        subtitle="Latency, recall and cost",
        thesis="Choose an index by measuring recall at your latency budget.",
        meta_description="A practical guide to vector search covering recall, latency and cost.",
        tags=["vector", "search"],
        sections=plans,
    )
    evidence = Evidence(
        id="ev1",
        title="Vector index trade-offs",
        url="https://docs.example.com/vector",
        domain="docs.example.com",
        snippet="Flat search is exact, HNSW is approximate.",
        retrieved_at=utc_now(),
    )
    sections: list[Section] = []
    claims: list[Claim] = []
    for index, plan in enumerate(plans, start=1):
        claim = Claim(
            id=f"s{index}c1",
            section_id=plan.id,
            text="HNSW is approximate.",
            evidence_ids=["ev1"],
            verified=True,
        )
        claims.append(claim)
        sections.append(
            Section(
                plan=plan,
                markdown=(
                    f"## {plan.title}\n\nFlat search is exact. HNSW trades recall for latency.\n\n"
                    "```python\nx = 1\n```\n"
                ),
                claims=[claim],
            )
        )
    quality = evaluate(outline=outline, sections=sections, claims=claims, brief=brief)
    return ExportContext(
        run_id="run_abc123def456",
        brief=brief,
        outline=outline,
        sections=sections,
        evidence=[evidence],
        claims=claims,
        quality=quality,
        usage=Usage(prompt_tokens=100, completion_tokens=50, calls=2, cost_usd=0.01),
        provider="mock",
        model="mock-writer-1",
        verification="corpus",
        generated_at=utc_now(),
        generator_version="0.1.0",
    )


# ----------------------------------------------------------------------
# Sanitiser
# ----------------------------------------------------------------------
def test_sanitizer_removes_scripts_and_handlers() -> None:
    dirty = (
        '<p onclick="alert(1)">hello</p><script>alert(2)</script>'
        '<img src="https://example.com/x.png" onerror="alert(3)">'
    )
    cleaned = sanitize_html(dirty)
    assert "<script" not in cleaned
    assert "onclick" not in cleaned
    assert "onerror" not in cleaned
    assert 'alt=""' in cleaned


def test_sanitizer_blocks_dangerous_urls() -> None:
    cleaned = sanitize_html(
        '<a href="javascript:alert(1)">x</a><a href="data:text/html,evil">y</a>'
        '<a href="https://example.com">ok</a>'
    )
    assert "javascript:" not in cleaned
    assert "data:text/html" not in cleaned
    assert 'href="https://example.com"' in cleaned
    assert 'rel="noopener noreferrer nofollow"' in cleaned


def test_sanitizer_drops_unknown_tags_but_keeps_text() -> None:
    cleaned = sanitize_html("<iframe src='x'></iframe><custom>kept</custom>")
    assert "iframe" not in cleaned
    assert "custom" not in cleaned
    assert "kept" in cleaned


def test_sanitizer_filters_classes_and_closes_open_tags() -> None:
    cleaned = sanitize_html('<div class="quality-badge evil"><strong>text')
    assert 'class="quality-badge"' in cleaned
    assert "evil" not in cleaned
    assert cleaned.endswith("</strong></div>")


def test_markdown_to_html_escapes_raw_html() -> None:
    rendered = markdown_to_html("Hello <script>alert(1)</script> **world**")
    assert "<script" not in rendered
    assert "<strong>world</strong>" in rendered


def test_markdown_to_html_supports_common_blocks() -> None:
    rendered = markdown_to_html(
        "# Title\n\n- one\n- two\n\n> quote\n\n```python\nprint(1)\n```\n\n[l](https://example.com)"
    )
    assert "<h1>" in rendered
    assert "<ul>" in rendered
    assert "<blockquote>" in rendered
    assert 'class="language-python"' in rendered
    assert 'href="https://example.com"' in rendered


# ----------------------------------------------------------------------
# Exports
# ----------------------------------------------------------------------
def test_markdown_export_contains_front_matter_and_report() -> None:
    markdown = render_markdown(_context())
    assert markdown.startswith("---\n")
    assert "quality_score:" in markdown
    assert "# A practical guide to vector search" in markdown
    assert "## Editorial report" in markdown
    assert "https://docs.example.com/vector" in markdown


def test_html_export_is_self_contained_and_escaped() -> None:
    html = render_html(_context(title_suffix=" </script><script>alert(1)</script>"))
    assert html.startswith("<!DOCTYPE html>")
    assert '<html lang="en">' in html
    assert "<style>" in html
    assert "<script>alert(1)</script>" not in html
    assert "application/ld+json" in html
    assert "\\u003c" in html


def test_jsonld_is_valid_schema_org() -> None:
    context = _context()
    payload = build_jsonld_dict(context)
    assert payload["@context"] == "https://schema.org"
    assert payload["@type"] == "Article"
    assert payload["headline"] == context.outline.title
    assert payload["citation"][0]["url"] == "https://docs.example.com/vector"
    assert json.loads(build_jsonld(context))["wordCount"] > 0


def test_social_pack_respects_post_limits() -> None:
    pack = build_social_pack(_context())
    assert pack["thread_length"] == len(pack["posts"]) >= 2
    for post in pack["posts"]:
        assert len(post) <= 280
    assert pack["linkedin"]
    assert "#Vector" in pack["hashtags"]


def test_manifest_lists_artifacts_and_warnings() -> None:
    context = _context()
    from draftproof.domain.models import Artifact

    artifacts = [
        Artifact(kind="markdown", relative_path="run/article.md", sha256="a" * 64, bytes=10)
    ]
    payload = build_manifest_dict(context, artifacts)
    assert payload["run"]["id"] == "run_abc123def456"
    assert payload["artifacts"][0]["kind"] == "markdown"
    assert payload["claims"][0]["verified"] is True
    assert any("corpus" in warning for warning in payload["warnings"])
    assert json.loads(render_manifest(context, artifacts))["schema_version"] == "1.0"
