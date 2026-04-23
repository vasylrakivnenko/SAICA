"""Shared HTTP helpers for discovery sources.

- `rate_limited_session` returns a `requests.Session` subclass that enforces a
  minimum interval between outbound calls using a simple last-call clock.
- `load_env` reads `/Users/vasyl/saicakg/.env.local` into `os.environ`
  (only keys not already set), so callers can `os.environ[...]` safely.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Optional

import requests

USER_AGENT = "saica-kg-pipeline/0.1 (+https://saica-kg.dev)"
_ENV_PATH = Path("/Users/vasyl/saicakg/.env.local")


def load_env(path: Optional[Path] = None) -> None:
    """Load KEY=VALUE lines from .env.local into os.environ if not already set.

    Idempotent; lines starting with `#` or blank are ignored.
    Values may be optionally wrapped in single or double quotes.
    """
    p = Path(path) if path else _ENV_PATH
    if not p.exists():
        return
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key and key not in os.environ:
            os.environ[key] = val


class _RateLimitedSession(requests.Session):
    def __init__(self, min_interval_s: float, user_agent: str):
        super().__init__()
        self._min_interval = float(min_interval_s)
        self._last_call: float = 0.0
        self._lock = threading.Lock()
        self.headers.update({"User-Agent": user_agent})

    def request(self, method, url, **kwargs):  # type: ignore[override]
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                return super().request(method, url, **kwargs)
            finally:
                self._last_call = time.monotonic()


def rate_limited_session(min_interval_s: float, user_agent: str = USER_AGENT) -> _RateLimitedSession:
    """Return a requests.Session that sleeps to enforce ``min_interval_s`` between calls."""
    return _RateLimitedSession(min_interval_s, user_agent)
