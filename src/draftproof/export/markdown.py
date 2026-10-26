"""Markdown export with front matter, source list and editorial report."""

from __future__ import annotations

import json

from draftproof.export.context import ExportContext


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _front_matter(context: ExportContext) -> str:
    outline = context.outline
    tags = ", ".join(_yaml_string(tag) for tag in outline.tags) or ""
    lines = [
        "---",
        f"title: {_yaml_string(outline.title)}",
        f"description: {_yaml_string(outline.meta_description)}",
        f"date: {context.generated_at.date().isoformat()}",
        f"generator: {_yaml_string(f'DraftProof {context.generator_version}')}",
        f"run_id: {_yaml_string(context.run_id)}",
        f"quality_score: {context.quality.score}",
        f"quality_grade: {_yaml_string(context.quality.grade)}",
        f"gates_passed: {'true' if context.quality.passed else 'false'}",
        f"verification: {_yaml_string(context.verification)}",
        f"provider: {_yaml_string(context.provider)}",
        f"model: {_yaml_string(context.model)}",
        f"tags: [{tags}]",
        "---",
    ]
    return "\n".join(lines)


def _sources(context: ExportContext) -> str:
    if not context.evidence:
        return "## Sources\n\n_No sources were retrieved for this run._"
    lines = ["## Sources", ""]
    for index, item in enumerate(context.evidence, start=1):
        status = item.status.value
        marker = "verified" if status == "verified" else f"**{status}**"
        lines.append(f"{index}. [{item.title}]({item.url}) — `{item.domain}` — {marker}")
    if context.verification == "corpus":
        lines.append("")
        lines.append(
            "_Sources resolved against the bundled offline corpus that ships with DraftProof; "
            "no external network calls were made._"
        )
    return "\n".join(lines)


def _report(context: ExportContext) -> str:
    report = context.quality
    gate_line = "passed" if report.passed else "failed: " + ", ".join(report.failed_gates)
    lines = [
        "## Editorial report",
        "",
        f"- **Score:** {report.score:.1f} / 100 ({report.grade})",
        f"- **Gates:** {gate_line}",
        f"- **Claims verified:** {sum(1 for claim in context.claims if claim.verified)}"
        f" / {len(context.claims)}",
        f"- **Usage:** {context.usage.total_tokens:,} tokens across {context.usage.calls} calls"
        f" (${context.usage.cost_usd:.4f})",
        "",
        "| Metric | Score | Weight | Detail |",
        "| --- | ---: | ---: | --- |",
    ]
    for metric in report.metrics:
        lines.append(
            f"| {metric.label} | {metric.score:.1f} | {metric.weight:.2f} | {metric.detail} |"
        )
    if report.issues:
        lines.extend(["", "### Editorial notes", ""])
        for issue in report.issues:
            scope = f" ({issue.section_id})" if issue.section_id else ""
            lines.append(f"- **{issue.severity.value.upper()}**{scope}: {issue.message}")
            if issue.directive:
                lines.append(f"  - _Fix:_ {issue.directive}")
    return "\n".join(lines)


def render_markdown(context: ExportContext) -> str:
    """Render the complete, publish-ready Markdown article."""
    outline = context.outline
    parts = [
        _front_matter(context),
        "",
        f"# {outline.title}",
        "",
    ]
    if outline.subtitle:
        parts.extend([f"*{outline.subtitle}*", ""])
    parts.extend(
        [
            f"> {outline.thesis}",
            "",
            context.body_markdown,
            "",
            _sources(context),
            "",
            _report(context),
            "",
        ]
    )
    return "\n".join(parts).strip() + "\n"
