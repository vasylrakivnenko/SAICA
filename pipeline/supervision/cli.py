"""CLI wrapper for prevention-event logging.

Designed to be called from:
- ``.pre-commit-config.yaml`` hooks (``invoked-by pre-commit``)
- ``.claude/hooks/log_pretool.sh`` (``invoked-by claude-code-hook``)
- CI workflows (``invoked-by ci``)
- humans on the terminal (``invoked-by manual``)

KG citations (mirrors :mod:`pipeline.supervision.logger`):

- ``data/tools/semgrep.yml`` — primary detection-paradigm supervisor that
  is *escalated* to prevention when it gates pre-commit; failures route
  here.
- ``data/failure_modes/scope_creep.yml`` — Claude Code ``PreToolUse``
  denials surface here.
- ``data/tools/dependabot.yml`` — citation-style template for headers.

Usage::

    python -m pipeline.supervision log \\
        --tool-id semgrep \\
        --failure-mode security_vulnerability \\
        --mechanism "blocked-commit-via-pre-commit" \\
        --detail "src/foo.py:14: unsafe deserialisation" \\
        --invoked-by pre-commit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline.supervision.logger import log_prevention


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.supervision",
        description="Append a SAICA-KG prevention event to the local JSONL log.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    log = sub.add_parser("log", help="append one prevention event")
    log.add_argument("--tool-id", required=True, help="SAICA-KG tool id (e.g. semgrep)")
    log.add_argument(
        "--failure-mode",
        required=True,
        help="SAICA failure-mode id (e.g. security_vulnerability)",
    )
    log.add_argument(
        "--mechanism",
        required=True,
        help='short verb phrase, e.g. "blocked-commit-via-pre-commit"',
    )
    log.add_argument("--detail", default="", help="human-readable specifics")
    log.add_argument(
        "--invoked-by",
        default="manual",
        choices=("pre-commit", "claude-code-hook", "ci", "manual"),
        help="caller surface",
    )
    log.add_argument(
        "--log-dir",
        default=None,
        help="override log directory (mostly for tests)",
    )
    log.set_defaults(_handler=_handle_log)
    return parser


def _handle_log(args: argparse.Namespace) -> int:
    try:
        path = log_prevention(
            tool_id=args.tool_id,
            failure_mode=args.failure_mode,
            mechanism=args.mechanism,
            detail=args.detail,
            invoked_by=args.invoked_by,
            log_dir=Path(args.log_dir) if args.log_dir else None,
        )
    except ValueError as exc:
        print(f"prevention-log: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"prevention-log: cannot write log: {exc}", file=sys.stderr)
        return 1

    print(str(path))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
