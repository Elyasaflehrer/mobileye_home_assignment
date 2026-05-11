"""GitLab REST API v4 client: auth, pagination, and status mapping."""

import logging
import time
from urllib.parse import quote

import httpx

from app.errors import (
    GitLabAuthFailed,
    GitLabNotFound,
    GitLabPermissionDenied,
    UpstreamError,
)

logger = logging.getLogger(__name__)


class GitLabClient:
    """Async client for the GitLab REST API v4.

    Owns an :class:`httpx.AsyncClient` configured with the ``PRIVATE-TOKEN``
    header and a 30-second timeout. The public methods
    (:meth:`list_issues`, :meth:`list_merge_requests`) follow GitLab's
    ``Link: rel=next`` pagination header until exhausted, and translate
    non-2xx responses into the exception classes defined in :mod:`app.errors`.

    The instance is constructed once at FastAPI startup and registered as the
    process-wide default via :func:`set_default_client`. :mod:`app.reports`
    reaches it through :func:`get_default_client`, which keeps the public
    ``reports.get_*_by_year`` signatures aligned with the spec.
    """

    def __init__(self, base_url: str, token: str) -> None:
        """Initialize the underlying async HTTP client.

        Args:
            base_url: Fully-qualified API base, e.g.
                ``https://gitlab.example.com/api/v4``. All request paths are
                resolved relative to this.
            token: GitLab personal or project access token with ``read_api``
                scope. Sent as the ``PRIVATE-TOKEN`` header on every request
                — never inserted into URLs.
        """
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"PRIVATE-TOKEN": token},
            timeout=30.0,
        )

    async def aclose(self) -> None:
        """Release the underlying connection pool.

        Invoked from the FastAPI lifespan shutdown hook. Idempotent in
        practice — calling it twice is harmless.
        """
        await self._client.aclose()

    async def list_issues(
        self, project: str | int | None = None, **params
    ) -> list[dict]:
        """Return every GitLab issue matching the given filters.

        Args:
            project: Project ID (``int``) or full path (``"mygroup/proj"``).
                ``None`` queries the whole instance with ``scope=all``,
                limited by the token's permissions.
            **params: Extra query parameters forwarded verbatim to GitLab —
                typically ``created_after`` and ``created_before`` set by
                :mod:`app.reports`.

        Returns:
            Flat list of issue dicts across all pages, exactly as returned
            by GitLab.

        Raises:
            GitLabNotFound: GitLab responded 404.
            GitLabAuthFailed: Token is invalid or missing (401).
            GitLabPermissionDenied: Token lacks required scope (403).
            UpstreamError: Network failure, timeout, 429, or 5xx upstream.
        """
        return await self._paginated_get(
            self._build_path("issues", project),
            self._with_instance_scope(project, params),
        )

    async def list_merge_requests(
        self, project: str | int | None = None, **params
    ) -> list[dict]:
        """Return every GitLab merge request matching the given filters.

        Same arguments, behavior, and exceptions as :meth:`list_issues`.
        """
        return await self._paginated_get(
            self._build_path("merge_requests", project),
            self._with_instance_scope(project, params),
        )

    async def _paginated_get(self, path: str, params: dict) -> list[dict]:
        """GET *path* with keyset pagination, following ``Link: rel=next``.

        Pagination knobs (``per_page=100``, ``pagination=keyset``,
        ``order_by=created_at``, ``sort=asc``) are merged into *params* for
        the first request only. Subsequent requests use the URL embedded in
        the ``Link: rel=next`` header verbatim — that URL already encodes
        all the pagination state, so we must not re-attach parameters.

        Args:
            path: Path relative to ``base_url`` (e.g. ``/issues`` or
                ``/projects/X/issues``).
            params: Caller-supplied query parameters; the pagination defaults
                above are merged into them.

        Returns:
            Flattened list of items across all pages, in the order returned
            by GitLab.

        Raises:
            GitLabAPIError: Any subclass — see :meth:`list_issues` for the
                full set.
        """
        full_params = {
            **params,
            "per_page": 100,
            "pagination": "keyset",
            "order_by": "created_at",
            "sort": "asc",
        }
        items: list[dict] = []
        pages = 0
        url: str | None = path
        use_params = True
        t0 = time.monotonic()
        while url:
            pages += 1
            logger.debug("GET %s (page %d)", url, pages)
            try:
                resp = await self._client.get(
                    url, params=full_params if use_params else None
                )
            except httpx.RequestError as e:
                raise UpstreamError(f"GitLab request failed: {e}") from e
            self._raise_for_status(resp)
            items.extend(resp.json())
            url = resp.links.get("next", {}).get("url")
            use_params = False
        duration = time.monotonic() - t0
        logger.info(
            "GitLab fetch: path=%s pages=%d items=%d duration=%.2fs",
            path, pages, len(items), duration,
        )
        return items

    @staticmethod
    def _build_path(resource: str, project: str | int | None) -> str:
        """Build the path for *resource* in either instance- or project-scope.

        The project identifier is URL-encoded once at the boundary using
        ``quote(value, safe="")`` — integer IDs survive unchanged; full paths
        have their ``/`` characters turned into ``%2F``.

        Args:
            resource: Either ``"issues"`` or ``"merge_requests"``.
            project: Project ID, full path, or ``None`` for instance scope.

        Returns:
            Path relative to ``base_url``.
        """
        if project is None:
            return f"/{resource}"
        encoded = quote(str(project), safe="")
        return f"/projects/{encoded}/{resource}"

    @staticmethod
    def _with_instance_scope(project: object, params: dict) -> dict:
        """Add ``scope=all`` to *params* when there is no project.

        GitLab's instance-wide endpoints default to "items I authored or am
        assigned to"; ``scope=all`` is required to get everything the token
        can read across the instance. Project-scoped endpoints ignore the
        parameter.

        Returns:
            A new dict — never mutates *params* in place.
        """
        if project is None:
            return {**params, "scope": "all"}
        return params

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        """Raise the matching :class:`GitLabAPIError` for a non-2xx response.

        Returns silently for any 2xx status. Otherwise logs the upstream
        status and a short detail snippet at ``WARNING`` before raising:

        - ``401`` → :class:`GitLabAuthFailed`
        - ``403`` → :class:`GitLabPermissionDenied`
        - ``404`` → :class:`GitLabNotFound`
        - anything else (429, 5xx, ...) → :class:`UpstreamError`

        Args:
            resp: The httpx response to inspect.
        """
        if resp.is_success:
            return
        status = resp.status_code
        try:
            body = resp.json()
            detail = body.get("message") or body.get("error") or resp.text[:200]
        except ValueError:
            detail = resp.text[:200]
        logger.warning("GitLab returned %d: %s", status, detail)
        if status == 404:
            raise GitLabNotFound(detail)
        if status == 401:
            raise GitLabAuthFailed(detail)
        if status == 403:
            raise GitLabPermissionDenied(detail)
        raise UpstreamError(f"upstream HTTP {status}: {detail}")


_client: GitLabClient | None = None


def set_default_client(c: GitLabClient) -> None:
    """Install *c* as the process-wide default GitLab client.

    Called from the FastAPI lifespan startup hook. Subsequent calls replace
    the existing default — useful only in tests.
    """
    global _client
    _client = c


def get_default_client() -> GitLabClient:
    """Return the currently-installed default GitLab client.

    Raises:
        RuntimeError: If no default client has been installed — usually
            means lifespan startup has not yet completed.
    """
    if _client is None:
        raise RuntimeError("GitLab client not initialized")
    return _client
