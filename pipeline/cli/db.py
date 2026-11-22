"""CLI: ``python -m pipeline.cli.db <init|status>``.

``init`` applies ``schema.sql``. ``init --drop-first`` deletes every row in
the five pipeline tables first; it prints which database it is about to
empty and does nothing unless ``--yes`` is given. ``status`` prints the
database it reads and a row count per table. Neither prints credentials.
"""

from __future__ import annotations

import argparse
import sys

from pipeline import db
from pipeline.logging_config import configure_logging


def _cmd_init(args: argparse.Namespace) -> int:
    where = db.describe_target()
    if args.drop_first:
        print(f"target database: {where}")
        print(
            "--drop-first drops these tables and every row in them: "
            + ", ".join(db._TABLES)
        )
        if not args.yes:
            print(
                "Nothing was changed. Run again with --yes to drop and re-create"
                " the tables.",
                file=sys.stderr,
            )
            return 2
    db.init_schema(drop_first=args.drop_first, allow_non_test=bool(args.yes))
    print(f"schema initialized in {where}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    print(f"database: {db.describe_target()}")
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
        help="Drop existing pipeline tables (and all their rows) before"
        " re-creating them; needs --yes",
    )
    p_init.add_argument(
        "--yes",
        action="store_true",
        help="Confirm --drop-first for the database that is printed",
    )
    p_init.set_defaults(func=_cmd_init)

    p_status = sub.add_parser("status", help="Print each pipeline table + row count")
    p_status.set_defaults(func=_cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
