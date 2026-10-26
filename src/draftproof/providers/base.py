"""Provider contracts shared by every model backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class Message:
    """A single chat message."""

    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class JsonSchema:
    """A named JSON schema a provider should honour."""

    name: str
    schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    """A fully described model call.

    ``task`` is a stable label (for example ``draft_section``) used for
    routing, metrics and the deterministic offline provider. Real providers
    ignore it.
    """

    messages: tuple[Message, ...]
    task: str = "generic"
    schema: JsonSchema | None = None
    temperature: float = 0.2
    max_tokens: int = 1024
    seed: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def system_prompt(self) -> str:
        return "\n\n".join(m.content for m in self.messages if m.role == "system")

    def user_prompt(self) -> str:
        return "\n\n".join(m.content for m in self.messages if m.role == "user")


@dataclass(frozen=True, slots=True)
class Completion:
    """The normalized result of a model call."""

    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    finish_reason: str = "stop"


@runtime_checkable
class Provider(Protocol):
    """Minimal protocol every model backend implements."""

    name: str
    model: str
    kind: str

    def complete(self, request: CompletionRequest) -> Completion:
        """Execute one completion request."""
        ...
