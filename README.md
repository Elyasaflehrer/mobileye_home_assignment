# GitLab Yearly Report Service

Returns GitLab issues and merge requests created in a given year, scoped
to a single project or to the whole instance.

## Requirements

- Python 3.12+
- A GitLab personal or project access token with `read_api` scope

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

| Variable | Required | Description |
|---|---|---|
| `GITLAB_URL` | yes | Base URL of any GitLab v4 instance, e.g. `https://gitlab.com` |
| `GITLAB_TOKEN` | yes | Access token with `read_api` scope |
| `LOG_LEVEL` | no | Standard Python logging level; defaults to `INFO` |

Copy `.env.example` to `.env` and fill in real values — the service loads it
on startup. A missing required variable causes a clear startup failure
(single-line FATAL message on stderr, non-zero exit).

## Run

```bash
uvicorn app.main:app --port 8080
```

Interactive OpenAPI docs at `http://localhost:8080/docs`.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Liveness probe; returns `{"status":"ok"}` |
| `GET` | `/issues?year=YYYY[&project=…]` | Issues created in *year* |
| `GET` | `/merge-requests?year=YYYY[&project=…]` | Merge requests created in *year* |

The `project` query parameter is optional. Accepts either a numeric ID
(`project=42`) or a full path (`project=mygroup%2Fmyproj` — URL-encoded
recommended but a literal `/` is also tolerated). Omit it to query the whole
instance, limited by the token's permissions.

Response bodies are the JSON arrays returned by GitLab, passed through verbatim.

### Examples

```bash
curl http://localhost:8080/health

# Issues from a project, by path
curl 'http://localhost:8080/issues?year=2025&project=mygroup%2Fmyproj'

# Merge requests from a project, by numeric ID
curl 'http://localhost:8080/merge-requests?year=2025&project=42'

# Whole instance — may be slow or 502 against gitlab.com (see Notes)
curl 'http://localhost:8080/issues?year=2025'
```

## Error responses

| Scenario | Status |
|---|---|
| Missing `year` | 400 |
| Invalid `year` (not a 4-digit value, YYYY) | 400 |
| GitLab returned 401 (authentication failed) | 401 |
| GitLab returned 403 (permission denied) | 403 |
| GitLab returned 404 (project not found) | 404 |
| Upstream failure (429, 5xx, network, timeout) | 502 |

All error bodies use FastAPI's default shape: `{"detail": "<message>"}`.
