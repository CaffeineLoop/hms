"""Domain errors raised by services and translated to HTTP responses in app/api/errors.py.

Services never import FastAPI; they raise these and the API layer decides the status code.
"""


class DomainError(Exception):
    """Base class for expected, client-facing business errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    """The requested resource does not exist (HTTP 404)."""


class ConflictError(DomainError):
    """The request conflicts with the current state of the data (HTTP 409)."""


class BusinessValidationError(DomainError):
    """The request is well-formed but violates a business rule (HTTP 422)."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class AuthenticationError(DomainError):
    """No valid credentials (HTTP 401). The message never says which part was wrong."""


class PermissionDeniedError(DomainError):
    """Authenticated, but not allowed to do this (HTTP 403)."""


class RateLimitedError(DomainError):
    """Too many attempts; retry later (HTTP 429)."""

    def __init__(self, message: str, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
