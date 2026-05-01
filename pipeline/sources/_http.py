"""Shared HTTP helpers for discovery sources.

- ``rate_limited_session`` returns a ``requests.Session`` subclass that
  enforces a minimum interval between outbound calls using a simple
  last-call clock.
- ``load_env`` is kept as a thin shim over :func:`pipeline.config.load_env_once`
  for backward compatibility; new code should import from ``pipeline.config``
  directly.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import requests

from pipeline.config import load_env_once

USER_AGENT = "saica-kg-pipeline/0.1 (+https://saica-kg.dev)"


def load_env(path: Optional[Path] = None) -> None:
    """Backward-compatible shim for :func:`pipeline.config.load_env_once`.

    The ``path`` argument is retained only for API compatibility with older
    callers — it is ignored, since the canonical location is
    ``<repo-root>/.env.local``. Use ``pipeline.config.load_env_once()`` in
    new code.
    """
    load_env_once()


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


def rate_limited_session(
    min_interval_s: float, user_agent: str = USER_AGENT
) -> _RateLimitedSession:
    """Return a requests.Session that sleeps to enforce ``min_interval_s`` between calls."""
    return _RateLimitedSession(min_interval_s, user_agent)
