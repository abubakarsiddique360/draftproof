"""Concrete pipeline stages.

Ordering, checkpointing and cancellation live in ``executor.py``; each stage
here only implements one unit of work and emits its own progress events.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from draftproof.domain.errors import (
    BudgetExceededError,
    InvalidModelOutputError,
    ProviderUnavailableError,
)
from draftproof.domain.models import (
    Claim,
    Evidence,
    EvidenceStatus,
    Outline,
    QualityReport,
    RunStatus,
    Section,
    SectionStatus,
    utc_now,
)
from draftproof.export.context import ExportContext
from draftproof.export.html import render_html
from draftproof.export.jsonld import build_jsonld
from draftproof.export.manifest import render_manifest
from draftproof.export.markdown import render_markdown
from draftproof.export.social import render_social
from draftproof.pipeline import prompts
from draftproof.pipeline.parsing import clean_section_markdown, parse_model
from draftproof.pipeline.schemas import RawClaims, RawOutline, normalize_outline
from draftproof.quality.evaluator import evaluate, failing_section_ids, global_directives
from draftproof.research.guard import sanitize_untrusted
from draftproof.research.retrievers import NullRetriever, RetrievedDoc
from draftproof.research.text import terms
from draftproof.research.urls import canonicalize, domain_of, host_matches

if TYPE_CHECKING:
    from draftproof.pipeline.context import PipelineContext


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _targets(context: PipelineContext) -> list[str]:
    return context.targets()


def _require_outline(context: PipelineContext) -> Outline:
    if context.outline is None:
        raise InvalidModelOutputError("The outline is missing from the run state", task="pipeline")
    return context.outline


def _require_quality(context: PipelineContext) -> QualityReport:
    if context.quality is None:
        raise InvalidModelOutputError("The quality report is missing", task="pipeline")
    return context.quality


def _evidence_for(
    context: PipelineContext, title: str, points: list[str], *, limit: int = 4
) -> list[Evidence]:
    if not context.evidence:
        return []
    wanted = terms(title + " " + " ".join(points))
    scored = sorted(
        context.evidence,
        key=lambda item: len(wanted & terms(item.title + " " + item.snippet)),
        reverse=True,
    )
    return scored[:limit]


def _draft_one(
    context: PipelineContext,
    plan_id: str,
    *,
    attempt: int,
    status: SectionStatus,
) -> Section:
    outline = _require_outline(context)
    existing = context.section(plan_id)
    plan = existing.plan
    evidence = _evidence_for(context, plan.title, plan.key_points)
    directives = context.directives_for(plan_id)
    previous = existing.markdown if (directives or attempt > 1) and existing.markdown else None

    request = prompts.section_request(
        brief=context.brief,
        outline=outline,
        plan=plan,
        evidence=evidence,
        directives=directives,
        previous=previous,
        attempt=attempt,
    )
    completion = context.router.complete(request)
    markdown = clean_section_markdown(completion.text, title=plan.title)
    return Section(
        plan=plan,
        markdown=markdown,
        attempt=attempt,
        status=status,
        claims=[],
        grounding=0.0,
    )


def _draft_many(
    context: PipelineContext,
    section_ids: list[str],
    *,
    attempt: int,
    status: SectionStatus,
) -> None:
    if not section_ids:
        return
    workers = min(context.settings.concurrency, len(section_ids))
    if workers <= 1:
        drafted = [
            _draft_one(context, section_id, attempt=attempt, status=status)
            for section_id in section_ids
        ]
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="draft") as pool:
            drafted = list(
                pool.map(
                    lambda section_id: _draft_one(
                        context, section_id, attempt=attempt, status=status
                    ),
                    section_ids,
                )
            )

    by_id = {section.plan.id: section for section in drafted}
    merged: list[Section] = []
    for section in context.sections:
        merged.append(by_id.get(section.plan.id, section))
    context.sections = merged
    context.sort_sections()
    for index, section in enumerate(context.sections):
        context.repo.upsert_section(context.run_id, index, section)
        if section.plan.id in by_id:
            context.sink.emit(
                "section_ready",
                {
                    "section_id": section.plan.id,
                    "title": section.plan.title,
                    "words": len(section.markdown.split()),
                    "attempt": section.attempt,
                },
            )


def _extract_claims_one(context: PipelineContext, section_id: str) -> list[Claim]:
    section = context.section(section_id)
    evidence = _evidence_for(context, section.plan.title, section.plan.key_points, limit=6)
    request = prompts.claims_request(section=section, evidence=evidence)
    completion = context.router.complete(request)
    payload = parse_model(completion.text, RawClaims, task="extract_claims")
    known = {item.id for item in context.evidence}
    claims: list[Claim] = []
    for index, item in enumerate(payload.claims[:6], start=1):
        text = " ".join(item.text.split())
        if len(text) < 5:
            continue
        claims.append(
            Claim(
                id=f"{section_id}c{index}",
                section_id=section_id,
                text=text[:600],
                evidence_ids=[
                    evidence_id for evidence_id in item.evidence_ids if evidence_id in known
                ][:6],
            )
        )
    return claims


def _extract_claims(context: PipelineContext, section_ids: list[str]) -> None:
    if not section_ids:
        return
    workers = min(context.settings.concurrency, len(section_ids))
    if workers <= 1:
        results = {
            section_id: _extract_claims_one(context, section_id) for section_id in section_ids
        }
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="claims") as pool:
            extracted = list(
                pool.map(lambda sid: (sid, _extract_claims_one(context, sid)), section_ids)
            )
        results = dict(extracted)

    for section_id, claims in results.items():
        context.set_section_claims(section_id, claims)
        context.sink.emit(
            "claims_ready",
            {"section_id": section_id, "claims": len(claims)},
        )
    context.repo.replace_claims(
        context.run_id,
        [claim for claims in results.values() for claim in claims],
        section_ids=section_ids,
    )


def _run_verification(context: PipelineContext) -> None:
    context.check_cancelled()
    result = context.verifier.verify(context.evidence, context.claims)
    context.evidence = result.evidence
    context.replace_claims(result.claims)
    context.mark_grounding()
    context.repo.update_evidence(context.run_id, context.evidence)
    context.repo.replace_claims(context.run_id, context.claims)
    for index, section in enumerate(context.sections):
        context.repo.upsert_section(context.run_id, index, section)
    context.sink.emit(
        "verification_ready",
        {
            "mode": context.verifier.name,
            "verified_claims": result.verified_claims,
            "total_claims": result.total_claims,
            "coverage": result.coverage,
            "verified_sources": sum(
                1 for item in context.evidence if item.status.value == "verified"
            ),
            "checked": result.checked,
        },
    )


def _evaluate(context: PipelineContext) -> None:
    outline = _require_outline(context)
    report = evaluate(
        outline=outline,
        sections=context.sections,
        claims=context.claims,
        brief=context.brief,
        rubric=context.rubric,
        revision_attempts=context.revision_attempts,
    )
    context.quality = report
    context.repo.save_quality(context.run_id, report)
    context.sink.emit(
        "quality_scored",
        {
            "score": report.score,
            "grade": report.grade,
            "passed": report.passed,
            "failed_gates": report.failed_gates,
            "metrics": [metric.model_dump() for metric in report.metrics],
            "issues": [issue.model_dump() for issue in report.issues],
            "attempt": context.revision_attempts,
        },
    )


# ----------------------------------------------------------------------
# Stages
# ----------------------------------------------------------------------
def brief_stage(context: PipelineContext) -> None:
    """Validate the brief and record the run policy."""
    if context.brief.sources_required and isinstance(context.retriever, NullRetriever):
        message = "Sources were requested but research is disabled for this run"
        context.warnings.append(message)
        context.sink.emit("warning", {"message": message})
    context.sink.emit(
        "log",
        {
            "stage": "brief",
            "message": f"Planning {context.brief.content_type.value} for {context.brief.audience}",
            "target_words": context.brief.target_words,
        },
    )


def plan_stage(context: PipelineContext) -> None:
    """Create the article outline."""
    evidence_available = not isinstance(context.retriever, NullRetriever)
    request = prompts.outline_request(context.brief, evidence_available=evidence_available)
    completion = context.router.complete(request)
    raw = parse_model(completion.text, RawOutline, task="plan_outline")
    outline = normalize_outline(raw, context.brief, evidence_available=evidence_available)
    context.outline = outline
    context.repo.save_outline(context.run_id, outline)
    context.sections = [
        Section(plan=plan, markdown="", attempt=1, status=SectionStatus.DRAFTED)
        for plan in outline.sections
    ]
    context.sink.emit(
        "outline_ready",
        {
            "title": outline.title,
            "sections": [
                {"id": plan.id, "title": plan.title, "target_words": plan.target_words}
                for plan in outline.sections
            ],
            "target_words": sum(plan.target_words for plan in outline.sections),
        },
    )


def _queries(context: PipelineContext) -> list[str]:
    outline = _require_outline(context)
    candidates = [context.brief.topic, outline.title]
    candidates.extend(plan.title for plan in outline.sections)
    seen: set[str] = set()
    queries: list[str] = []
    for candidate in candidates:
        cleaned = " ".join(candidate.split())
        key = cleaned.casefold()
        if len(cleaned) < 8 or key in seen:
            continue
        seen.add(key)
        queries.append(cleaned)
        if len(queries) >= 6:
            break
    return queries


def research_stage(context: PipelineContext) -> None:
    """Retrieve, filter and normalise evidence."""
    if context.outline is None:
        raise InvalidModelOutputError("Research started without an outline", task="research")
    if isinstance(context.retriever, NullRetriever):
        context.sink.emit("warning", {"message": "Research disabled: no retriever configured"})
        return

    raw_docs: list[RetrievedDoc] = []
    for query in _queries(context):
        context.check_cancelled()
        try:
            raw_docs.extend(
                context.retriever.search(query, limit=context.settings.results_per_query)
            )
        except Exception as exc:
            message = f"Retriever failed for query '{query}': {exc}"
            logger.warning(message)
            context.warnings.append(message)
            context.sink.emit("warning", {"message": message})

    deduped: dict[str, RetrievedDoc] = {}
    for doc in raw_docs:
        url = canonicalize(doc.url)
        existing = deduped.get(url)
        if existing is None or doc.score > existing.score:
            deduped[url] = RetrievedDoc(
                title=doc.title,
                url=url,
                snippet=doc.snippet,
                published_at=doc.published_at,
                source=doc.source,
                score=doc.score,
                metadata=doc.metadata,
            )

    allowed = context.settings.allowed_domains
    blocked = context.settings.blocked_domains
    filtered: list[RetrievedDoc] = []
    for doc in deduped.values():
        domain = domain_of(doc.url)
        if blocked and host_matches(domain, blocked):
            continue
        if allowed and not host_matches(domain, allowed):
            continue
        filtered.append(doc)

    filtered.sort(key=lambda item: (-item.score, item.title))
    selected = filtered[: context.settings.evidence_limit]

    evidence: list[Evidence] = []
    for index, doc in enumerate(selected, start=1):
        snippet, suspicious = sanitize_untrusted(doc.snippet)
        evidence.append(
            Evidence(
                id=f"ev{index}",
                title=doc.title[:240] or doc.url,
                url=doc.url,
                domain=domain_of(doc.url),
                snippet=snippet,
                published_at=doc.published_at,
                status=EvidenceStatus.UNCHECKED,
                source=doc.source,
                injection_suspected=suspicious,
            )
        )

    context.evidence = evidence
    context.repo.replace_evidence(context.run_id, evidence)
    context.sink.emit(
        "evidence_ready",
        {
            "count": len(evidence),
            "candidates": len(deduped),
            "items": [
                {"id": item.id, "title": item.title, "url": item.url, "domain": item.domain}
                for item in evidence
            ],
        },
    )
    if not evidence:
        message = "No evidence matched this topic; claims cannot be grounded"
        context.warnings.append(message)
        context.sink.emit("warning", {"message": message})


def draft_stage(context: PipelineContext) -> None:
    """Draft every targeted section in parallel."""
    if context.outline is None:
        raise InvalidModelOutputError("Drafting started without an outline", task="draft_section")
    attempt = max(1, context.revision_attempts + 1)
    status = SectionStatus.REVISED if context.revision_attempts else SectionStatus.DRAFTED
    _draft_many(context, _targets(context), attempt=attempt, status=status)


def claims_stage(context: PipelineContext) -> None:
    """Extract and persist claims for the targeted sections."""
    _extract_claims(context, _targets(context))


def verify_stage(context: PipelineContext) -> None:
    """Verify every claim against its evidence."""
    _run_verification(context)


def critique_stage(context: PipelineContext) -> None:
    """Score the draft against the rubric."""
    _evaluate(context)


def revise_stage(context: PipelineContext) -> None:
    """Revise failing sections until the gates pass or the budget runs out."""
    if context.quality is None:
        _evaluate(context)

    max_attempts = context.settings.max_revision_attempts
    while context.quality is not None and not context.quality.passed:
        if context.revision_attempts >= max_attempts:
            break
        context.check_cancelled()
        context.revision_attempts += 1
        report = context.quality
        targets = failing_section_ids(report)
        if not targets:
            targets = [section.plan.id for section in context.sections]

        directives: dict[str, list[str]] = {
            key: list(value) for key, value in context.review_directives.items()
        }
        directives.setdefault("*", [])
        directives["*"] = [*directives["*"], *global_directives(report)]
        for issue in report.issues:
            if issue.section_id and issue.directive:
                directives.setdefault(issue.section_id, []).append(issue.directive)

        context.sink.emit(
            "revision_started",
            {"attempt": context.revision_attempts, "sections": targets, "score": report.score},
        )
        previous_targets = context.target_section_ids
        context.target_section_ids = set(targets)
        context.review_directives = directives
        try:
            _draft_many(
                context,
                targets,
                attempt=context.revision_attempts + 1,
                status=SectionStatus.REVISED,
            )
            for section_id in targets:
                context.set_section_status(
                    section_id, SectionStatus.REVISED, context.revision_attempts + 1
                )
            _extract_claims(context, targets)
            _run_verification(context)
            _evaluate(context)
        except (BudgetExceededError, ProviderUnavailableError) as exc:
            message = f"Revision stopped early: {exc.message}"
            context.warnings.append(message)
            context.sink.emit("warning", {"message": message})
            break
        finally:
            context.target_section_ids = previous_targets

        report = _require_quality(context)
        context.sink.emit(
            "revision_finished",
            {
                "attempt": context.revision_attempts,
                "score": report.score,
                "passed": report.passed,
                "failed_gates": report.failed_gates,
            },
        )

    if context.quality is not None and not context.quality.passed:
        message = (
            "Quality gates still failing after "
            f"{context.revision_attempts} revision attempt(s): "
            + ", ".join(context.quality.failed_gates)
        )
        context.warnings.append(message)
        context.sink.emit("warning", {"message": message})


def publish_stage(context: PipelineContext) -> None:
    """Render every artifact, write the provenance manifest and finish the run."""
    if context.outline is None or context.quality is None:
        raise InvalidModelOutputError("Publishing requires an outline and a quality report")

    usage = context.router.ledger.snapshot()
    context.repo.set_usage(context.run_id, usage)
    export_context = ExportContext(
        run_id=context.run_id,
        brief=context.brief,
        outline=context.outline,
        sections=context.sections,
        evidence=context.evidence,
        claims=context.claims,
        quality=context.quality,
        usage=usage,
        provider=context.settings.provider,
        model=context.model_name or context.settings.model or context.settings.provider,
        verification=context.verifier.name,
        generated_at=utc_now(),
        generator_version=_version(),
        revision_attempts=context.revision_attempts,
    )

    payloads: dict[str, str] = {
        "markdown": render_markdown(export_context),
        "html": render_html(export_context),
        "jsonld": build_jsonld(export_context),
        "social": render_social(export_context),
        "quality": context.quality.model_dump_json(indent=2),
        "outline": context.outline.model_dump_json(indent=2),
    }
    artifacts = [
        context.artifacts.write(context.run_id, kind, payload) for kind, payload in payloads.items()
    ]
    artifacts.append(
        context.artifacts.write(
            context.run_id, "manifest", render_manifest(export_context, artifacts)
        )
    )
    for artifact in artifacts:
        context.repo.add_artifact(context.run_id, artifact)
        context.sink.emit(
            "artifact_written",
            {
                "kind": artifact.kind,
                "bytes": artifact.bytes,
                "sha256": artifact.sha256,
                "path": artifact.relative_path,
            },
        )

    status = (
        RunStatus.AWAITING_REVIEW
        if context.settings.review_required and not context.auto_complete
        else RunStatus.COMPLETED
    )
    context.repo.set_status(context.run_id, status)
    context.sink.emit(
        "run_finished",
        {
            "status": status.value,
            "score": context.quality.score,
            "passed": context.quality.passed,
            "grade": context.quality.grade,
            "artifacts": [artifact.kind for artifact in artifacts],
            "warnings": context.warnings,
            "usage": usage.model_dump(),
        },
    )


def _version() -> str:
    from draftproof import __version__

    return __version__
