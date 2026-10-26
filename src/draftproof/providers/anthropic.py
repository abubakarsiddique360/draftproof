"""Anthropic Messages API provider."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from draftproof.domain.errors import ProviderError, TransientProviderError
from draftproof.providers.base import Completion, CompletionRequest
from draftproof.providers.pricing import estimate_cost

_API_VERSION = "2023-06-01"


class AnthropicProvider:
    """Claude messages provider using the raw HTTP API over httpx."""

    kind = "anthropic"

    def __init__(
        self,
        name: str,
        model: str,
        base_url: str,
        *,
        api_key: str,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client = client

    def _endpoint(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/messages"
        return f"{self.base_url}/v1/messages"

    def complete(self, request: CompletionRequest) -> Completion:
        started = time.perf_counter()
        payload = self._payload(request)
        client = self._client or httpx.Client(timeout=self._timeout)
        owned = self._client is None
        try:
            try:
                response = client.post(
                    self._endpoint(),
                    json=payload,
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": _API_VERSION,
                        "content-type": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                raise TransientProviderError(f"{self.name}: transport error: {exc}") from exc
        finally:
            if owned:
                client.close()

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientProviderError(f"{self.name}: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}: {' '.join(response.text.split())[:300]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.name}: response was not JSON") from exc

        text = _extract_text(data)
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("output_tokens") or 0)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return Completion(
            text=text,
            provider=self.name,
            model=str(data.get("model") or self.model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate_cost(self.model, prompt_tokens, completion_tokens),
            latency_ms=latency_ms,
            finish_reason=str(data.get("stop_reason") or "stop"),
        )

    def _payload(self, request: CompletionRequest) -> dict[str, Any]:
        system = request.system_prompt()
        if request.schema is not None:
            schema_text = json.dumps(request.schema.schema, ensure_ascii=False)
            system = (
                f"{system}\n\nRespond with a single JSON object that satisfies this JSON schema. "
                "Do not wrap it in Markdown fences and do not add commentary.\n"
                f"Schema name: {request.schema.name}\nSchema: {schema_text}"
            ).strip()
        messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
            if message.role != "system"
        ]
        if not messages:
            messages = [{"role": "user", "content": "Proceed."}]
        return {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": system or "You are a precise technical editor.",
            "messages": messages,
        }


def _extract_text(data: dict[str, Any]) -> str:
    blocks = data.get("content")
    if isinstance(blocks, list):
        chunks = [
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "".join(chunk for chunk in chunks if isinstance(chunk, str))
        if text:
            return text
    raise ProviderError("anthropic provider returned no text content")
