"""CLI: ``python -m pipeline.cli.extract <tools|papers|tool|paper|status> ...``.

Thin wrapper around ``pipeline.extract.kimi`` that:

1. Pulls pending rows from Postgres (via ``pipeline.db.get_pending``).
2. Checks the per-candidate cache (``pipeline.extract.cache``) to avoid
   re-paying Kimi for something we already extracted.
3. Calls the LLM for misses.
4. Persists extractions back into ``candidate_*.extracted``.

This CLI does NOT write YAML. That's the graduation CLI's job.

Examples::

    python -m pipeline.cli.extract tools --limit 20
    python -m pipeline.cli.extract papers --limit 20
    python -m pipeline.cli.extract tool 42
    python -m pipeline.cli.extract paper 42
    python -m pipeline.cli.extract status
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from psycopg.rows import dict_row

from pipeline import db
from pipeline.extract import cache as cache_mod
from pipeline.extract import kimi
from pipeline.extract.schemas import PaperExtraction, ToolExtraction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_KIND_TABLE = {"tools": "candidate_tools", "papers": "candidate_papers"}


def _fetch_one(kind: str, candidate_id: int) -> Optional[dict]:
    table = _KIND_TABLE[kind]
    sql = f"SELECT * FROM {table} WHERE id = %s"
    with db.get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (candidate_id,))
        return cur.fetchone()


def _extract_one(kind: str, row: dict, *, force: bool = False) -> dict:
    """Extract + cache a single candidate. Returns the extracted payload."""
    cache_key = cache_mod.compute_cache_key(
        kind=kind,
        candidate_id=int(row["id"]),
        source_url=str(row.get("source_url") or ""),
    )
    if not force:
        cached = cache_mod.lookup_extraction(kind, int(row["id"]), cache_key)
        if cached is not None:
            print(f"  [cache] hit for {kind} id={row['id']}")
            return cached

    if kind == "tools":
        extraction = kimi.extract_tool(row)
    elif kind == "papers":
        extraction = kimi.extract_paper(row)
    else:
        raise ValueError(f"Unknown kind {kind!r}")

    payload = extraction.model_dump(mode="json")
    cache_mod.store_extraction(
        kind,
        int(row["id"]),
        cache_key,
        payload,
        model=kimi._model_name(),
    )
    print(
        f"  [kimi] extracted {kind} id={row['id']}"
        f" (overall_confidence={payload.get('overall_confidence')})"
    )
    return payload


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


def _cmd_batch(args: argparse.Namespace) -> int:
    kind = args.cmd  # "tools" | "papers"
    pending = db.get_pending(kind, limit=args.limit)
    if not pending:
        print(f"no pending {kind}")
        return 0
    print(f"extracting {len(pending)} pending {kind} (concurrency={kimi.MAX_CONCURRENCY})")
    ok = 0
    failed = 0
    for row in pending:
        try:
            _extract_one(kind, row, force=args.force)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  [error] {kind} id={row['id']}: {exc}", file=sys.stderr)
    print(f"done: ok={ok} failed={failed}")
    return 0 if failed == 0 else 1


def _cmd_one(args: argparse.Namespace) -> int:
    kind = "tools" if args.cmd == "tool" else "papers"
    row = _fetch_one(kind, args.candidate_id)
    if row is None:
        print(f"no {kind[:-1]} candidate with id={args.candidate_id}", file=sys.stderr)
        return 2
    payload = _extract_one(kind, row, force=args.force)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    sql_template = (
        "SELECT status, COUNT(*) AS n,"
        "       SUM(CASE WHEN jsonb_typeof(extracted) = 'object' AND extracted ? 'payload' THEN 1 ELSE 0 END) AS extracted_n"
        " FROM {table} GROUP BY status ORDER BY status"
    )
    with db.get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        for kind, table in _KIND_TABLE.items():
            print(f"\n{table}:")
            cur.execute(sql_template.format(table=table))
            rows = cur.fetchall()
            if not rows:
                print("  (empty)")
                continue
            for r in rows:
                print(
                    f"  status={r['status']:<10}  count={r['n']:>4}"
                    f"  extracted={r['extracted_n']:>4}"
                )
    return 0


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pipeline.cli.extract")
    sub = p.add_subparsers(dest="cmd", required=True)

    for kind in ("tools", "papers"):
        sp = sub.add_parser(kind, help=f"Extract pending {kind} candidates")
        sp.add_argument("--limit", type=int, default=20)
        sp.add_argument(
            "--force",
            action="store_true",
            help="Ignore cache and re-call Kimi",
        )
        sp.set_defaults(func=_cmd_batch)

    for singular in ("tool", "paper"):
        sp = sub.add_parser(singular, help=f"Extract one {singular} candidate by id")
        sp.add_argument("candidate_id", type=int)
        sp.add_argument("--force", action="store_true")
        sp.set_defaults(func=_cmd_one)

    sp_status = sub.add_parser(
        "status", help="Show pending vs extracted counts per candidate table"
    )
    sp_status.set_defaults(func=_cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
