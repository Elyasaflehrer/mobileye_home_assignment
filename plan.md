# Plan — Mobileye DevOps-IT Home Assignment

Design notes for the GitLab Yearly Report Service. Strictly the spec; the
MCP server is the implemented bonus.

---

## 1. Contract

**Functions** (spec-mandated signatures, kept literal)
- `get_issues_by_year(year, project_id_or_path=None)`
- `get_merge_requests_by_year(year, project_id_or_path=None)`

Omit `project_id_or_path` → whole-instance scope; otherwise single project.

**HTTP endpoints** (port 8080)

| Method | Path |
|---|---|
| GET | `/health` → `200 {"status":"ok"}` |
| GET | `/issues?year=YYYY[&project=…]` |
| GET | `/merge-requests?year=YYYY[&project=…]` |

**Env vars**
- `GITLAB_URL` (required)
- `GITLAB_TOKEN` (required; missing → fail-fast at startup)
- `LOG_LEVEL` (optional, default `INFO`)

**Error mapping** (body = FastAPI default `{"detail": "…"}`)

| Scenario | Status |
|---|---|
| Missing `year` | 400 |
| Invalid `year` (not 4-digit) | 400 |
| GitLab 404 (project not found) | 404 |
| GitLab 401 (auth) | 401 |
| GitLab 403 (perms) | 403 |
| GitLab 429 / 5xx / network / timeout | 502 |

---

## 2. Decisions (locked)

1. **Stack:** Python + FastAPI + httpx + uvicorn. Stdlib `os.getenv` for config.
   *Why:* FastAPI gives free 400 via pydantic; httpx pairs with FastAPI's async model; three env vars don't warrant a config library.

2. **URL-agnostic.** Any GitLab v4 instance, host/version supplied at runtime.
   *Why:* spec requires `GITLAB_URL` as env var and offers a local GitLab container as one test target — no host is hardcoded.

3. **Response shape:** bare GitLab JSON array, verbatim.
   *Why:* most literal reading of "returns issues from…"; no invented wrappers or curated fields.

4. **Runtime:** single uvicorn worker, no `--reload`, non-root in Docker.
   *Why:* simplest topology for a small read-only service; container hygiene.

5. **Mid-pagination failure → fail the whole request,** no partial data.
   *Why:* silent partial responses carry no completion signal; a clean error lets the caller retry deliberately.

6. **Async end-to-end.** `async def` in routes, `reports.py`, `gitlab_client.py`. `httpx.AsyncClient`.
   *Why:* FastAPI is async-native; one concurrency model; async httpx fits `Link`-header pagination without parking a thread.

7. **`class GitLabClient`** owns the `httpx.AsyncClient`, base URL, auth header, pagination, and status → exception mapping.
   *Why:* encapsulates session and shared headers; gives lifespan a clear `__init__` / `aclose` pair; avoids module-level globals for the HTTP session.

8. **Client lifecycle:** lifespan creates one `GitLabClient` on startup, calls `aclose()` on shutdown. Exposed via a module-level singleton (`set_default_client` / `get_default_client`) so `reports.py` signatures match the spec.
   *Why:* the spec freezes `reports.py`'s signature — no client param allowed. The singleton lets `reports.py` reach the client without altering it.

9. **Centralized `errors.py`:** exception classes, status mapping, FastAPI handlers (including `RequestValidationError → 400`). `errors.register(app)` from `main.py`.
   *Why:* graded error table — one file containing the full mapping is easy to verify.

---

## 3. Architecture

```
FastAPI routes (main.py)   ← thin: validation + status mapping
        ↓
reports.py                  ← get_*_by_year (no transport coupling)
        ↓
gitlab_client.py            ← auth, URL build, pagination, error mapping
        ↓
GitLab v4
```

**Rule:** `reports.py` knows nothing about FastAPI. Routes are adapters. This is what makes the MCP bonus a separate transport rather than a code rewrite.

---

## 4. File layout

```
app/
  __init__.py
  main.py             # FastAPI app, lifespan, 3 routes, errors.register(app)
  config.py           # env loading, fail-fast, logging.dictConfig
  gitlab_client.py    # class GitLabClient (async), pagination, default-client singleton
  reports.py          # async get_issues_by_year, async get_merge_requests_by_year
  errors.py           # exception classes + status mapping + handlers + register()
  validators.py       # parse_year, shared input validators
mcp_server/
  __init__.py
  __main__.py         # `from mcp_server.server import mcp; mcp.run()`
  server.py           # FastMCP app, helpers, two @mcp.tool() functions
Dockerfile
.dockerignore
README.md
test.md
requirements.txt
.env.example
```

---

## 5. GitLab integration rules

- **Endpoints**
  - Project: `/api/v4/projects/{id|encoded_path}/{issues|merge_requests}`
  - Instance: `/api/v4/{issues|merge_requests}?scope=all`
- **`GITLAB_URL`** — strip trailing `/` once at startup.
- **Auth** — `PRIVATE-TOKEN: <token>` header, never in URL.
- **Project identifier** — `urllib.parse.quote(value, safe="")` once at the boundary; same path handles int ID and `group/proj`.
- **State filter** — none. GitLab defaults to all states.
- **Year filter (UTC)** — `created_after=YYYY-01-01T00:00:00Z`, `created_before=(YYYY+1)-01-01T00:00:00Z`.
- **Pagination** — request `pagination=keyset&order_by=created_at&sort=asc&per_page=100`; follow `Link: rel=next` until absent (works for keyset or offset).
- **Timeouts** — 30s per request, no retries.
- **Token never logged.**

---

## 6. Dockerfile

- Base `python:3.12-slim`
- Non-root user
- `EXPOSE 8080`
- `CMD` uvicorn `app.main:app` on `0.0.0.0:8080`, single worker
- `.dockerignore` excludes `.git/`, `__pycache__/`, `.venv/`, IDE files, secrets, docs
- Single-stage; `HEALTHCHECK` via `python -c "urllib.request..."` (no curl in slim image)

---

## 7. Logging

- Stdlib `logging`. Plain text. Configured once at process start. Level from `LOG_LEVEL`.
- **FastAPI** logs to stdout; **MCP server** logs to stderr (MCP stdio uses stdout for JSON-RPC).
- **Never log the token.**
- INFO — startup line (URL only); GitLab call summary (endpoint, year, project, pages, items, duration).
- WARNING — upstream non-2xx before status mapping; implausible-year hints.
- ERROR — unexpected exceptions via `logger.exception(...)`; config failures at startup.
- DEBUG — per-page pagination calls.

---

## 8. Testing

- Primary: manual `curl` and inspector smoke tests — see `test.md`.
- Deferred: pytest + `respx` for `reports.py`; one test per row of the error table.

---

## 9. MCP server (bonus)

Exposes the two reporting functions as MCP tools over the stdio transport.
Built as a fully separate package (`mcp_server/`) with **no shared imports
from `app/`** — the FastAPI service is the graded deliverable; touching it
for ungraded gain is the wrong risk.

### Locked decisions

1. **Separate package, duplicated GitLab logic.**
   *Why:* zero regression risk to the FastAPI service. ~50 lines of intentional duplication.

2. **SDK:** `mcp[cli]` (Anthropic's official Python SDK), `FastMCP` decorator API.
   *Why:* matches FastAPI's ergonomics; the `[cli]` extra ships the inspector so reviewers can test without configuring a separate MCP client.

3. **Transport:** stdio only.
   *Why:* universal local-MCP transport (Claude Desktop, Claude Code, `mcp dev`). HTTP/SSE is for remote MCP.

4. **Entrypoint:** `python -m mcp_server` via `__main__.py`.
   *Why:* canonical Python convention for runnable packages; shortest invocation in client configs.

5. **Logging:** stderr only via `logging.basicConfig`.
   *Why:* MCP stdio uses **stdout** for JSON-RPC framing; stdout logs corrupt the protocol.

6. **HTTP client:** per-request `httpx.AsyncClient` via `async with`.
   *Why:* avoids long-lived-client lifecycle ceremony. ~50ms TLS handshake per call — negligible for interactive use.

7. **Tool functions** match the spec contract verbatim (`get_issues_by_year`, `get_merge_requests_by_year`) and are thin wrappers around `_list`. Google-style docstrings; FastMCP parses `Args:` into per-parameter descriptions in the input schema. `ValueError` and `httpx.HTTPStatusError` propagate — FastMCP wraps them as JSON-RPC errors.

### Verification

`mcp dev mcp_server/server.py` opens the inspector. Both tools appear; calling them returns the raw GitLab JSON array (same shape as the HTTP routes). See README.md "MCP server (bonus)" for the user-facing walkthrough.
