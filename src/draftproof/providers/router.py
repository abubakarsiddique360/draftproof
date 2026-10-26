"""Resilient model routing.

The router owns retries, exponential backoff, a per-provider circuit breaker
and the run-level cost ledger, so the pipeline never has to think about
provider reliability.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable, Mapping, Sequence

from draftproof.domain.errors import (
    BudgetExceededError,
    ProviderError,
    ProviderUnavailableError,
    TransientProviderError,
)
from draftproof.domain.models import Usage
from draftproof.providers.base import Completion, CompletionRequest, Provider

logger = logging.getLogger(__name__)


class UsageLedger:
    """Thread-safe usage and cost accumulator with a hard budget ceiling."""

    def __init__(self, max_cost_usd: float = 0.0) -> None:
        self.max_cost_usd = max(0.0, max_cost_usd)
        self._lock = threading.Lock()
        self._usage = Usage()

    def record(self, completion: Completion) -> Usage:
        with self._lock:
            self._usage = self._usage + Usage(
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                calls=1,
                cost_usd=completion.cost_usd,
            )
            return self._usage.model_copy()

    def snapshot(self) -> Usage:
        with self._lock:
            return self._usage.model_copy()

    @property
    def exhausted(self) -> bool:
        if self.max_cost_usd <= 0:
            return False
        return self.snapshot().cost_usd >= self.max_cost_usd

    def check(self) -> None:
        """Raise when the configured cost budget has been consumed."""
        if self.exhausted:
            usage = self.snapshot()
            raise BudgetExceededError(
                f"Run budget exhausted: ${usage.cost_usd:.4f} of ${self.max_cost_usd:.2f} used",
                hint="Raise DRAFTPROOF_MAX_COST_USD or lower the requested article length.",
            )


class CircuitBreaker:
    """Open a provider circuit after repeated failures and probe it later."""

    def __init__(
        self,
        *,
        threshold: int = 3,
        cooldown: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = max(1, threshold)
        self._cooldown = max(0.0, cooldown)
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def is_open(self, provider: str) -> bool:
        with self._lock:
            opened_at = self._opened_at.get(provider)
            if opened_at is None:
                return False
            if self._clock() - opened_at >= self._cooldown:
                self._opened_at.pop(provider, None)
                self._failures[provider] = 0
                return False
            return True

    def record_success(self, provider: str) -> None:
        with self._lock:
            self._failures[provider] = 0
            self._opened_at.pop(provider, None)

    def record_failure(self, provider: str) -> None:
        with self._lock:
            failures = self._failures.get(provider, 0) + 1
            self._failures[provider] = failures
            if failures >= self._threshold:
                self._opened_at[provider] = self._clock()

    def state(self) -> dict[str, int]:
        with self._lock:
            return dict(self._failures)


class ModelRouter:
    """Route completion requests across a resilient provider chain."""

    def __init__(
        self,
        providers: Mapping[str, Provider],
        chain: Sequence[str],
        ledger: UsageLedger | None = None,
        *,
        max_retries: int = 2,
        breaker: CircuitBreaker | None = None,
        task_chains: Mapping[str, Sequence[str]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._providers = dict(providers)
        self._chain = [name for name in chain if name in self._providers]
        if not self._chain:
            raise ProviderUnavailableError(
                "No usable provider is configured",
                hint="Set DRAFTPROOF_PROVIDER=mock to run fully offline.",
            )
        self.ledger = ledger or UsageLedger()
        self._max_retries = max(0, max_retries)
        self._breaker = breaker or CircuitBreaker()
        self._task_chains = {key: list(value) for key, value in (task_chains or {}).items()}
        self._sleep = sleep
        self._rng = rng or random.Random(0)

    @property
    def chain(self) -> list[str]:
        return list(self._chain)

    @property
    def providers(self) -> Mapping[str, Provider]:
        return dict(self._providers)

    def _chain_for(self, task: str) -> list[str]:
        preferred = self._task_chains.get(task)
        if not preferred:
            return self._chain
        resolved = [name for name in preferred if name in self._providers]
        return resolved or self._chain

    def complete(self, request: CompletionRequest) -> Completion:
        """Execute a request, retrying transient failures and falling back."""
        self.ledger.check()
        failures: list[str] = []
        for provider_name in self._chain_for(request.task):
            provider = self._providers[provider_name]
            if self._breaker.is_open(provider_name):
                failures.append(f"{provider_name}: circuit open")
                continue
            for attempt in range(self._max_retries + 1):
                try:
                    completion = provider.complete(request)
                except TransientProviderError as exc:
                    self._breaker.record_failure(provider_name)
                    failures.append(f"{provider_name}: {exc.message}")
                    if attempt < self._max_retries:
                        delay = min(4.0, 0.25 * (2**attempt)) + self._rng.uniform(0.0, 0.1)
                        logger.info(
                            "Retrying %s after %.2fs (%s)", provider_name, delay, exc.message
                        )
                        self._sleep(delay)
                        continue
                    break
                except ProviderError as exc:
                    self._breaker.record_failure(provider_name)
                    failures.append(f"{provider_name}: {exc.message}")
                    break
                except Exception as exc:
                    self._breaker.record_failure(provider_name)
                    failures.append(f"{provider_name}: unexpected error: {exc}")
                    logger.exception("Unexpected provider failure")
                    break
                else:
                    self._breaker.record_success(provider_name)
                    self.ledger.record(completion)
                    self.ledger.check()
                    return completion

        raise ProviderUnavailableError(
            "Every configured provider failed for task '" + request.task + "'",
            hint="; ".join(failures[-4:]) or "Check provider credentials and connectivity.",
        )
