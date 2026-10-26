"""Standalone HTML export.

The page is self-contained: inline CSS, no external fonts or scripts, and a
JSON-LD block that is escaped so it cannot terminate the script element.
"""

from __future__ import annotations

from html import escape

from draftproof.export.context import ExportContext
from draftproof.export.jsonld import build_jsonld
from draftproof.export.sanitize import markdown_to_html

_CSS = """
:root { color-scheme: light dark; --bg:#fbfaf7; --fg:#1c1b19; --muted:#5f5c55;
  --accent:#0f766e; --line:#e3ded4; --card:#ffffff; --warn:#a16207; --bad:#b91c1c; }
@media (prefers-color-scheme: dark) { :root { --bg:#15171a; --fg:#eceae5; --muted:#a3a09a;
  --accent:#5eead4; --line:#2b2f36; --card:#1c1f24; --warn:#fbbf24; --bad:#f87171; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:17px/1.65 -apple-system,
  BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 46rem; margin: 0 auto; padding: 3.5rem 1.25rem 5rem; }
h1 { font-size: clamp(1.9rem, 4vw, 2.6rem); line-height:1.15; letter-spacing:-.02em;
  margin:0 0 .6rem; }
h2 { margin-top: 2.6rem; font-size:1.45rem; letter-spacing:-.01em; }
h3 { margin-top: 1.9rem; font-size:1.15rem; }
p, li { max-width: 68ch; }
a { color: var(--accent); text-underline-offset: 3px; }
code { font: .88em/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: color-mix(in srgb, var(--fg) 8%, transparent); padding:.15em .35em;
  border-radius:4px; }
pre { background: var(--card); border:1px solid var(--line); border-radius:10px;
  padding:1rem 1.1rem; overflow:auto; }
pre code { background:none; padding:0; font-size:.85rem; }
blockquote { margin:1.6rem 0; padding:.2rem 0 .2rem 1.1rem; border-left:3px solid var(--accent);
  color:var(--muted); font-size:1.05rem; }
table { width:100%; border-collapse: collapse; margin:1.4rem 0; font-size:.92rem; }
th, td { text-align:left; padding:.5rem .6rem; border-bottom:1px solid var(--line); }
th { font-weight:600; color:var(--muted); }
.lede { color:var(--muted); font-size:1.1rem; margin:0 0 1.6rem; }
.quality-badge { display:inline-flex; gap:.5rem; align-items:center; font-size:.82rem;
  border:1px solid var(--line); border-radius:999px; padding:.3rem .75rem; color:var(--muted); }
.quality-pass { color: var(--accent); }
.quality-fail { color: var(--bad); }
.meta { display:flex; flex-wrap:wrap; gap:.6rem; margin-bottom:2.4rem; }
details { margin-top:2.4rem; border-top:1px solid var(--line); padding-top:1rem; }
summary { cursor:pointer; font-weight:600; }
footer { margin-top:3rem; color:var(--muted); font-size:.85rem; }
@media print { body { background:#fff; color:#000; } details { display:block; } }
"""


def _badge(context: ExportContext) -> str:
    state = "quality-pass" if context.quality.passed else "quality-fail"
    label = "gates passed" if context.quality.passed else "gates failed"
    return (
        f'<span class="quality-badge {state}">{context.quality.score:.1f}/100 '
        f"({escape(context.quality.grade)}) &middot; {label}</span>"
    )


def _sources_block(context: ExportContext) -> str:
    if not context.evidence:
        return '<h2 class="sources">Sources</h2><p>No sources were retrieved for this run.</p>'
    items = []
    for item in context.evidence:
        items.append(
            f'<li><a href="{escape(item.url, quote=True)}" rel="noopener noreferrer nofollow">'
            f"{escape(item.title)}</a> <code>{escape(item.domain)}</code> "
            f"&middot; {escape(item.status.value)}</li>"
        )
    return '<h2 class="sources">Sources</h2><ol>' + "".join(items) + "</ol>"


def _report_block(context: ExportContext) -> str:
    rows = "".join(
        f"<tr><td>{escape(metric.label)}</td><td>{metric.score:.1f}</td>"
        f"<td>{metric.weight:.2f}</td><td>{escape(metric.detail)}</td></tr>"
        for metric in context.quality.metrics
    )
    notes = "".join(
        f"<li><strong>{escape(issue.severity.value.upper())}</strong>: {escape(issue.message)}</li>"
        for issue in context.quality.issues
    )
    return (
        '<details class="report"><summary>Editorial report</summary>'
        f"<p>{escape(context.quality.summary)}</p>"
        "<table><thead><tr><th>Metric</th><th>Score</th><th>Weight</th><th>Detail</th></tr>"
        f"</thead><tbody>{rows}</tbody></table>"
        + (f"<ul>{notes}</ul>" if notes else "")
        + "</details>"
    )


def render_html(context: ExportContext) -> str:
    """Render a self-contained HTML page."""
    outline = context.outline
    jsonld = build_jsonld(context).replace("<", "\\u003c")
    title = escape(outline.title)
    description = escape(outline.meta_description)
    subtitle = f'<p class="lede">{escape(outline.subtitle)}</p>' if outline.subtitle else ""
    body = markdown_to_html(context.body_markdown)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<meta name="author" content="ABU BAKAR SIDDIQUE">
<meta name="generator" content="DraftProof {escape(context.generator_version)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<style>{_CSS}</style>
<script type="application/ld+json">{jsonld}</script>
</head>
<body>
<main>
<article>
<header>
<div class="meta">{_badge(context)}</div>
<h1>{title}</h1>
{subtitle}
<blockquote>{escape(outline.thesis)}</blockquote>
</header>
{body}
{_sources_block(context)}
{_report_block(context)}
</article>
<footer>Generated by DraftProof &middot; run <code>{escape(context.run_id)}</code> &middot;
model <code>{escape(context.provider)}/{escape(context.model)}</code></footer>
</main>
</body>
</html>
"""
