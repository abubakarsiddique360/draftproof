"""Minimal Prometheus-style metrics registry."""

from __future__ import annotations

import threading
from collections import defaultdict


class Metrics:
    """Thread-safe counters exposed in Prometheus text format."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[tuple[tuple[str, str], ...], float]] = defaultdict(dict)
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        key = tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items()))
        with self._lock:
            bucket = self._counters[name]
            bucket[key] = bucket.get(key, 0.0) + value

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def render(self) -> str:
        """Render every metric in the Prometheus text exposition format."""
        lines: list[str] = []
        with self._lock:
            for name, bucket in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                for labels, value in sorted(bucket.items()):
                    if labels:
                        rendered = ",".join(f'{k}="{v}"' for k, v in labels)
                        lines.append(f"{name}{{{rendered}}} {value:g}")
                    else:
                        lines.append(f"{name} {value:g}")
            for name, value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value:g}")
        return "\n".join(lines) + "\n"
