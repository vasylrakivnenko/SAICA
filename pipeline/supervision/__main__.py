"""Entrypoint so ``python -m pipeline.supervision`` invokes the CLI."""

from __future__ import annotations

from pipeline.supervision.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
