"""MCP server exposing the GitLab yearly-report tools."""

import logging
import os
import sys
import time
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load .env before any os.environ access so .env values are visible.
load_dotenv()


def _require(name: str) -> str:
    """Read a required environment variable, exiting clean if unset."""
    value = os.environ.get(name)
    if not value:
        sys.stderr.write(
            f"FATAL: required environment variable '{name}' is not set\n"
        )
        raise SystemExit(2)
    return value


GITLAB_URL = _require("GITLAB_URL").strip().rstrip("/")
GITLAB_TOKEN = _require("GITLAB_TOKEN")
GITLAB_API_BASE = f"{GITLAB_URL}/api/v4"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# stderr only — stdout is the MCP JSON-RPC channel.
logging.basicConfig(
    stream=sys.stderr,
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("mcp_server")
logger.info("Starting MCP server, gitlab_url=%s", GITLAB_URL)


def _parse_year(v: object) -> int:
    """Validate and parse a 4-digit calendar year (YYYY)."""
    s = str(v).strip()
    if not s.isdigit() or len(s) != 4:
        raise ValueError("year must be a 4-digit value (YYYY)")
    return int(s)


def _year_window(year: int) -> dict[str, str]:
    """Build the half-open UTC date range for *year*."""
    return {
        "created_after": f"{year}-01-01T00:00:00Z",
        "created_before": f"{year + 1}-01-01T00:00:00Z",
    }


def _build_path(resource: str, project: str | int | None) -> str:
    """Construct the path for project- or instance-scoped queries."""
    if project is None:
        return f"/{resource}"
    return f"/projects/{quote(str(project), safe='')}/{resource}"


async def _fetch_all_pages(
    client: httpx.AsyncClient, path: str, params: dict
) -> list[dict]:
    """GET *path* with keyset pagination, following ``Link: rel=next``."""
    full_params = {
        **params,
        "per_page": 100,
        "pagination": "keyset",
        "order_by": "created_at",
        "sort": "asc",
    }
    items: list[dict] = []
    url: str | None = path
    use_params = True
    pages = 0
    t0 = time.monotonic()
    while url:
        pages += 1
        resp = await client.get(url, params=full_params if use_params else None)
        resp.raise_for_status()
        items.extend(resp.json())
        url = resp.links.get("next", {}).get("url")
        use_params = False
    duration = time.monotonic() - t0
    logger.info(
        "GitLab fetch: path=%s pages=%d items=%d duration=%.2fs",
        path, pages, len(items), duration,
    )
    return items


async def _list(
    resource: str,
    year: int,
    project: str | int | None,
) -> list[dict]:
    """Fetch all matching items for one resource (issues or merge_requests)."""
    year = _parse_year(year)
    params = _year_window(year)
    if project is None:
        params["scope"] = "all"
    async with httpx.AsyncClient(
        base_url=GITLAB_API_BASE,
        headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
        timeout=30.0,
    ) as client:
        return await _fetch_all_pages(client, _build_path(resource, project), params)


mcp = FastMCP("gitlab-yearly-report")


@mcp.tool()
async def get_issues_by_year(
    year: int,
    project_id_or_path: str | int | None = None,
) -> list[dict]:
    """Return all GitLab issues created during the given calendar year.

    Args:
        year: 4-digit calendar year, e.g. 2025.
        project_id_or_path: Optional. GitLab project ID (integer) or full
            path string (e.g. "mygroup/myproj"). If omitted, queries the
            whole GitLab instance with scope=all (limited by the access
            token's permissions).

    Returns:
        List of GitLab issue objects, exactly as returned by the REST API.
    """
    return await _list("issues", year, project_id_or_path)


@mcp.tool()
async def get_merge_requests_by_year(
    year: int,
    project_id_or_path: str | int | None = None,
) -> list[dict]:
    """Return all GitLab merge requests created during the given calendar year.

    Args:
        year: 4-digit calendar year, e.g. 2025.
        project_id_or_path: Optional. GitLab project ID (integer) or full
            path string (e.g. "mygroup/myproj"). If omitted, queries the
            whole GitLab instance with scope=all (limited by the access
            token's permissions).

    Returns:
        List of GitLab merge request objects, exactly as returned by the REST API.
    """
    return await _list("merge_requests", year, project_id_or_path)
