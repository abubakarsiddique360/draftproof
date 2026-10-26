"""Pipeline package: context, stages, executor and application service."""

from __future__ import annotations

from draftproof.pipeline.context import PipelineContext
from draftproof.pipeline.events import (
    EventSink,
    NullEventSink,
    RecordingEventSink,
    RepositoryEventSink,
    TeeEventSink,
)
from draftproof.pipeline.executor import Pipeline, Stage, default_stages, revision_stages
from draftproof.pipeline.service import RunService, load_service

__all__ = [
    "EventSink",
    "NullEventSink",
    "Pipeline",
    "PipelineContext",
    "RecordingEventSink",
    "RepositoryEventSink",
    "RunService",
    "Stage",
    "TeeEventSink",
    "default_stages",
    "load_service",
    "revision_stages",
]
