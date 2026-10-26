"""Provider implementations, schema synthesis and the resilient router."""

from __future__ import annotations

import json
from typing import Any, Literal

import httpx
import pytest
from pydantic import BaseModel

from draftproof.domain.errors import (
    BudgetExceededError,
    ProviderError,
    ProviderUnavailableError,
    TransientProviderError,
)
from draftproof.providers.anthropic import AnthropicProvider
from draftproof.providers.base import Completion, CompletionRequest, JsonSchema, Message
from draftproof.providers.jsonschema_mock import synthesize
from draftproof.providers.mock import MockProvider
from draftproof.providers.openai_compat import OpenAICompatibleProvider
from draftproof.providers.pricing import estimate_cost, is_priced
from draftproof.providers.router import CircuitBreaker, ModelRouter, UsageLedger


def _request(
    task: str = "draft_section", *, schema: JsonSchema | None = None, user: str = "hello"
) -> CompletionRequest:
    return CompletionRequest(
        messages=(Message(role="system", content="system"), Message(role="user", content=user)),
        task=task,
        schema=schema,
        max_tokens=256,
    )


# ----------------------------------------------------------------------
# Mock provider
# ----------------------------------------------------------------------
def test_mock_is_deterministic() -> None:
    provider = MockProvider()
    first = provider.complete(_request())
    second = provider.complete(_request())
    assert first.text == second.text
    assert first.cost_usd == 0.0
    assert first.prompt_tokens > 0


def test_mock_section_output_has_heading_and_links() -> None:
    prompt = (
        "Section title: Measuring latency\n"
        "Section id: s2\n"
        "Goal: Explain how to measure latency.\n"
        "Audience: engineers\n"
        "Target words: 200\n"
        "Requires code: false\n"
        "Key points:\n- First point\n- Second point\n"
        "Evidence (cite these when a paragraph needs support):\n"
        "- ev1 | A source | https://docs.example.com/a\n"
    )
    completion = MockProvider().complete(_request(user=prompt))
    assert completion.text.startswith("## Measuring latency")
    assert "https://docs.example.com/a" in completion.text


def test_mock_section_output_is_unique_across_sections() -> None:
    def prompt(section: int) -> str:
        return (
            f"Section title: Section {section}\nSection id: s{section}\n"
            "Goal: Explain the topic.\nAudience: engineers\nTarget words: 220\n"
            "Requires code: false\nKey points:\n- A point\n"
        )

    provider = MockProvider()
    first = provider.complete(_request(user=prompt(1))).text
    second = provider.complete(_request(user=prompt(2))).text
    first_sentences = {line for line in first.splitlines() if len(line.split()) > 6}
    second_sentences = {line for line in second.splitlines() if len(line.split()) > 6}
    assert first_sentences.isdisjoint(second_sentences)


def test_mock_code_section_is_valid_python() -> None:
    prompt = (
        "Section title: Build it\nSection id: s1\nGoal: Show code.\n"
        "Target words: 150\nRequires code: true\n"
    )
    text = MockProvider().complete(_request(user=prompt)).text
    assert "```python" in text


class _Nested(BaseModel):
    name: str
    score: float
    tags: list[str]
    enabled: bool
    choice: Literal["alpha", "beta"]


def test_schema_synthesis_matches_pydantic_model() -> None:
    import random

    schema = _Nested.model_json_schema()
    for seed in range(5):
        payload = synthesize(schema, random.Random(seed))
        model = _Nested.model_validate(payload)
        assert isinstance(model.tags, list)
        assert model.choice in {"alpha", "beta"}


def test_mock_handles_unknown_schema_name() -> None:
    schema = JsonSchema(name="other", schema=_Nested.model_json_schema())
    completion = MockProvider().complete(_request("generic", schema=schema))
    _Nested.model_validate(json.loads(completion.text))


# ----------------------------------------------------------------------
# OpenAI-compatible provider
# ----------------------------------------------------------------------
def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_provider_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        body = json.loads(request.content)
        assert body["model"] == "gpt-4o-mini"
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 2000},
            },
        )

    provider = OpenAICompatibleProvider(
        "openai",
        "gpt-4o-mini",
        "https://api.example.com/v1",
        api_key="secret",
        client=_client(handler),
    )
    completion = provider.complete(_request())
    assert completion.text == "hello"
    assert completion.prompt_tokens == 1000
    assert completion.cost_usd == pytest.approx(estimate_cost("gpt-4o-mini", 1000, 2000))


def test_openai_provider_retries_without_response_format() -> None:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": "unsupported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    schema = JsonSchema(name="claims", schema={"type": "object"})
    provider = OpenAICompatibleProvider(
        "ollama", "model", "http://localhost:11434/v1", client=_client(handler)
    )
    completion = provider.complete(_request(schema=schema))
    assert completion.text == "{}"
    assert len(calls) == 2
    assert "response_format" not in calls[1]


def test_openai_provider_maps_transient_errors() -> None:
    provider = OpenAICompatibleProvider(
        "groq",
        "model",
        "https://api.example.com",
        api_key="k",
        client=_client(lambda request: httpx.Response(429, text="slow down")),
    )
    with pytest.raises(TransientProviderError):
        provider.complete(_request())


def test_openai_provider_maps_client_errors() -> None:
    provider = OpenAICompatibleProvider(
        "groq",
        "model",
        "https://api.example.com",
        api_key="k",
        client=_client(lambda request: httpx.Response(401, text="nope")),
    )
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(_request())
    assert not isinstance(excinfo.value, TransientProviderError)


def test_openai_provider_handles_content_parts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": [{"type": "text", "text": "part"}]}}]},
        )

    provider = OpenAICompatibleProvider(
        "x", "m", "https://e.x", api_key="k", client=_client(handler)
    )
    assert provider.complete(_request()).text == "part"


def test_openai_provider_rejects_empty_payload() -> None:
    provider = OpenAICompatibleProvider(
        "x",
        "m",
        "https://e.x",
        api_key="k",
        client=_client(lambda request: httpx.Response(200, json={})),
    )
    with pytest.raises(ProviderError):
        provider.complete(_request())


# ----------------------------------------------------------------------
# Anthropic provider
# ----------------------------------------------------------------------
def test_anthropic_provider_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "key"
        body = json.loads(request.content)
        assert body["system"]
        return httpx.Response(
            200,
            json={
                "model": "claude-3-5-sonnet-latest",
                "content": [{"type": "text", "text": "claude says hi"}],
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "stop_reason": "end_turn",
            },
        )

    provider = AnthropicProvider(
        "anthropic",
        "claude-3-5-sonnet-latest",
        "https://api.anthropic.com",
        api_key="key",
        client=_client(handler),
    )
    completion = provider.complete(_request(schema=JsonSchema(name="x", schema={"type": "object"})))
    assert completion.text == "claude says hi"
    assert completion.prompt_tokens == 100


def test_anthropic_provider_errors() -> None:
    provider = AnthropicProvider(
        "anthropic",
        "claude",
        "https://api.anthropic.com",
        api_key="k",
        client=_client(lambda request: httpx.Response(500)),
    )
    with pytest.raises(TransientProviderError):
        provider.complete(_request())


# ----------------------------------------------------------------------
# Pricing
# ----------------------------------------------------------------------
def test_pricing() -> None:
    assert estimate_cost("gpt-4o-mini", 1_000_000, 0) == pytest.approx(0.15)
    assert estimate_cost("unknown-model", 1_000_000, 1_000_000) == 0.0
    assert is_priced("gpt-4o-mini")
    assert not is_priced("totally-unknown")


# ----------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------
class _ScriptedProvider:
    def __init__(self, name: str, failures: int = 0, *, kind: str = "openai") -> None:
        self.name = name
        self.model = f"{name}-model"
        self.kind = kind
        self.calls = 0
        self._failures = failures

    def complete(self, request: CompletionRequest) -> Completion:
        self.calls += 1
        if self._failures > 0:
            self._failures -= 1
            raise TransientProviderError(f"{self.name} failed")
        return Completion(
            text="ok",
            provider=self.name,
            model=self.model,
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.01,
        )


class _BrokenProvider:
    name = "broken"
    model = "broken"
    kind = "openai"

    def complete(self, request: CompletionRequest) -> Completion:
        raise ProviderError("permanent failure")


def test_router_retries_then_succeeds() -> None:
    provider = _ScriptedProvider("primary", failures=1)
    router = ModelRouter({"primary": provider}, ["primary"], max_retries=2, sleep=lambda _: None)
    completion = router.complete(_request())
    assert completion.text == "ok"
    assert provider.calls == 2
    assert router.ledger.snapshot().calls == 1


def test_router_falls_back() -> None:
    broken = _BrokenProvider()
    backup = _ScriptedProvider("backup")
    router = ModelRouter(
        {"broken": broken, "backup": backup}, ["broken", "backup"], sleep=lambda _: None
    )
    completion = router.complete(_request())
    assert completion.provider == "backup"


def test_router_raises_when_everything_fails() -> None:
    router = ModelRouter({"broken": _BrokenProvider()}, ["broken"], sleep=lambda _: None)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        router.complete(_request())
    assert "broken" in (excinfo.value.hint or "")


def test_router_circuit_breaker_opens() -> None:
    broken = _BrokenProvider()
    breaker = CircuitBreaker(threshold=2, cooldown=60.0, clock=lambda: 100.0)
    router = ModelRouter(
        {"broken": broken, "backup": _ScriptedProvider("backup")},
        ["broken", "backup"],
        breaker=breaker,
        sleep=lambda _: None,
    )
    router.complete(_request())
    router.complete(_request())
    assert breaker.state().get("broken", 0) >= 2
    assert breaker.is_open("broken")
    completion = router.complete(_request())
    assert completion.provider == "backup"


def test_router_budget_exceeded() -> None:
    ledger = UsageLedger(max_cost_usd=0.005)
    provider = _ScriptedProvider("primary")
    router = ModelRouter({"primary": provider}, ["primary"], ledger)
    with pytest.raises(BudgetExceededError):
        router.complete(_request())
    assert provider.calls == 1


def test_usage_ledger_accumulates() -> None:
    ledger = UsageLedger()
    ledger.record(
        Completion(text="a", provider="p", model="m", prompt_tokens=10, completion_tokens=5)
    )
    ledger.record(
        Completion(
            text="b", provider="p", model="m", prompt_tokens=10, completion_tokens=5, cost_usd=0.5
        )
    )
    usage = ledger.snapshot()
    assert usage.calls == 2
    assert usage.total_tokens == 30
    assert usage.cost_usd == pytest.approx(0.5)
    assert not ledger.exhausted


def test_router_requires_a_provider() -> None:
    with pytest.raises(ProviderUnavailableError):
        ModelRouter({}, ["missing"])
