"""Configuration behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from draftproof.config import Settings, secret_value


def test_defaults_are_safe(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    assert settings.provider == "mock"
    assert settings.retriever == "local_corpus"
    assert settings.verification_mode == "corpus"
    assert settings.api_key_required is False
    assert settings.db_path == tmp_path / "draftproof.db"


def test_comma_separated_lists_are_parsed() -> None:
    settings = Settings(fallback_providers="groq, ollama", cors_origins="https://a.example")
    assert settings.fallback_providers == ["groq", "ollama"]
    assert settings.cors_origins == ["https://a.example"]


def test_provider_chain_deduplicates() -> None:
    settings = Settings(provider="mock", fallback_providers=["mock", "groq", "GROQ"])
    assert settings.provider_chain == ["mock", "groq"]


def test_verification_mode_follows_retriever() -> None:
    assert Settings(retriever="local_corpus").verification_mode == "corpus"
    assert Settings(retriever="none").verification_mode == "off"
    assert Settings(retriever="local_corpus", verification="live").verification_mode == "live"


def test_snapshot_contains_no_secrets() -> None:
    settings = Settings(api_key="super-secret", service_api_key="also-secret")
    snapshot = settings.snapshot()
    assert "super-secret" not in str(snapshot)
    assert "also-secret" not in str(snapshot)
    assert snapshot["provider_chain"] == ["mock"]


def test_invalid_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="chatty")
    with pytest.raises(ValidationError):
        Settings(base_url="ftp://example.com")
    with pytest.raises(ValidationError):
        Settings(concurrency=0)


def test_tavily_requires_credentials() -> None:
    with pytest.raises(ValidationError):
        Settings(retriever="tavily")


def test_secret_value_helper() -> None:
    assert secret_value(None) is None
    assert secret_value(Settings(api_key="abc").api_key) == "abc"


def test_ensure_dirs_creates_paths(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "nested" / "data")
    settings.ensure_dirs()
    assert settings.data_dir.is_dir()
    assert settings.artifacts_dir.is_dir()
    assert settings.db_path.parent.is_dir()
