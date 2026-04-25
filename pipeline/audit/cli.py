"""CLI for the audit analyzer.

Usage::

    python -m pipeline.audit.cli https://github.com/owner/repo
    python -m pipeline.audit.cli https://github.com/owner/repo --md
    python -m pipeline.audit.cli https://github.com/owner/repo --json

Without ``--md`` or ``--json`` we print the Markdown report followed by a
short JSON summary so users get the human view first and the machine view
on the same invocation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.audit.analyzer import audit_repo, audit_repo_local


def _json_dump(report) -> str:
    # Pydantic v2 model_dump_json is preferred; fall back to dict + json.
    if hasattr(report, "model_dump_json"):
        return report.model_dump_json(indent=2)
    return json.dumps(report.dict(), indent=2, default=str)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.audit.cli",
        description="Audit a public GitHub repo for AI-coding-agent supervision coverage.",
    )
    parser.add_argument(
        "repo_url",
        help="https://github.com/<owner>/<repo>",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Treat repo_url as a local filesystem path (skip clone). Useful for testing.",
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument("--md", action="store_true", help="Print only the Markdown report.")
    fmt.add_argument("--json", action="store_true", help="Print only the JSON report.")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Optional file to write the chosen format to (default: stdout).",
    )

    args = parser.parse_args(argv)

    try:
        if args.local:
            report = audit_repo_local(args.repo_url)
        else:
            report = audit_repo(args.repo_url)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        out = _json_dump(report)
    elif args.md:
        out = report.markdown
    else:
        # Default: Markdown, then a short JSON tail (stack + coverage + gap counts).
        tail = {
            "repo_url": report.repo_url,
            "audited_at": report.audited_at.isoformat(),
            "n_supervision_tools": len(report.stack.supervision_tools),
            "n_failure_modes_covered": len(report.coverage.failure_modes_covered),
            "n_failure_modes_missing": len(report.coverage.failure_modes_missing),
            "gaps": [
                {"failure_mode": g.failure_mode, "severity": g.severity}
                for g in report.gaps
            ],
        }
        out = report.markdown + "\n```json\n" + json.dumps(tail, indent=2) + "\n```\n"

    if args.output:
        args.output.write_text(out, encoding="utf-8")
    else:
        print(out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
