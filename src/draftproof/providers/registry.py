"""Provider construction from settings."""

from __future__ import annotations

import logging
import os

import httpx

from draftproof.config import Settings, secret_value
from draftproof.domain.errors import ConfigurationError
from draftproof.domain.models import ProviderInfo
from draftproof.providers.anthropic import AnthropicProvider
from draftproof.providers.base import Provider
from draftproof.providers.mock import MockProvider
from draftproof.providers.openai_compat import OpenAICompatibleProvider
from draftproof.providers.pricing import PRESETS

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal")


def _is_local(base_url: str | None) -> bool:
    if not base_url:
        return False
    return any(host in base_url for host in _LOCAL_HOSTS)


def _resolve_model(name: str, settings: Settings) -> str:
    preset = PRESETS[name]
    if name == settings.provider and settings.model:
        return settings.model
    return preset.default_model


def _resolve_base_url(name: str, settings: Settings) -> str | None:
    preset = PRESETS[name]
    if name == settings.provider and settings.base_url:
        return settings.base_url
    return preset.base_url


def _resolve_key(name: str, settings: Settings) -> str | None:
    preset = PRESETS[name]
    if name == settings.provider:
        primary = secret_value(settings.api_key)
        if primary:
            return primary
    if name == "anthropic":
        anthropic_key = secret_value(settings.anthropic_api_key)
        if anthropic_key:
            return anthropic_key
    if preset.api_key_env:
        return os.environ.get(preset.api_key_env) or None
    return None


def build_provider(
    name: str,
    settings: Settings,
    *,
    client: httpx.Client | None = None,
) -> Provider:
    """Build one provider by name, raising when it cannot be configured."""
    key = name.strip().lower()
    preset = PRESETS.get(key)
    if preset is None:
        known = ", ".join(sorted(PRESETS))
        raise ConfigurationError(
            f"Unknown provider '{name}'",
            hint=f"Supported providers: {known}.",
        )

    model = _resolve_model(key, settings)
    base_url = _resolve_base_url(key, settings)

    if preset.kind == "mock":
        return MockProvider(model=model, seed=settings.seed)

    if not base_url:
        raise ConfigurationError(f"Provider '{key}' requires a base URL")

    api_key = _resolve_key(key, settings)
    if api_key is None and not _is_local(base_url):
        env_hint = preset.api_key_env or "DRAFTPROOF_API_KEY"
        raise ConfigurationError(
            f"Provider '{key}' requires an API key",
            hint=f"Set {env_hint}, or run with DRAFTPROOF_PROVIDER=mock.",
        )

    if preset.kind == "anthropic":
        if api_key is None:
            raise ConfigurationError("Anthropic provider requires an API key")
        return AnthropicProvider(
            key,
            model,
            base_url,
            api_key=api_key,
            timeout=settings.request_timeout,
            client=client,
        )

    return OpenAICompatibleProvider(
        key,
        model,
        base_url,
        api_key=api_key,
        timeout=settings.request_timeout,
        client=client,
    )


def build_providers(
    settings: Settings, *, client: httpx.Client | None = None
) -> dict[str, Provider]:
    """Build the configured chain, failing fast if the primary is unusable."""
    providers: dict[str, Provider] = {}
    for name in settings.provider_chain:
        try:
            providers[name] = build_provider(name, settings, client=client)
        except ConfigurationError:
            if name == settings.provider:
                raise
            logger.warning("Skipping fallback provider %s: not configured", name)
    return providers


def describe_providers(settings: Settings) -> list[ProviderInfo]:
    """Describe every known provider without raising on missing credentials."""
    described: list[ProviderInfo] = []
    for name, preset in sorted(PRESETS.items()):
        model = _resolve_model(name, settings)
        base_url = _resolve_base_url(name, settings)
        if preset.kind == "mock":
            described.append(
                ProviderInfo(
                    name=name,
                    kind=preset.kind,
                    model=model,
                    available=True,
                    note="Deterministic offline provider",
                )
            )
            continue
        key = _resolve_key(name, settings)
        available = bool(base_url) and (key is not None or _is_local(base_url))
        note = ""
        if not available:
            note = f"Set {preset.api_key_env}" if preset.api_key_env else "Requires a base URL"
        described.append(
            ProviderInfo(
                name=name,
                kind=preset.kind,
                model=model,
                available=available,
                note=note,
            )
        )
    return described
