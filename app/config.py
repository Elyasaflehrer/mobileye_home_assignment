"""Configuration: env vars (fail-fast at import) and logging setup."""

import logging
import logging.config
import os
import sys


def _require(name: str) -> str:
    """Read a required environment variable.

    Args:
        name: The variable to look up.

    Returns:
        The variable's value (guaranteed non-empty).

    Raises:
        SystemExit: With exit code 2 if the variable is unset or empty. A
            single-line ``FATAL: ...`` message is written to ``stderr`` first
            so the cause is visible without parsing a traceback.
    """
    value = os.environ.get(name)
    if not value:
        sys.stderr.write(
            f"FATAL: required environment variable '{name}' is not set\n"
        )
        raise SystemExit(2)
    return value


GITLAB_URL: str = _require("GITLAB_URL").rstrip("/")
GITLAB_TOKEN: str = _require("GITLAB_TOKEN")

LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()
GITLAB_API_BASE: str = f"{GITLAB_URL}/api/v4"


def setup_logging() -> None:
    """Configure the root logger: plain-text format, ``stdout``, level from ``LOG_LEVEL``.

    Idempotent — safe to call more than once, though it should be called
    exactly once near the top of ``app.main`` before the FastAPI app is built.
    """
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s %(levelname)s %(name)s — %(message)s",
            },
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
            },
        },
        "root": {
            "level": LOG_LEVEL,
            "handlers": ["stdout"],
        },
    })
