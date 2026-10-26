"""Domain errors raised across DraftProof.

Every error carries a stable ``code`` so the HTTP layer and the CLI can present
consistent messages without inspecting exception types.
"""

from __future__ import annotations


class DraftProofError(Exception):
    """Base class for every error raised by DraftProof."""

    code = "draftproof_error"
    http_status = 500

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        return payload


class ConfigurationError(DraftProofError):
    """A required setting is missing or invalid."""

    code = "configuration_error"
    http_status = 500


class RunNotFoundError(DraftProofError):
    """The requested run does not exist."""

    code = "run_not_found"
    http_status = 404


class ConflictError(DraftProofError):
    """The requested transition is not valid for the current run state."""

    code = "conflict"
    http_status = 409


class UnauthorizedError(DraftProofError):
    """The caller did not present a valid API key."""

    code = "unauthorized"
    http_status = 401


class RateLimitedError(DraftProofError):
    """The caller exceeded the configured request budget."""

    code = "rate_limited"
    http_status = 429


class ProviderError(DraftProofError):
    """A model provider returned an error."""

    code = "provider_error"
    http_status = 502


class TransientProviderError(ProviderError):
    """A provider error that may succeed when retried."""

    code = "provider_transient"


class ProviderUnavailableError(ProviderError):
    """No provider in the chain is currently usable."""

    code = "provider_unavailable"


class BudgetExceededError(DraftProofError):
    """The run exceeded its configured cost budget."""

    code = "budget_exceeded"
    http_status = 402


class InvalidModelOutputError(DraftProofError):
    """A model response could not be validated against the expected schema."""

    code = "invalid_model_output"
    http_status = 502

    def __init__(
        self, message: str, *, task: str | None = None, snippet: str | None = None
    ) -> None:
        super().__init__(message)
        self.task = task
        self.snippet = snippet


class UnsafeURLError(DraftProofError):
    """A URL failed the outbound request safety policy."""

    code = "unsafe_url"


class StorageError(DraftProofError):
    """The storage layer could not complete an operation."""

    code = "storage_error"


class CancelledError(DraftProofError):
    """The run was cancelled by a caller."""

    code = "cancelled"
    http_status = 409
