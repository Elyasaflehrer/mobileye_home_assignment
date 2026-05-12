"""Yearly report builders for GitLab issues and merge requests."""

import logging
from datetime import datetime, timezone

from app.gitlab_client import get_default_client

logger = logging.getLogger(__name__)

_GITLAB_FOUNDED = 2011


def _year_window(year: int) -> dict[str, str]:
    """Build the half-open UTC date range for *year*.

    The upper bound is the start of the *next* year, giving a clean
    half-open interval ``[YYYY-01-01T00:00:00Z, (YYYY+1)-01-01T00:00:00Z)``.
    Using a half-open interval keeps the result correct regardless of
    whether GitLab interprets ``created_before`` inclusively or exclusively.

    Args:
        year: Four-digit calendar year (e.g. ``2025``).

    Returns:
        Dict with two ISO 8601 keys — ``created_after`` and ``created_before``
        — both in UTC.
    """
    return {
        "created_after": f"{year}-01-01T00:00:00Z",
        "created_before": f"{year + 1}-01-01T00:00:00Z",
    }


def _warn_implausible_year(year: int) -> bool:
    """Emit a WARNING log line for years that cannot contain GitLab data.

    GitLab was founded in 2011, so any year before that produces an empty
    result. A year past the current UTC year likewise has no data yet.
    Both pass query validation (they're 4-digit years), so this is the
    only place the implausibility is surfaced.
    """
    if year < _GITLAB_FOUNDED:
        logger.warning(
            "year=%d is before GitLab's founding in %d; result will be empty",
            year, _GITLAB_FOUNDED,
        )
        return True
    current = datetime.now(timezone.utc).year
    if year > current:
        logger.warning(
            "year=%d is in the future (current=%d); result will be empty",
            year, current,
        )
        return True
    return False


async def get_issues_by_year(
    year: int, project_id_or_path: str | int | None = None
) -> list[dict]:
    """Return every GitLab issue created during *year*.

    Args:
        year: Four-digit calendar year (e.g. ``2025``).
        project_id_or_path: Project ID (``int``) or full path
            (``"mygroup/proj"``). If ``None``, queries the whole instance
            with ``scope=all``, limited by the token's permissions.

    Returns:
        Flat list of issue dicts across all pages, verbatim from GitLab.

    Raises:
        GitLabAPIError: Any subclass — see :meth:`GitLabClient.list_issues`.
    """
    if _warn_implausible_year(year):
        return []
    return await get_default_client().list_issues(
        project=project_id_or_path, **_year_window(year),
    )


async def get_merge_requests_by_year(
    year: int, project_id_or_path: str | int | None = None
) -> list[dict]:
    """Return every GitLab merge request created during *year*.

    Same arguments, behavior, and exceptions as :func:`get_issues_by_year`,
    but queries the merge-request endpoint instead of the issue endpoint.
    """
    if _warn_implausible_year(year):
        return []
    return await get_default_client().list_merge_requests(
        project=project_id_or_path, **_year_window(year),
    )
