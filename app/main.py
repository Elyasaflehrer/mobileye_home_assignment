"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

# Load .env into os.environ before importing app.config, which reads env vars
# at import time.
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Query
from pydantic import BeforeValidator
from pydantic_core import PydanticCustomError

from app import config, errors, reports
from app.gitlab_client import GitLabClient, set_default_client

config.setup_logging()
logger = logging.getLogger(__name__)
logger.info("Starting service, gitlab_url=%s", config.GITLAB_URL)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the GitLab client at startup; close it at shutdown.

    The client is installed as the process-wide default so that
    :mod:`app.reports` can reach it through :func:`get_default_client`
    while keeping its public function signatures aligned with the spec.
    """
    client = GitLabClient(config.GITLAB_API_BASE, config.GITLAB_TOKEN)
    set_default_client(client)
    logger.info("GitLab client initialized")
    try:
        yield
    finally:
        await client.aclose()
        logger.info("GitLab client closed")


app = FastAPI(title="GitLab Yearly Report Service", lifespan=lifespan)
errors.register(app)


def _parse_year(v: object) -> int:
    """Accept only a 4-digit calendar year, as int or string."""
    s = str(v).strip()
    if not s.isdigit() or len(s) != 4:
        raise PydanticCustomError("year_format", "must be a 4-digit year (YYYY)")
    return int(s)


YearParam = Annotated[
    int,
    BeforeValidator(_parse_year),
    Query(description="Four-digit calendar year (YYYY), e.g. 2025"),
]
ProjectParam = Annotated[
    str | None,
    Query(description="GitLab project ID or URL-encoded full path, e.g. mygroup%2Fproj"),
]


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe.

    Returns:
        Fixed payload ``{"status": "ok"}``. Performs no external calls;
        success means only that the process is alive and reachable.
    """
    return {"status": "ok"}


@app.get("/issues")
async def issues(year: YearParam, project: ProjectParam = None) -> list[dict]:
    """Return every GitLab issue created during *year*.

    Args:
        year: Four-digit calendar year. Missing or invalid values return 400.
        project: Optional project ID or full path. Omit to query the whole
            instance (subject to the token's permissions).

    Returns:
        Bare JSON array of GitLab issue dicts, exactly as returned by GitLab.
    """
    return await reports.get_issues_by_year(year, project)


@app.get("/merge-requests")
async def merge_requests(year: YearParam, project: ProjectParam = None) -> list[dict]:
    """Return every GitLab merge request created during *year*.

    Same arguments, behavior, and error responses as :func:`issues`,
    but queries the merge-request endpoint.
    """
    return await reports.get_merge_requests_by_year(year, project)
