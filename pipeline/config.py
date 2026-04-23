"""Single source of truth for env vars + repo-relative paths.

All pipeline modules that need to read ``.env.local`` or touch state files
at ``<repo>/.pipeline/`` should go through this module. Consolidates the
three formerly-duplicated ``.env.local`` loaders (``pipeline.db``,
``pipeline.sources._http``, ``pipeline.rerank.cohere``) into a single
idempotent implementation, and eliminates hardcoded absolute paths so the
repo is portable between checkouts.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# Anchor every path on the repo root (two levels above this file:
# pipeline/config.py -> pipeline/ -> <repo-root>/). This keeps the package
# portable: no developer's home-directory path appears in source.
REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env.local"
PIPELINE_STATE_DIR = REPO_ROOT / ".pipeline"  # ensured-exists at runtime


def load_env_once() -> None:
    """Idempotently load ``.env.local`` into ``os.environ``.

    Never overrides an env var already present in the process environment —
    so callers can still win over the file (CI sets vars via the real
    environment, local dev sets them via ``.env.local``).
    """
    if getattr(load_env_once, "_loaded", False):
        return
    if ENV_PATH.exists():
        try:
            text = ENV_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("could not read %s: %s", ENV_PATH, exc)
            text = ""
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    load_env_once._loaded = True  # type: ignore[attr-defined]


def require_env(name: str) -> str:
    """Return ``os.environ[name]`` or raise a helpful RuntimeError."""
    load_env_once()
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"{name} not set. Add to {ENV_PATH} or export it.")
    return val


def optional_env(name: str, default: str | None = None) -> str | None:
    """Return ``os.environ.get(name, default)`` after ensuring env is loaded."""
    load_env_once()
    return os.environ.get(name, default)


def state_file(name: str) -> Path:
    """Return a path under ``<repo>/.pipeline/``, creating the dir if needed."""
    PIPELINE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return PIPELINE_STATE_DIR / name


__all__ = [
    "REPO_ROOT",
    "ENV_PATH",
    "PIPELINE_STATE_DIR",
    "load_env_once",
    "require_env",
    "optional_env",
    "state_file",
]
