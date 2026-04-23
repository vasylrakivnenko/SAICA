"""One-shot structured-logging setup for pipeline CLIs and modules.

Module-level code should do ``log = logging.getLogger(__name__)`` and emit
through that logger. CLI entry points call :func:`configure_logging` at the
top of ``main()`` exactly once; subsequent calls only adjust the level.

Level precedence: explicit ``level=`` argument > ``SAICA_LOG_LEVEL`` env
var > ``"INFO"``.
"""

from __future__ import annotations

import logging
import os
import sys


def configure_logging(level: str | None = None) -> None:
    """One-shot logger setup. Safe to call multiple times."""
    lvl = (level or os.environ.get("SAICA_LOG_LEVEL") or "INFO").upper()
    root = logging.getLogger()
    if getattr(configure_logging, "_done", False):
        root.setLevel(lvl)
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-5s %(name)s :: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(lvl)
    configure_logging._done = True  # type: ignore[attr-defined]


__all__ = ["configure_logging"]
