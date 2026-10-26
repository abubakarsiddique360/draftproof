"""Environment-driven configuration.

All settings use the ``DRAFTPROOF_`` prefix and can be supplied through the
process environment or a local ``.env`` file. Secrets are wrapped in
``SecretStr`` so they never leak into logs, API responses or provenance data.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from draftproof.domain.errors import ConfigurationError


def _split_csv(value: object) -> object:
    """Accept either a JSON list, a comma separated string or a real list."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            return value
        return [part.strip() for part in text.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    """Runtime configuration for the library, API and CLI."""

    model_config = SettingsConfigDict(
        env_prefix="DRAFTPROOF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Literal["dev", "test", "prod"] = "dev"
    data_dir: Path = Path("data")
    database_path: Path | None = None
    log_level: str = "INFO"

    # Model routing
    provider: str = "mock"
    model: str | None = None
    fallback_providers: Annotated[list[str], NoDecode] = Field(default_factory=list)
    base_url: str | None = None
    api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.25
    max_tokens: Annotated[int, Field(ge=128, le=32_000)] = 3000
    request_timeout: Annotated[float, Field(ge=1.0, le=600.0)] = 60.0
    max_retries: Annotated[int, Field(ge=0, le=5)] = 2
    concurrency: Annotated[int, Field(ge=1, le=16)] = 4
    seed: Annotated[int, Field(ge=0, le=1_000_000)] = 7

    # Pipeline policy
    max_revision_attempts: Annotated[int, Field(ge=0, le=4)] = 2
    max_cost_usd: Annotated[float, Field(ge=0.0, le=1000.0)] = 1.0
    review_required: bool = False

    # Research and verification
    retriever: Literal["local_corpus", "tavily", "none"] = "local_corpus"
    tavily_api_key: SecretStr | None = None
    search_endpoint: str | None = None
    evidence_limit: Annotated[int, Field(ge=1, le=20)] = 8
    results_per_query: Annotated[int, Field(ge=1, le=10)] = 4
    verification: Literal["auto", "live", "corpus", "off"] = "auto"
    verification_min_overlap: Annotated[float, Field(ge=0.0, le=1.0)] = 0.18
    allowed_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)
    blocked_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)
    fetch_max_bytes: Annotated[int, Field(ge=1024, le=2_000_000)] = 200_000
    fetch_timeout: Annotated[float, Field(ge=1.0, le=60.0)] = 8.0

    # HTTP service
    service_api_key: SecretStr | None = None
    rate_limit_per_minute: Annotated[int, Field(ge=0, le=100_000)] = 60
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    max_body_bytes: Annotated[int, Field(ge=1024, le=10_000_000)] = 262_144

    @field_validator(
        "fallback_providers", "allowed_domains", "blocked_domains", "cors_origins", mode="before"
    )
    @classmethod
    def _parse_lists(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("base_url", "search_endpoint")
    @classmethod
    def _validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().rstrip("/")
        if not text.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return text

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
        return level

    @model_validator(mode="after")
    def _validate_combo(self) -> Settings:
        if self.retriever == "tavily" and not self.tavily_api_key and not self.search_endpoint:
            raise ValueError(
                "retriever='tavily' requires DRAFTPROOF_TAVILY_API_KEY "
                "or DRAFTPROOF_SEARCH_ENDPOINT"
            )
        return self

    @property
    def db_path(self) -> Path:
        return self.database_path or self.data_dir / "draftproof.db"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def provider_chain(self) -> list[str]:
        chain = [self.provider, *self.fallback_providers]
        seen: set[str] = set()
        ordered: list[str] = []
        for name in chain:
            key = name.strip().lower()
            if key and key not in seen:
                seen.add(key)
                ordered.append(key)
        return ordered

    @property
    def verification_mode(self) -> Literal["live", "corpus", "off"]:
        if self.verification != "auto":
            return self.verification
        if self.retriever == "local_corpus":
            return "corpus"
        if self.retriever == "tavily":
            return "live"
        return "off"

    @property
    def api_key_required(self) -> bool:
        return self.service_api_key is not None

    def ensure_dirs(self) -> None:
        """Create the data and artifact directories if they do not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        parent = self.db_path.parent
        parent.mkdir(parents=True, exist_ok=True)

    def snapshot(self) -> dict[str, object]:
        """Return a secret-free snapshot suitable for provenance storage."""
        return {
            "provider": self.provider,
            "provider_chain": self.provider_chain,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "seed": self.seed,
            "concurrency": self.concurrency,
            "retriever": self.retriever,
            "verification": self.verification_mode,
            "evidence_limit": self.evidence_limit,
            "max_revision_attempts": self.max_revision_attempts,
            "max_cost_usd": self.max_cost_usd,
            "review_required": self.review_required,
        }

    def require_api_key(self) -> str:
        """Return the provider API key or raise a configuration error."""
        if self.api_key is None:
            raise ConfigurationError(
                "DRAFTPROOF_API_KEY is not set",
                hint="Export the key for your provider, or run with DRAFTPROOF_PROVIDER=mock.",
            )
        return self.api_key.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once with a compact, parseable format."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


def secret_value(secret: SecretStr | None) -> str | None:
    """Return the plaintext of an optional secret."""
    return secret.get_secret_value() if secret is not None else None
