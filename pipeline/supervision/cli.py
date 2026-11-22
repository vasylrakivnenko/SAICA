"""Command line for the prevention log: write one event by hand.

Everything written here is a **self-report** and is stored with
``recorded_by: "cli"``, whatever ``--invoked-by`` says. Events that a hook
observed are written by the hook process itself
(:mod:`pipeline.supervision.pretool`), never through this command.

``--invoked-by`` says what happened: ``manual`` (a person), ``agent-manual``
(an agent that ran into a failed check and reports it, as ``CLAUDE.md``
asks), ``pre-commit`` or ``ci`` (a script calling this command). The old
value ``claude-code-hook`` is still accepted and stored as ``agent-manual``:
this command cannot be a hook.

Usage::

    .venv/bin/python -m pipeline.supervision log \\
        --tool-id ruff \\
        --failure-mode logic_error \\
        --mechanism "blocked-commit-via-pre-commit" \\
        --detail "src/foo.py:14: F821 undefined name" \\
        --invoked-by agent-manual

    .venv/bin/python -m pipeline.supervision show     # counts by who recorded
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline.supervision.logger import log_prevention, read_events

INVOKED_BY = ("manual", "agent-manual", "pre-commit", "ci")


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
        choices=INVOKED_BY + ("claude-code-hook",),
        help=(
            "what triggered this report (claude-code-hook is an old name; it "
            "is stored as agent-manual)"
        ),
    )
    log.add_argument(
        "--log-dir",
        default=None,
        help="override log directory (mostly for tests)",
    )
    log.set_defaults(_handler=_handle_log)

    show = sub.add_parser("show", help="count the logged events by who recorded them")
    show.add_argument("--log-dir", default=None, help="override log directory")
    show.set_defaults(_handler=_handle_show)
    return parser


def _handle_show(args: argparse.Namespace) -> int:
    events = read_events(Path(args.log_dir) if args.log_dir else None)
    hook = [e for e in events if e.get("recorded_by") == "hook"]
    typed = len(events) - len(hook)
    print(f"{len(events)} events")
    print(f"  recorded by the hook itself (observed): {len(hook)}")
    print(f"  typed in through this command (self-reported): {typed}")
    for event in hook[:20]:
        print(
            f"  {event.get('ts', '')}  {event.get('decision', '?'):4}  "
            f"{event.get('mechanism', '')}  {event.get('detail', '')[:80]}"
        )
    return 0


def _handle_log(args: argparse.Namespace) -> int:
    invoked_by = args.invoked_by
    if invoked_by == "claude-code-hook":
        print(
            "prevention-log: this command is not a hook; recording "
            "invoked_by=agent-manual",
            file=sys.stderr,
        )
        invoked_by = "agent-manual"
    try:
        path = log_prevention(
            tool_id=args.tool_id,
            failure_mode=args.failure_mode,
            mechanism=args.mechanism,
            detail=args.detail,
            invoked_by=invoked_by,
            log_dir=Path(args.log_dir) if args.log_dir else None,
            recorded_by="cli",
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
