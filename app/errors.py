"""Custom exceptions, status mapping, and FastAPI exception handlers."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class GitLabAPIError(Exception):
    """Base for every GitLab-side failure surfaced to clients.

    Subclasses correspond one-to-one with rows of the assignment's error
    table. Registering a single handler for this base class catches all
    subclasses via polymorphism.
    """


class GitLabNotFound(GitLabAPIError):
    """GitLab returned 404 — project does not exist or is hidden from the token."""


class GitLabAuthFailed(GitLabAPIError):
    """GitLab returned 401 — token is missing, invalid, or expired."""


class GitLabPermissionDenied(GitLabAPIError):
    """GitLab returned 403 — token lacks the scope required for the resource."""


class UpstreamError(GitLabAPIError):
    """Upstream failure not in the spec table: 429, 5xx, network error, or timeout."""


_STATUS: dict[type[GitLabAPIError], int] = {
    GitLabNotFound: 404,
    GitLabAuthFailed: 401,
    GitLabPermissionDenied: 403,
    UpstreamError: 502,
}


async def gitlab_error_handler(
    request: Request, exc: GitLabAPIError
) -> JSONResponse:
    """Translate a :class:`GitLabAPIError` into a JSON response.

    The HTTP status is looked up in ``_STATUS`` by the exception's concrete
    type; an unmapped subclass falls back to ``500`` (defensive — should never
    fire because every subclass is in the table).

    Args:
        request: The originating request (unused; required by FastAPI).
        exc: The raised exception instance.

    Returns:
        ``JSONResponse`` with body ``{"detail": str(exc)}`` and the mapped status.
    """
    return JSONResponse(
        {"detail": str(exc)},
        status_code=_STATUS.get(type(exc), 500),
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Translate a pydantic validation error into ``400 Bad Request``.

    Overrides FastAPI's default ``422 Unprocessable Entity`` so the response
    matches the spec's error contract for missing or malformed ``year``.

    Args:
        request: The originating request (unused; required by FastAPI).
        exc: The validation error raised during request parsing.

    Returns:
        ``JSONResponse`` with body ``{"detail": [...]}`` and status ``400``.
    """
    return JSONResponse({"detail": exc.errors()}, status_code=400)


def register(app: FastAPI) -> None:
    """Wire the GitLab and validation exception handlers onto *app*.

    Called once from :mod:`app.main` immediately after the FastAPI instance
    is constructed.
    """
    app.add_exception_handler(GitLabAPIError, gitlab_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
