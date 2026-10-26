"""OpenAI-compatible chat completion provider.

Works with OpenAI, Groq, OpenRouter, Ollama, LM Studio, vLLM and any other
service that implements ``POST /chat/completions``.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from draftproof.domain.errors import ProviderError, TransientProviderError
from draftproof.providers.base import Completion, CompletionRequest
from draftproof.providers.pricing import estimate_cost


class OpenAICompatibleProvider:
    """Chat completions over an OpenAI-compatible HTTP endpoint."""

    kind = "openai"

    def __init__(
        self,
        name: str,
        model: str,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client = client
        self._extra_headers = extra_headers or {}

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self._extra_headers}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _client_or_new(self) -> tuple[httpx.Client, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.Client(timeout=self._timeout), True

    def complete(self, request: CompletionRequest) -> Completion:
        started = time.perf_counter()
        payload = self._payload(request)
        client, owned = self._client_or_new()
        try:
            try:
                response = client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                )
            except httpx.HTTPError as exc:
                raise TransientProviderError(
                    f"{self.name}: transport error: {exc}",
                    hint="Check the base URL, network access and provider status.",
                ) from exc
            if response.status_code == 400 and "response_format" in payload:
                # Some OpenAI-compatible servers reject structured outputs.
                payload.pop("response_format", None)
                response = client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                )
        finally:
            if owned:
                client.close()

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientProviderError(
                f"{self.name}: HTTP {response.status_code}: {_safe_excerpt(response.text)}"
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}: {_safe_excerpt(response.text)}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.name}: response was not JSON") from exc

        text = _extract_text(data)
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return Completion(
            text=text,
            provider=self.name,
            model=str(data.get("model") or self.model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate_cost(self.model, prompt_tokens, completion_tokens),
            latency_ms=latency_ms,
            finish_reason=str(_first_choice(data).get("finish_reason") or "stop"),
        )

    def _payload(self, request: CompletionRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.as_dict() for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.seed is not None:
            payload["seed"] = request.seed
        if request.schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema.name,
                    "schema": request.schema.schema,
                    "strict": False,
                },
            }
        return payload


def _first_choice(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0]
    return {}


def _extract_text(data: dict[str, Any]) -> str:
    choice = _first_choice(data)
    message = choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]
            return "".join(chunks)
    text = choice.get("text")
    if isinstance(text, str):
        return text
    raise ProviderError("openai-compatible provider returned no text content")


def _safe_excerpt(text: str, limit: int = 300) -> str:
    return " ".join(text.split())[:limit]
