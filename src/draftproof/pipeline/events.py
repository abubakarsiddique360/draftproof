"""Event sinks used to stream progress to the API, CLI and tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from draftproof.storage.repository import Repository


@runtime_checkable
class EventSink(Protocol):
    """Receives structured progress events."""

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Record one event."""
        ...


class NullEventSink:
    """Discards events (useful in unit tests)."""

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        return


class RepositoryEventSink:
    """Persists events so SSE clients can replay them."""

    def __init__(self, repo: Repository, run_id: str) -> None:
        self._repo = repo
        self._run_id = run_id

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        self._repo.append_event(self._run_id, event_type, data)


class RecordingEventSink:
    """Keeps events in memory for assertions and CLI rendering."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))

    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.events]


class TeeEventSink:
    """Fan events out to several sinks."""

    def __init__(self, sinks: Sequence[EventSink]) -> None:
        self._sinks = list(sinks)

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        for sink in self._sinks:
            sink.emit(event_type, data)
