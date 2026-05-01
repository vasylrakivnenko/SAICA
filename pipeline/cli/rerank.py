"""CLI: ``python -m pipeline.cli.rerank <tools> [flags]``.

Score pending candidate_tools rows against the supervision-focused query
library (``pipeline.rerank.queries.SUPERVISION_QUERIES``) using Cohere
Rerank v4.0 Pro on Azure, then write aggregated scores back into each
row's ``nlp_tags`` (never touching the ``extracted`` column).

Examples::

    python -m pipeline.cli.rerank tools
    python -m pipeline.cli.rerank tools --limit 50
    python -m pipeline.cli.rerank tools --ids 73,74,106
    python -m pipeline.cli.rerank tools --query-id fabrication
    python -m pipeline.cli.rerank tools --dry-run
    python -m pipeline.cli.rerank tools --limit 5 --top 5
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Optional

from psycopg.rows import dict_row
from psycopg.types.json import Json

from pipeline import db
from pipeline.cost_caps import CallBudget, CostCapExceeded
from pipeline.rerank.cohere import (
    CohereRerankClient,
    DocScore,
    compose_document,
    rerank_candidates,
    rerank_provenance,
)
from pipeline.rerank.queries import (
    QUERY_SET_VERSION,
    SUPERVISION_QUERIES,
    RerankQuery,
    queries_content_hash,
)


log = logging.getLogger("pipeline.cli.rerank")

# Conservative default: 100 Cohere rerank calls. Each bundles many docs so
# the useful-work ceiling is large; 100 is still well under any plausible
# runaway. Users can override with --max-calls.
DEFAULT_MAX_CALLS = 100

# Exit code reserved pipeline-wide for "budget hit".
EXIT_BUDGET_HIT = 3


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _fetch_rows(
    limit: Optional[int],
    ids: Optional[list[int]],
    *,
    rescore_stale: bool = False,
) -> list[dict]:
    """Pull candidate_tools rows from Postgres.

    If ``ids`` is provided, fetch exactly those (regardless of status);
    otherwise fall back to pending rows ordered oldest-first (same contract
    as ``db.get_pending``). When ``rescore_stale`` is True, the pending
    selection is post-filtered in Python to only rows whose stored
    ``rerank_query_set_hash`` doesn't match the current
    ``queries_content_hash()`` (rows never scored also qualify).
    """
    if ids:
        sql = (
            "SELECT id, source_url, proposed_id, name, summary, nlp_tags, status "
            "FROM candidate_tools WHERE id = ANY(%s) ORDER BY id ASC"
        )
        with db.get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (list(ids),))
            return list(cur.fetchall())

    sql = (
        "SELECT id, source_url, proposed_id, name, summary, nlp_tags, status "
        "FROM candidate_tools WHERE status = 'pending' ORDER BY created_at ASC "
    )
    params: tuple = ()
    if limit is not None:
        sql += "LIMIT %s"
        params = (limit,)
    with db.get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())

    if rescore_stale:
        current_hash = queries_content_hash()
        rows = [
            r
            for r in rows
            if (r.get("nlp_tags") or {}).get("rerank_query_set_hash") != current_hash
        ]
    return rows


def _readme_lookup(url: str) -> Optional[str]:
    """Best-effort README fetch from ``raw_readmes``.

    Matches by exact URL first, then by prefix (since we commonly store
    ``<repo>/blob/main/README.md`` while the candidate's ``source_url`` is
    just the repo root).
    """
    sql_exact = "SELECT content FROM raw_readmes WHERE url = %s"
    sql_prefix = "SELECT content FROM raw_readmes WHERE url LIKE %s LIMIT 1"
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql_exact, (url,))
        row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
        cur.execute(sql_prefix, (url.rstrip("/") + "%",))
        row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
    return None


def _write_scores(rows_by_id: dict[int, dict], scores: list[DocScore]) -> int:
    """Merge rerank scores into ``candidate_tools.nlp_tags``. Returns row count.

    Fields written to ``nlp_tags``:
        rerank_score              -- max across queries (primary ranking signal)
        rerank_score_mean         -- mean across queries
        rerank_best_query         -- query_id that produced score_max
        rerank_per_query          -- {query_id: float}
        rerank_updated_at         -- ISO8601 string (UTC)
        rerank_query_set_version  -- ``QUERY_SET_VERSION`` at write time
        rerank_query_set_hash     -- short hash of the live SUPERVISION_QUERIES
        rerank_scored_at          -- ISO timestamp (pairs with hash)

    Storing the version + hash lets a later process detect stale scores
    (``rerank_query_set_hash`` differs from ``queries_content_hash()``) and
    re-score just those rows with ``--rescore-stale``.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    provenance = rerank_provenance()
    sql = (
        "UPDATE candidate_tools SET nlp_tags = "
        "COALESCE(nlp_tags, '{}'::jsonb) || %s::jsonb WHERE id = %s"
    )
    updated = 0
    with db.get_conn() as conn, conn.cursor() as cur:
        for score in scores:
            if score.candidate_id not in rows_by_id:
                continue
            patch = {
                "rerank_score": round(score.score_max, 6),
                "rerank_score_mean": round(score.score_mean, 6),
                "rerank_best_query": score.best_query,
                "rerank_per_query": {
                    k: round(v, 6) for k, v in score.per_query.items()
                },
                "rerank_updated_at": now,
                **provenance,
            }
            cur.execute(sql, (Json(patch), score.candidate_id))
            updated += 1
        conn.commit()
    return updated


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print_top(
    scores: list[DocScore],
    rows_by_id: dict[int, dict],
    top: int,
    queries: list[RerankQuery],
) -> None:
    n = min(top, len(scores))
    print(f"top {n}:")
    name_col = max(
        (
            len((rows_by_id[s.candidate_id].get("proposed_id") or "") or "")
            for s in scores[:n]
        ),
        default=12,
    )
    name_col = max(name_col, 12)
    for s in scores[:n]:
        row = rows_by_id.get(s.candidate_id, {})
        label = row.get("proposed_id") or row.get("name") or f"id={s.candidate_id}"
        print(
            f"  [{s.candidate_id:>4}] {label:<{name_col}}"
            f"  max={s.score_max:.3f}  mean={s.score_mean:.3f}"
            f"  best={s.best_query}"
        )


def _dry_run(rows: list[dict], queries: list[RerankQuery]) -> None:
    print(f"DRY RUN — would send {len(queries)} queries × {len(rows)} docs")
    print("endpoint: <AZURE_COHERE_RERANK_ENDPOINT>")
    print("queries:")
    for q in queries:
        facet = f" ({q.facet})" if q.facet else ""
        print(f"  - [{q.id}]{facet}: {q.text[:90]}")
    print("documents (preview):")
    for r in rows:
        doc = compose_document(r)
        head = doc.splitlines()[0] if doc else "(empty)"
        print(
            f"  - id={r['id']:<4} chars={len(doc):>5} "
            f"proposed_id={r.get('proposed_id')!r} head={head[:80]!r}"
        )


# ---------------------------------------------------------------------------
# Subcommand
# ---------------------------------------------------------------------------


def _parse_ids(raw: Optional[str]) -> Optional[list[int]]:
    if not raw:
        return None
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError as exc:
        raise SystemExit(f"invalid --ids value {raw!r}: {exc}") from exc


def _select_queries(query_id: Optional[str]) -> list[RerankQuery]:
    if query_id is None:
        return list(SUPERVISION_QUERIES)
    matched = [q for q in SUPERVISION_QUERIES if q.id == query_id]
    if not matched:
        known = ", ".join(q.id for q in SUPERVISION_QUERIES)
        raise SystemExit(f"unknown --query-id {query_id!r}; known ids: {known}")
    return matched


def _cmd_tools(args: argparse.Namespace) -> int:
    ids = _parse_ids(args.ids)
    rows = _fetch_rows(args.limit, ids, rescore_stale=args.rescore_stale)
    if not rows:
        if args.rescore_stale:
            print(
                f"no stale candidates to rescore "
                f"(current hash={queries_content_hash()}, version={QUERY_SET_VERSION})"
            )
        else:
            print("no candidates to score")
        return 0
    queries = _select_queries(args.query_id)

    if args.dry_run:
        _dry_run(rows, queries)
        return 0

    budget = CallBudget(
        max_calls=args.max_calls,
        max_tokens_estimate=args.max_cost_tokens,
    )
    t0 = time.time()
    client = CohereRerankClient()
    try:
        scores = rerank_candidates(
            rows,
            queries,
            readme_lookup=_readme_lookup,
            client=client,
            budget=budget,
        )
    except CostCapExceeded as exc:
        print(
            f"[budget] cost cap hit: {exc}; {budget.summary()}",
            file=sys.stderr,
        )
        return EXIT_BUDGET_HIT
    elapsed = time.time() - t0

    rows_by_id = {int(r["id"]): r for r in rows}
    ops = len(queries) * len(rows)
    print(
        f"sent {len(queries)} queries x {len(rows)} docs = {ops} scoring ops; "
        f"elapsed {elapsed:.1f}s"
    )

    # Persist to Postgres unless --no-write.
    if args.no_write:
        print("(skipped DB write: --no-write)")
    else:
        wrote = _write_scores(rows_by_id, scores)
        print(f"updated nlp_tags.rerank_* on {wrote} candidate_tools rows")

    # Surface any rate-limit header info Cohere may expose.
    last = getattr(client, "last_headers", {}) or {}
    interesting = {
        k: v
        for k, v in last.items()
        if any(t in k.lower() for t in ("ratelimit", "x-ms-region", "request-id"))
    }
    if interesting:
        print("last response headers:")
        for k, v in sorted(interesting.items()):
            print(f"  {k}: {v}")

    _print_top(scores, rows_by_id, args.top, queries)
    return 0


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pipeline.cli.rerank",
        description=(
            "Cohere rerank scoring of pending SAICA-KG tool candidates "
            "against supervision-focused query passages."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("tools", help="rerank pending candidate_tools rows")
    sp.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max pending rows to score (default: all pending)",
    )
    sp.add_argument(
        "--ids",
        default=None,
        help="comma-separated candidate_tools.id list; overrides --limit/--status",
    )
    sp.add_argument(
        "--query-id",
        default=None,
        help=(
            "only run a single query by id (default: all SUPERVISION_QUERIES). "
            f"Known ids: {', '.join(q.id for q in SUPERVISION_QUERIES)}"
        ),
    )
    sp.add_argument(
        "--top",
        type=int,
        default=15,
        help="how many top-scoring candidates to print after scoring",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be sent without calling the API",
    )
    sp.add_argument(
        "--no-write",
        action="store_true",
        help="skip writing scores back to Postgres",
    )
    sp.add_argument(
        "--rescore-stale",
        action="store_true",
        help=(
            "only score pending rows whose stored rerank_query_set_hash "
            "differs from the current live hash (i.e. the query set has "
            "been edited since they were last scored)"
        ),
    )
    sp.add_argument(
        "--max-calls",
        type=int,
        default=DEFAULT_MAX_CALLS,
        help=(
            f"hard cap on Cohere rerank HTTP calls for this run "
            f"(default {DEFAULT_MAX_CALLS}). "
            f"Exits with code {EXIT_BUDGET_HIT} when exceeded."
        ),
    )
    sp.add_argument(
        "--max-cost-tokens",
        type=int,
        default=None,
        help="optional soft cap on total tokens across the run",
    )
    sp.set_defaults(func=_cmd_tools)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    from pipeline.logging_config import configure_logging

    configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
