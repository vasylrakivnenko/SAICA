"""CLI: ``python -m pipeline.cli.db <init|status>``."""

from __future__ import annotations

import argparse
import sys

from pipeline import db


def _cmd_init(args: argparse.Namespace) -> int:
    db.init_schema(drop_first=args.drop_first)
    print("schema initialized")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    counts = db.table_counts()
    width = max(len(name) for name, _ in counts)
    for name, count in counts:
        print(f"{name.ljust(width)}  count={count}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pipeline.cli.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Run schema.sql against the configured DB")
    p_init.add_argument(
        "--drop-first",
        action="store_true",
        help="Drop existing pipeline tables before re-creating them",
    )
    p_init.set_defaults(func=_cmd_init)

    p_status = sub.add_parser("status", help="Print each pipeline table + row count")
    p_status.set_defaults(func=_cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
