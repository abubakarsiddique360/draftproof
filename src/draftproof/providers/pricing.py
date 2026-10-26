"""Known provider presets and per-model price data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Preset:
    """Static defaults for a named provider."""

    kind: str
    base_url: str | None
    default_model: str
    api_key_env: str | None


PRESETS: dict[str, Preset] = {
    "mock": Preset(kind="mock", base_url=None, default_model="mock-writer-1", api_key_env=None),
    "openai": Preset(
        kind="openai",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
    ),
    "groq": Preset(
        kind="openai",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        api_key_env="GROQ_API_KEY",
    ),
    "ollama": Preset(
        kind="openai",
        base_url="http://localhost:11434/v1",
        default_model="llama3.1:8b",
        api_key_env=None,
    ),
    "openrouter": Preset(
        kind="openai",
        base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        api_key_env="OPENROUTER_API_KEY",
    ),
    "anthropic": Preset(
        kind="anthropic",
        base_url="https://api.anthropic.com",
        default_model="claude-3-5-sonnet-latest",
        api_key_env="ANTHROPIC_API_KEY",
    ),
}

# USD per one million tokens: (input, output). Unknown models estimate to zero
# and are surfaced in the run provenance as "unpriced".
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-sonnet-4": (3.00, 15.00),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate the USD cost of a call, returning ``0.0`` for unknown models."""
    key = model.strip().lower()
    price: tuple[float, float] | None = PRICES.get(key)
    if price is None:
        for prefix, candidate in PRICES.items():
            if key.startswith(prefix):
                price = candidate
                break
    if price is None:
        return 0.0
    prompt_price, completion_price = price
    cost = (prompt_tokens / 1_000_000) * prompt_price
    cost += (completion_tokens / 1_000_000) * completion_price
    return round(cost, 8)


def is_priced(model: str) -> bool:
    """Report whether a model has a known price entry."""
    key = model.strip().lower()
    return key in PRICES or any(key.startswith(prefix) for prefix in PRICES)
