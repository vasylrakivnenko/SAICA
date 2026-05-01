"""CLI entry point: ``python -m pipeline.cli.preprocess {run,stats}``."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Optional


def _parse_since(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    # Accept YYYY-MM-DD or ISO-8601.
    try:
        if len(value) == 10 and value[4] == "-" and value[7] == "-":
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"invalid --since value {value!r}: {exc}") from exc


def _cmd_run(args: argparse.Namespace) -> int:
    from pipeline.nlp.pipeline import run

    since = _parse_since(args.since)
    summary = run(since=since)
    return 0 if not summary.errors else 1


def _cmd_stats(_: argparse.Namespace) -> int:
    from pipeline import db

    with db.get_conn() as conn, conn.cursor() as cur:
        print("candidate_tools by status:")
        cur.execute(
            "SELECT status, COUNT(*) FROM candidate_tools "
            "GROUP BY status ORDER BY status"
        )
        for row in cur.fetchall():
            print(f"  {row[0]:<12} {row[1]}")
        print("candidate_papers by status:")
        cur.execute(
            "SELECT status, COUNT(*) FROM candidate_papers "
            "GROUP BY status ORDER BY status"
        )
        for row in cur.fetchall():
            print(f"  {row[0]:<12} {row[1]}")
        print("raw_search_results by source:")
        cur.execute(
            "SELECT source, COUNT(*) FROM raw_search_results "
            "GROUP BY source ORDER BY source"
        )
        for row in cur.fetchall():
            print(f"  {row[0]:<16} {row[1]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.cli.preprocess",
        description="SAICA-KG NLP pre-processing CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="process raw_search_results rows")
    p_run.add_argument(
        "--since",
        default=None,
        help="only rows fetched since this timestamp (YYYY-MM-DD or ISO-8601)",
    )
    p_run.set_defaults(func=_cmd_run)

    p_stats = sub.add_parser("stats", help="print candidate counts by status")
    p_stats.set_defaults(func=_cmd_stats)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    from pipeline.logging_config import configure_logging

    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
