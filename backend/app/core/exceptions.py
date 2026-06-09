"""Domain exceptions.

The service and repository layers raise these — they carry an HTTP status and a
safe client-facing detail but know nothing about FastAPI. `app.main` registers a
single handler that turns any `AppError` into a JSON response. This keeps the
service layer free of HTTP/framework coupling (per the three-layer rule).
"""
from __future__ import annotations


class AppError(Exception):
    """Base for all domain errors. Subclasses set status_code and detail."""

    status_code: int = 400
    detail: str = "Application error"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class EmailAlreadyExistsError(AppError):
    status_code = 409
    detail = "An account with this email already exists"


class InvalidCredentialsError(AppError):
    status_code = 401
    detail = "Incorrect email or password"


class InvalidTokenError(AppError):
    status_code = 401
    detail = "Could not validate credentials"


class TokenExpiredError(InvalidTokenError):
    detail = "Token has expired"


class InactiveUserError(AppError):
    status_code = 403
    detail = "User account is inactive"


class NotFoundError(AppError):
    status_code = 404
    detail = "Resource not found"


class PermissionDeniedError(AppError):
    status_code = 403
    detail = "Permission denied"


class ConflictError(AppError):
    status_code = 409
    detail = "Conflict"


class NoAvailableDriverError(AppError):
    status_code = 409
    detail = "No available drivers nearby"


class ValidationError(AppError):
    status_code = 422
    detail = "Validation error"
