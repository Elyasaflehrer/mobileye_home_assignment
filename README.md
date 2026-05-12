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

## MCP server (bonus)

The repository also ships an MCP server (`mcp_server/`) that exposes the same
two reporting functions as MCP tools. The fastest way to verify it works is
the **MCP inspector** — a small web UI that spawns the server as a subprocess
and lets you call its tools interactively.

### Prerequisites

Beyond the project's normal `pip install -r requirements.txt`, one extra install:

```bash
pip install uv
```

`uv` is the Python spawn helper that `mcp dev` uses to launch the server.
The inspector UI itself is a Node.js package that `mcp dev` downloads on
first use via `npx` — requires **Node.js / npm** on your system; you'll be
prompted to confirm the one-time download.

### Run the inspector

Make sure `GITLAB_URL` and `GITLAB_TOKEN` are available — either in `.env`
at the project root or as shell exports.

```bash
mcp dev mcp_server/server.py
```

On first run, `npx` prompts to download the inspector — confirm with `y`.
The terminal then prints a URL (typically `http://localhost:6274`); open it
in your browser. You should see:

- Connection status: **Connected**
- Server name: **`gitlab-yearly-report`**

The server's own log lines appear in the terminal running `mcp dev` (logs
go to stderr — stdout is reserved for the MCP protocol).

### Try a tool

1. In the inspector UI, click **Tools** to see the registered tools.
2. Pick **`get_issues_by_year`** and fill in:
   - `year`: a 4-digit year, e.g. `2025`.
   - `project_id_or_path`: a project path like `mygroup/myproj`, a numeric
     project ID, or leave blank to query the whole instance.
3. Click **Call Tool**. The response panel shows the raw GitLab JSON array.

Meanwhile, the terminal running `mcp dev` logs a summary line like:

```
... INFO mcp_server — GitLab fetch: path=/projects/.../issues pages=1 items=N duration=0.42s
```

`get_merge_requests_by_year` works the same way, with the same parameters.

### Tools provided

| Tool | Parameters | Description |
|---|---|---|
| `get_issues_by_year` | `year: int`, `project_id_or_path: str \| int \| None = None` | GitLab issues created in *year*; optional project scope. |
| `get_merge_requests_by_year` | `year: int`, `project_id_or_path: str \| int \| None = None` | GitLab merge requests created in *year*; optional project scope. |

Same signatures and return shape (raw GitLab JSON array) as the `/issues`
and `/merge-requests` HTTP routes.
