# Plan — Mobileye DevOps-IT Home Assignment

Planning doc. Strictly the spec — no extra functionality. MCP server is bonus.

---

## 1. Contract

**Functions**
- `get_issues_by_year(year, project_id_or_path=None)`
- `get_merge_requests_by_year(year, project_id_or_path=None)`

If `project_id_or_path` is omitted → whole-instance scope; otherwise single project.

**HTTP endpoints (port 8080)**
| Method | Path |
|---|---|
| GET | `/health` → `200 {"status":"ok"}` |
| GET | `/issues?year=YYYY[&project=…]` |
| GET | `/merge-requests?year=YYYY[&project=…]` |

**Env vars**
- `GITLAB_URL` (required)
- `GITLAB_TOKEN` (required) — missing → fail-fast at startup
- `LOG_LEVEL` (optional, default `INFO`)

**Error mapping** (response body = FastAPI default `{"detail": "…"}`)
| Scenario | Status |
|---|---|
| Missing `year` | 400 |
| Invalid `year` (not 4-digit int 1000–9999) | 400 |
| GitLab 404 (project not found) | 404 |
| GitLab 401 (auth) | 401 |
| GitLab 403 (perms) | 403 |
| GitLab 429 / 5xx / network / timeout | 502 |

---

## 2. Decisions

**Locked**

1. **Stack:** Python + FastAPI + httpx + uvicorn. Stdlib `os.getenv` for config.
   *Why:* FastAPI gives free 400 on invalid query params via pydantic; httpx pairs naturally with FastAPI's async model; `os.getenv` is sufficient for 3 env vars without pulling in a config library.

2. **URL-agnostic** — any GitLab v4 instance, host/version supplied at runtime.
   *Why:* the spec requires the service to accept `GITLAB_URL` as an env var and the appendix offers a local GitLab 18.10 container as one of several test targets — so the code can't assume gitlab.com, a self-hosted host, or any specific GitLab version.

3. **Response shape:** bare GitLab JSON array, verbatim.
   *Why:* most literal reading of "returns issues from…"; zero invention of wrappers or curated fields keeps us strictly inside the spec.

4. **Runtime:** single uvicorn worker, no `--reload`, run as non-root in Docker.
   *Why:* single-process / single-container is the simplest topology for a small read-only service; non-root is standard container hygiene.

5. **Mid-pagination failure** → fail the whole request (no partial data).
   *Why:* silent partial responses carry no signal that they're incomplete; a clean error lets the caller retry deliberately.

6. **Async end-to-end.** `async def` in routes, `reports.py`, `gitlab_client.py`. `httpx.AsyncClient`.
   *Why:* FastAPI is async-native; one concurrency model end-to-end is simpler than mixing sync underneath, and async httpx is the natural fit for following `Link`-header pagination on the event loop without parking a thread.

7. **`class GitLabClient`** owns the `httpx.AsyncClient`, base URL, auth header, pagination, and status → exception mapping.
   *Why:* encapsulates session and shared headers as one cohesive object; gives the lifespan event a clear `__init__` / `aclose` lifecycle and avoids module-level globals for the HTTP session itself.

8. **Client lifecycle:** FastAPI lifespan event creates one `GitLabClient` on startup, calls `aclose()` on shutdown. The instance is exposed via a **module-level singleton** in `gitlab_client.py` (`set_default_client` / `get_default_client`) so `reports.py` function signatures match the spec literally.
   *Why:* the spec freezes the `reports.py` signature to `(year, project_id_or_path=None)` — no client param allowed; a singleton (set by lifespan, cleared on shutdown) lets `reports.py` reach the client without altering its signature, while lifespan still guarantees `aclose()` runs.

9. **Centralized `errors.py`:** exception classes, exception → status mapping, FastAPI exception handlers (including `RequestValidationError → 400` to override FastAPI's default 422). `errors.register(app)` called from `main.py`.
   *Why:* the spec's error table is graded — one file containing all exception classes, the status mapping, and the handlers gives a reviewer a single place to verify the whole error contract.

**Deferred (build only if time permits)**
- Dockerfile style (single-stage vs multi-stage)
- `HEALTHCHECK` directive (urllib one-liner / install curl / skip)
- Automated tests (pytest + respx)
- MCP server bonus

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

Rule: `reports.py` knows nothing about FastAPI. Routes are adapters. This is also what makes the MCP bonus trivial.

---

## 4. File layout

```
app/
  __init__.py
  main.py             # FastAPI app, lifespan event, 3 routes, errors.register(app)
  config.py           # os.getenv, fail-fast, URL normalize, logging.dictConfig
  gitlab_client.py    # class GitLabClient (async), pagination, module-level singleton
  reports.py          # async get_issues_by_year, async get_merge_requests_by_year
  errors.py           # exception classes + status mapping + FastAPI handlers + register()
Dockerfile
.dockerignore
README.md
requirements.txt
.env.example
```

---

## 5. GitLab integration rules

- **Endpoints**
  - Project: `/api/v4/projects/{id|encoded_path}/{issues|merge_requests}`
  - Instance: `/api/v4/{issues|merge_requests}?scope=all`
- **`GITLAB_URL`**: strip trailing `/` once at startup.
- **Auth**: `PRIVATE-TOKEN: <token>` header — never in URL.
- **Project identifier**: `urllib.parse.quote(value, safe="")` once at the boundary; same path handles int ID and `group/proj`.
- **State filter**: none — GitLab defaults to all states.
- **Year filter (UTC)**: `created_after=YYYY-01-01T00:00:00Z`, `created_before=(YYYY+1)-01-01T00:00:00Z`.
- **Pagination**: request `pagination=keyset&order_by=created_at&sort=asc&per_page=100`; always follow `Link: rel=next` until absent (works for keyset or offset).
- **Timeouts**: 30s per request, no retries.
- **Token never logged.**

---

## 6. Implementation order

1. Skeleton: FastAPI + `/health` + `config.py` (`os.getenv`, fail-fast, URL normalize, `logging.dictConfig`) + Dockerfile → `curl /health` works in the container.
2. `gitlab_client.py`: auth, single GET, paginated GET, status → custom exceptions.
3. `reports.py`: two functions, scope dispatch, year filter.
4. Routes `/issues`, `/merge-requests` — pydantic validates `year`.
5. `errors.py`: exception → HTTP status handlers per the error table.
6. `README.md` per outline in §9.
7. Deferred items in this order: tests → MCP server.

---

## 7. Dockerfile

- Base `python:3.12-slim`
- Non-root user
- `EXPOSE 8080`
- `CMD` uvicorn `app.main:app` on `0.0.0.0:8080`, single worker
- `.dockerignore` excludes `.git/`, `__pycache__/`, `.venv/`, `tests/`
- Multi-stage + `HEALTHCHECK` shape: decided at build time

---

## 8. Logging

- Stdlib `logging`. Plain text. stdout. Configured once via `logging.dictConfig` in `config.py`. Level from `LOG_LEVEL`.
- **Never log the token.**
- INFO: startup line (URL only); GitLab call summary (endpoint, year, project, pages, items, duration).
- WARNING: upstream non-2xx before status mapping.
- ERROR: unexpected exceptions via `logger.exception(...)`; config failures at startup.
- DEBUG: per-page pagination calls.

---

## 9. README outline

1. One-line description
2. Requirements (Docker, GitLab token with `read_api`)
3. Quick start: `docker build`, `docker run` with env vars
4. Env-var table
5. Endpoint list
6. `curl` example per endpoint
7. Error-response table
8. Notes (UTC year boundary, all states included, instance-wide can be large)
9. (If built) test / MCP run instructions

---

## 10. Testing

- Primary: manual `curl` smoke tests against a real GitLab.
- Deferred: pytest + `respx` for `reports.py`; one test per row of the error table.
