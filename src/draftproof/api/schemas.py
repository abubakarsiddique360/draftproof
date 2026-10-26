"""Request and response schemas for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from draftproof.domain.models import (
    Brief,
    ContentType,
    ReviewDecision,
    RunStatus,
    RunSummary,
    Tone,
)


class CreateRunRequest(BaseModel):
    """Payload for ``POST /api/v1/runs``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    topic: str = Field(min_length=4, max_length=300, examples=["Vector search trade-offs"])
    audience: str = Field(default="software engineers", max_length=120)
    content_type: ContentType = ContentType.EXPLAINER
    tone: Tone = Tone.PRACTICAL
    target_words: int = Field(default=1400, ge=300, le=6000)
    key_points: list[str] = Field(default_factory=list, max_length=12)
    must_include: list[str] = Field(default_factory=list, max_length=12)
    must_avoid: list[str] = Field(default_factory=list, max_length=12)
    sources_required: bool = False
    language: str = Field(default="en", min_length=2, max_length=12)
    seed: int = Field(default=7, ge=0, le=1_000_000)

    @field_validator("key_points", "must_include", "must_avoid")
    @classmethod
    def _limit_items(cls, value: list[str]) -> list[str]:
        return [item[:200] for item in value][:12]

    def to_brief(self) -> Brief:
        """Convert the request into a validated brief."""
        return Brief(
            topic=self.topic,
            audience=self.audience,
            content_type=self.content_type,
            tone=self.tone,
            target_words=self.target_words,
            key_points=self.key_points,
            must_include=self.must_include,
            must_avoid=self.must_avoid,
            sources_required=self.sources_required,
            language=self.language,
            seed=self.seed,
        )


class RunCreated(BaseModel):
    """Response for a newly queued run."""

    run_id: str
    status: RunStatus
    topic: str
    stream_url: str


class ReviewRequest(BaseModel):
    """Editorial decision for ``POST /api/v1/runs/{id}/review``."""

    model_config = ConfigDict(extra="forbid")

    decision: ReviewDecision
    notes: str = Field(default="", max_length=2000)
    reviewer: str = Field(default="editor", max_length=120)
    section_ids: list[str] | None = None


class RegenerateRequest(BaseModel):
    """Payload for regenerating one section."""

    model_config = ConfigDict(extra="forbid")

    notes: str = Field(default="", max_length=2000)
    reviewer: str = Field(default="editor", max_length=120)


class CancelResponse(BaseModel):
    """Result of a cancellation request."""

    run_id: str
    cancelled: bool
    status: RunStatus


class HealthResponse(BaseModel):
    """Liveness payload."""

    status: str
    version: str
    database: str
    uptime_seconds: float


class ErrorBody(BaseModel):
    """Structured error envelope."""

    code: str
    message: str
    hint: str | None = None


class ErrorResponse(BaseModel):
    """Top level error envelope."""

    error: ErrorBody


class RunPage(BaseModel):
    """Paginated run list."""

    items: list[RunSummary]
    total: int
    limit: int
    offset: int


class RubricResponse(BaseModel):
    """Serialized rubric for the studio UI."""

    weights: dict[str, float]
    gates: list[dict[str, float | str]]
    flesch_target: list[float]
