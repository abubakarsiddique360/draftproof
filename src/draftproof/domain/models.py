"""Typed domain models shared by the pipeline, API, CLI and exporters."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(tz=UTC)


class ContentType(StrEnum):
    EXPLAINER = "explainer"
    TUTORIAL = "tutorial"
    COMPARISON = "comparison"
    ANALYSIS = "analysis"
    ANNOUNCEMENT = "announcement"


class Tone(StrEnum):
    PRACTICAL = "practical"
    AUTHORITATIVE = "authoritative"
    CONVERSATIONAL = "conversational"
    TECHNICAL = "technical"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    REVISING = "revising"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
)


class EvidenceStatus(StrEnum):
    VERIFIED = "verified"
    UNREACHABLE = "unreachable"
    BLOCKED = "blocked"
    UNCHECKED = "unchecked"


class SectionStatus(StrEnum):
    DRAFTED = "drafted"
    REVISED = "revised"
    FAILED = "failed"


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _clean_list(values: list[str], *, limit: int, item_limit: int = 200) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = " ".join(str(value).split()).strip(" -•\t")
        if not item or len(item) > item_limit:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
        if len(cleaned) >= limit:
            break
    return cleaned


class Brief(BaseModel):
    """The normalized creative brief that drives one run."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    topic: str = Field(min_length=4, max_length=300)
    audience: str = Field(default="software engineers", min_length=2, max_length=120)
    content_type: ContentType = ContentType.EXPLAINER
    tone: Tone = Tone.PRACTICAL
    target_words: Annotated[int, Field(ge=300, le=6000)] = 1400
    key_points: list[str] = Field(default_factory=list, max_length=12)
    must_include: list[str] = Field(default_factory=list, max_length=12)
    must_avoid: list[str] = Field(default_factory=list, max_length=12)
    sources_required: bool = False
    language: str = Field(default="en", min_length=2, max_length=12)
    seed: Annotated[int, Field(ge=0, le=1_000_000)] = 7

    @field_validator("topic", "audience")
    @classmethod
    def _collapse_ws(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("key_points", "must_include", "must_avoid")
    @classmethod
    def _normalize_list(cls, value: list[str]) -> list[str]:
        return _clean_list(value, limit=12)


class SectionPlan(BaseModel):
    """One planned section of the article."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: str = Field(pattern=r"^s[1-9][0-9]?$")
    title: str = Field(min_length=3, max_length=140)
    goal: str = Field(min_length=10, max_length=400)
    key_points: list[str] = Field(default_factory=list, max_length=6)
    target_words: Annotated[int, Field(ge=80, le=1200)] = 240
    requires_evidence: bool = False
    requires_code: bool = False

    @field_validator("key_points")
    @classmethod
    def _normalize_points(cls, value: list[str]) -> list[str]:
        return _clean_list(value, limit=6, item_limit=240)


class Outline(BaseModel):
    """The article blueprint produced by the planning stage."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str = Field(min_length=5, max_length=120)
    subtitle: str | None = Field(default=None, max_length=160)
    thesis: str = Field(min_length=20, max_length=600)
    meta_description: str = Field(min_length=40, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=8)
    sections: list[SectionPlan] = Field(min_length=3, max_length=10)

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        return _clean_list(value, limit=8, item_limit=40)

    @model_validator(mode="after")
    def _unique_section_ids(self) -> Outline:
        ids = [section.id for section in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("section ids must be unique")
        return self


class Evidence(BaseModel):
    """A retrievable source used to ground claims."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: str = Field(min_length=2, max_length=24)
    title: str = Field(min_length=1, max_length=240)
    url: str = Field(min_length=8, max_length=2048)
    domain: str = Field(min_length=1, max_length=200)
    snippet: str = Field(default="", max_length=1200)
    published_at: str | None = Field(default=None, max_length=40)
    retrieved_at: datetime = Field(default_factory=utc_now)
    status: EvidenceStatus = EvidenceStatus.UNCHECKED
    http_status: int | None = None
    overlap: float = Field(default=0.0, ge=0.0, le=1.0)
    content_hash: str | None = None
    source: str | None = Field(default=None, max_length=60)
    injection_suspected: bool = False


class Claim(BaseModel):
    """A factual assertion extracted from a section, linked to evidence."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: str = Field(min_length=2, max_length=24)
    section_id: str = Field(min_length=2, max_length=24)
    text: str = Field(min_length=5, max_length=600)
    evidence_ids: list[str] = Field(default_factory=list, max_length=6)
    verified: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=300)


class Section(BaseModel):
    """A drafted section plus its verification state."""

    model_config = ConfigDict(extra="ignore")

    plan: SectionPlan
    markdown: str = Field(default="", max_length=60_000)
    attempt: Annotated[int, Field(ge=1, le=20)] = 1
    claims: list[Claim] = Field(default_factory=list)
    grounding: float = Field(default=0.0, ge=0.0, le=1.0)
    status: SectionStatus = SectionStatus.DRAFTED


class MetricResult(BaseModel):
    """One scored quality metric."""

    key: str
    label: str
    value: float
    unit: str = ""
    score: float = Field(ge=0.0, le=100.0)
    weight: float = Field(ge=0.0, le=1.0)
    passed: bool
    detail: str = ""


class Issue(BaseModel):
    """An editorial problem with an actionable fix directive."""

    code: str
    message: str
    severity: Severity = Severity.MEDIUM
    section_id: str | None = None
    directive: str = ""


class QualityReport(BaseModel):
    """The outcome of the rubric evaluation."""

    score: float = Field(ge=0.0, le=100.0)
    grade: str = Field(min_length=1, max_length=2)
    passed: bool
    metrics: list[MetricResult] = Field(default_factory=list)
    failed_gates: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    summary: str = ""

    def metric(self, key: str) -> MetricResult | None:
        return next((metric for metric in self.metrics if metric.key == key), None)


class Usage(BaseModel):
    """Aggregated model usage for a run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            calls=self.calls + other.calls,
            cost_usd=round(self.cost_usd + other.cost_usd, 8),
        )


class Artifact(BaseModel):
    """A published file produced by a run."""

    kind: str
    relative_path: str
    sha256: str
    bytes: int
    created_at: datetime = Field(default_factory=utc_now)


class Review(BaseModel):
    """A human editorial decision recorded against a run."""

    decision: ReviewDecision
    notes: str = Field(default="", max_length=2000)
    reviewer: str = Field(default="editor", max_length=120)
    created_at: datetime = Field(default_factory=utc_now)


class RunRecord(BaseModel):
    """Full persisted state of a run."""

    id: str
    created_at: datetime
    updated_at: datetime
    status: RunStatus
    brief: Brief
    provider: str
    model: str
    parent_run_id: str | None = None
    outline: Outline | None = None
    quality: QualityReport | None = None
    usage: Usage = Field(default_factory=Usage)
    artifacts: list[Artifact] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    reviews: list[Review] = Field(default_factory=list)
    error: str | None = None
    finished_at: datetime | None = None


class RunSummary(BaseModel):
    """Compact run representation for list endpoints and CLI tables."""

    id: str
    topic: str
    status: RunStatus
    provider: str
    model: str
    score: float | None = None
    passed: bool | None = None
    created_at: datetime
    cost_usd: float = 0.0


class ProviderInfo(BaseModel):
    """Advertised provider capability."""

    name: str
    kind: str
    model: str
    available: bool
    note: str = ""


class ServerMeta(BaseModel):
    """Runtime capability report exposed by ``GET /api/v1/meta``."""

    name: str = "DraftProof"
    version: str
    provider_chain: list[str]
    retriever: str
    verification: str
    review_required: bool
    api_key_required: bool
    limits: dict[str, int | float]
    providers: list[ProviderInfo] = Field(default_factory=list)


StreamEventType = Literal[
    "run_started",
    "run_status",
    "stage_started",
    "stage_finished",
    "log",
    "warning",
    "outline_ready",
    "evidence_ready",
    "section_ready",
    "claims_ready",
    "verification_ready",
    "quality_scored",
    "revision_started",
    "revision_finished",
    "artifact_written",
    "usage",
    "run_finished",
]
