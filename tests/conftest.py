"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from draftproof.config import Settings
from draftproof.domain.models import Brief
from draftproof.pipeline.service import RunService


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        provider="mock",
        retriever="local_corpus",
        verification="auto",
        max_cost_usd=1.0,
        concurrency=4,
    )


@pytest.fixture()
def service(settings: Settings) -> Iterator[RunService]:
    instance = RunService.build(settings)
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture()
def brief() -> Brief:
    return Brief(
        topic="Retrieval-augmented generation in production",
        target_words=900,
        sources_required=True,
    )
