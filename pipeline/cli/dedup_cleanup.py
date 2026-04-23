"""One-time retrofit CLI: mark duplicates the preprocess pass missed.

Before ``DupChecker`` was wired into preprocess, candidate rows could be
promoted even when a matching ``data/tools/*.yml`` already existed (observed
live: the ``helicone`` YAML predated the ``Helicone/helicone`` candidate by
weeks, yet preprocess re-promoted the GitHub URL). This CLI is a backfill
— it walks every ``status IN ('pending','low_relevance')`` row in
``candidate_tools``, asks :class:`pipeline.dedup.DupChecker` (YAML side only)
if the URL already exists in the canonical corpus, and if so transitions the
row to ``status='duplicate'`` with ``nlp_tags.dup_match`` pointing at the
matched YAML tool id. A second pass catches intra-candidate collisions
(multiple candidate rows that canonicalize to the same GitHub URL): keep the
oldest (lowest id) and mark the rest duplicate, pointing at the keeper's id.

Usage::

    python -m pipeline.cli.dedup_cleanup --dry-run        # report only
    python -m pipeline.cli.dedup_cleanup                  # apply UPDATEs
    python -m pipeline.cli.dedup_cleanup --purge-raw      # also tag raw rows

``--purge-raw`` iterates ``raw_search_results`` and, for any row whose URL
canonicalizes to a YAML tool, writes ``raw_json._dup_of_yaml = '<tool-id>'``
on the JSONB. Nothing is deleted — the downstream preprocess wired in
``fde60f9`` already filters these out via ``DupChecker``.

The module is structured so tests can exercise the planner + applier
without a live Postgres: pass a fake connection and a pre-built
``DupChecker`` into :func:`run`.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from pipeline.dedup import DupChecker, canonical_github_url


# ---------------------------------------------------------------------------
# Plan dataclasses
# ---------------------------------------------------------------------------


@dataclass
class YamlDupAction:
    """A candidate row that matched a YAML tool."""

    candidate_id: int
    source_url: str
    tool_id: str
    rule: str


@dataclass
class IntraDupAction:
    """A candidate row that duplicates another (older) candidate row."""

    candidate_id: int
    source_url: str
    keeper_candidate_id: int
    keeper_source_url: str


@dataclass
class RawDupAction:
    """A raw_search_results row whose URL resolves to a known YAML tool."""

    raw_id: int
    url: str
    tool_id: str


@dataclass
class Plan:
    yaml_dups: list[YamlDupAction] = field(default_factory=list)
    intra_dups: list[IntraDupAction] = field(default_factory=list)
    raw_dups: list[RawDupAction] = field(default_factory=list)
    # status -> count, captured AFTER the plan is applied (or projected,
    # for dry-run). Populated by :func:`_final_counts`.
    final_status_counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Plan construction
# ---------------------------------------------------------------------------


_SCAN_STATUSES = ("pending", "low_relevance")


def _fetch_scan_rows(conn: Any) -> list[tuple[int, str]]:
    """Return (id, source_url) for every scan-eligible candidate row."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, source_url FROM candidate_tools "
            "WHERE status IN ('pending', 'low_relevance') "
            "ORDER BY id ASC"
        )
        return [(int(r[0]), r[1]) for r in cur.fetchall()]


def _fetch_raw_rows(conn: Any) -> list[tuple[int, Optional[str]]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, url FROM raw_search_results ORDER BY id ASC")
        return [(int(r[0]), r[1]) for r in cur.fetchall()]


def build_plan(
    conn: Any,
    checker: DupChecker,
    *,
    include_raw: bool = False,
) -> Plan:
    """Compute the set of updates without issuing any writes.

    Semantics:
      1. For each ``candidate_tools`` row in ('pending','low_relevance'),
         ask ``checker`` (which must be built with
         ``include_candidates=False``) if the URL matches the YAML corpus.
         Matches go in ``plan.yaml_dups``.
      2. Among the *remaining* (unmatched) rows, group by canonical URL.
         Any group of size >= 2 contributes ``size - 1`` entries to
         ``plan.intra_dups``, keeping the lowest-id row.
      3. If ``include_raw`` is set, scan ``raw_search_results`` and record
         every URL that canonicalizes to a YAML tool.
    """
    plan = Plan()

    rows = _fetch_scan_rows(conn)
    unmatched: list[tuple[int, str]] = []
    for cid, url in rows:
        hit = checker.check_url(url) if url else None
        if hit is not None and hit.kind == "yaml":
            plan.yaml_dups.append(
                YamlDupAction(
                    candidate_id=cid,
                    source_url=url,
                    tool_id=hit.match_id,
                    rule=hit.rule,
                )
            )
        else:
            unmatched.append((cid, url))

    # Intra-batch dedup. Rows ordered by id ASC (SELECT guarantees it), so
    # the first in each group is the oldest.
    groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for cid, url in unmatched:
        canon = canonical_github_url(url) if url else None
        # If the URL is not a GitHub repo we use the raw URL as the key —
        # exact-string repeats still get caught, but arbitrary near-misses
        # (with/without query string) would not. That's intentional; a more
        # aggressive fallback belongs in DupChecker, not here.
        key = canon or (url or f"__nokey_{cid}")
        groups[key].append((cid, url))
    for _key, members in groups.items():
        if len(members) < 2:
            continue
        keeper_id, keeper_url = members[0]
        for cid, url in members[1:]:
            plan.intra_dups.append(
                IntraDupAction(
                    candidate_id=cid,
                    source_url=url,
                    keeper_candidate_id=keeper_id,
                    keeper_source_url=keeper_url,
                )
            )

    if include_raw:
        raw_rows = _fetch_raw_rows(conn)
        for raw_id, url in raw_rows:
            if not url:
                continue
            hit = checker.check_url(url)
            if hit is not None and hit.kind == "yaml":
                plan.raw_dups.append(
                    RawDupAction(raw_id=raw_id, url=url, tool_id=hit.match_id)
                )

    return plan


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


_UPDATE_CANDIDATE_SQL = """
    UPDATE candidate_tools
       SET status   = 'duplicate',
           nlp_tags = jsonb_set(
               COALESCE(nlp_tags, '{}'::jsonb),
               '{dup_match}',
               to_jsonb(%s::text),
               true
           )
     WHERE id = %s
"""

_UPDATE_RAW_SQL = """
    UPDATE raw_search_results
       SET raw_json = jsonb_set(
           COALESCE(raw_json, '{}'::jsonb),
           '{_dup_of_yaml}',
           to_jsonb(%s::text),
           true
       )
     WHERE id = %s
"""


def apply_plan(conn: Any, plan: Plan) -> None:
    """Apply every action in ``plan`` in a single transaction."""
    with conn.cursor() as cur:
        for action in plan.yaml_dups:
            cur.execute(
                _UPDATE_CANDIDATE_SQL, (action.tool_id, action.candidate_id)
            )
        for action in plan.intra_dups:
            cur.execute(
                _UPDATE_CANDIDATE_SQL,
                (str(action.keeper_candidate_id), action.candidate_id),
            )
        for action in plan.raw_dups:
            cur.execute(_UPDATE_RAW_SQL, (action.tool_id, action.raw_id))
    conn.commit()


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _final_counts(conn: Any) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, COUNT(*) FROM candidate_tools "
            "GROUP BY status ORDER BY status"
        )
        return {str(row[0]): int(row[1]) for row in cur.fetchall()}


def _project_counts_for_dry_run(conn: Any, plan: Plan) -> dict[str, int]:
    """Return the post-apply status distribution *without* issuing writes."""
    current = _final_counts(conn)
    delta = len(plan.yaml_dups) + len(plan.intra_dups)
    if delta == 0:
        return current
    projected = dict(current)
    # We can only subtract from the statuses we scanned.
    to_subtract = defaultdict(int)
    with conn.cursor() as cur:
        ids = [a.candidate_id for a in plan.yaml_dups] + [
            a.candidate_id for a in plan.intra_dups
        ]
        if ids:
            cur.execute(
                "SELECT status, COUNT(*) FROM candidate_tools "
                "WHERE id = ANY(%s) GROUP BY status",
                (ids,),
            )
            for row in cur.fetchall():
                to_subtract[str(row[0])] = int(row[1])
    for status, count in to_subtract.items():
        projected[status] = projected.get(status, 0) - count
        if projected[status] <= 0:
            projected.pop(status, None)
    projected["duplicate"] = projected.get("duplicate", 0) + delta
    return projected


def format_report(plan: Plan, *, dry_run: bool, include_raw: bool) -> str:
    lines: list[str] = []
    prefix = "[dry-run] " if dry_run else ""
    lines.append(f"{prefix}dedup_cleanup report")
    lines.append(f"{prefix}  YAML-matched candidates: {len(plan.yaml_dups)}")
    if plan.yaml_dups:
        tool_counts: dict[str, int] = defaultdict(int)
        for action in plan.yaml_dups:
            tool_counts[action.tool_id] += 1
        for tool_id, count in sorted(tool_counts.items()):
            lines.append(f"{prefix}    - {tool_id}: {count}")
        for action in plan.yaml_dups:
            lines.append(
                f"{prefix}    candidate_id={action.candidate_id} "
                f"url={action.source_url} -> {action.tool_id} "
                f"(rule={action.rule})"
            )
    lines.append(
        f"{prefix}  intra-candidate duplicates: {len(plan.intra_dups)}"
    )
    for action in plan.intra_dups:
        lines.append(
            f"{prefix}    candidate_id={action.candidate_id} "
            f"url={action.source_url} -> keeper id={action.keeper_candidate_id}"
        )
    if include_raw:
        lines.append(
            f"{prefix}  raw_search_results tagged: {len(plan.raw_dups)}"
        )
        for action in plan.raw_dups:
            lines.append(
                f"{prefix}    raw_id={action.raw_id} url={action.url} "
                f"-> {action.tool_id}"
            )
    lines.append(f"{prefix}  final status counts:")
    for status, count in sorted(plan.final_status_counts.items()):
        lines.append(f"{prefix}    {status:<14} {count}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point (used by ``main`` and tests alike)
# ---------------------------------------------------------------------------


def run(
    conn: Any,
    checker: DupChecker,
    *,
    dry_run: bool,
    purge_raw: bool,
) -> Plan:
    """Build the plan, optionally apply it, populate final counts, return it.

    Tests prefer this over ``main`` because it accepts an already-built
    connection and checker — no Postgres, no YAML disk I/O required.
    """
    plan = build_plan(conn, checker, include_raw=purge_raw)
    if dry_run:
        plan.final_status_counts = _project_counts_for_dry_run(conn, plan)
    else:
        apply_plan(conn, plan)
        plan.final_status_counts = _final_counts(conn)
    return plan


# ---------------------------------------------------------------------------
# argparse + main
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pipeline.cli.dedup_cleanup",
        description=(
            "Mark candidate_tools rows whose URL duplicates an existing "
            "data/tools/*.yml entry (or an older candidate row)."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change; don't issue UPDATEs.",
    )
    p.add_argument(
        "--purge-raw",
        action="store_true",
        help=(
            "Also tag raw_search_results rows whose URL matches a YAML tool "
            "with raw_json._dup_of_yaml = '<tool-id>'. No rows are deleted."
        ),
    )
    p.add_argument(
        "--yaml-dir",
        default="data/tools",
        help="Canonical tool YAML directory (default: data/tools).",
    )
    return p


def main(argv: Optional[Iterable[str]] = None) -> int:
    from pipeline.logging_config import configure_logging

    configure_logging()
    args = _build_parser().parse_args(list(argv) if argv is not None else None)

    # Deferred import so tests can run without psycopg installed.
    from pipeline import db as pipeline_db

    checker = DupChecker(yaml_dir=args.yaml_dir, include_candidates=False)
    with pipeline_db.get_conn() as conn:
        plan = run(
            conn,
            checker,
            dry_run=args.dry_run,
            purge_raw=args.purge_raw,
        )
        sys.stdout.write(
            format_report(
                plan, dry_run=args.dry_run, include_raw=args.purge_raw
            )
            + "\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
