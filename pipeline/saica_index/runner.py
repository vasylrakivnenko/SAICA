"""SAICA Index — orchestrator.

For each ``SeedRepo`` of the board: call
:func:`pipeline.audit.analyzer.audit_repo`, score the result with
:func:`pipeline.saica_index.score.score_report`, and serialise the
combined result to a single JSON the leaderboard page consumes.

Output schema (``site/public/saica_index.json``)
------------------------------------------------

::

    {
      "version": 1,
      "generated_at": "2026-05-01T12:34:56Z",
      "boards": {
        "popular_oss":  [<row>, ...]
      },
      "errors": [
        {"url": "...", "board": "...", "error": "..."}
      ]
    }

A ``row`` is::

    {
      "name":            "tiangolo/fastapi",
      "url":             "https://github.com/tiangolo/fastapi",
      "category":        "web_framework",
      "note":            "...",
      "score":           0.42,
      "grade":           "C",
      "fms_covered":     7,
      "fms_total":       11,
      "paradigm_counts": {"prevention": 2, "detection": 4, ...},
      "is_balanced":     false,
      "per_fm":          {"scope_creep": 0.4, ...},
      "summary":         "...",
      "audited_at":      "2026-05-01"
    }

The leaderboard page (``site/src/pages/leaderboard.astro``) reads this
file directly — no backend.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.audit.analyzer import audit_repo
from pipeline.audit.schemas import AuditReport
from pipeline.saica_index.score import RepoScore, score_report
from pipeline.saica_index.seeds import Board, SeedRepo, load_all_boards

log = logging.getLogger("saica_index")

_REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = _REPO / "site" / "public" / "saica_index.json"


# ---------------------------------------------------------------------------
# Per-repo audit + score
# ---------------------------------------------------------------------------


def _row_for(seed: SeedRepo, report: AuditReport, score: RepoScore) -> dict[str, Any]:
    return {
        "name": seed.name,
        "url": seed.url,
        "category": seed.category,
        "note": seed.note,
        "score": score.score,
        "grade": score.grade,
        "fms_covered": score.failure_modes_covered,
        "fms_total": score.failure_modes_total,
        "paradigm_counts": score.paradigm_counts,
        "is_balanced": score.is_balanced,
        "per_fm": score.per_fm,
        "summary": report.summary,
        "audited_at": report.audited_at.isoformat(),
        "score_notes": score.notes,
    }


def _audit_one(
    seed: SeedRepo, github_token: str | None = None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Audit + score one repo. Returns ``(row, error)``; one of them None."""
    t0 = time.time()
    try:
        report = audit_repo(seed.url, github_token=github_token)
    except Exception as exc:  # noqa: BLE001 — anything can go wrong over the network
        log.warning("audit failed: %s — %s", seed.url, exc)
        return None, {"url": seed.url, "board": seed.board, "error": str(exc)}

    score = score_report(report)
    elapsed = time.time() - t0
    log.info(
        "%-50s  %s  %.2f  (fm=%d/%d, %.1fs)",
        seed.name,
        score.grade,
        score.score,
        score.failure_modes_covered,
        score.failure_modes_total,
        elapsed,
    )
    return _row_for(seed, report, score), None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


class PartialRunError(ValueError):
    """A run of a subset was asked to write the published snapshot."""


def _same_file(a: Path, b: Path) -> bool:
    return a.expanduser().resolve() == b.expanduser().resolve()


def run_index(
    *,
    out_path: Path = DEFAULT_OUT,
    boards: dict[Board, list[SeedRepo]] | None = None,
    limit: int | None = None,
    github_token: str | None = None,
) -> dict[str, Any]:
    """Audit every seed, score, write JSON, return the same payload.

    ``limit`` (per board) is for fast local iteration. A limited run never
    writes the published snapshot (:data:`DEFAULT_OUT`): it raises
    :class:`PartialRunError` before the first audit. ``github_token`` is
    sent to the GitHub API only; one audit costs one API call and the
    anonymous limit is 60 calls per hour.
    """
    if limit is not None and _same_file(out_path, DEFAULT_OUT):
        raise PartialRunError(
            f"--limit {limit} would replace the published snapshot "
            f"({DEFAULT_OUT}) with a partial board. Pass --out with another "
            "path for a trial run."
        )
    if boards is None:
        boards = load_all_boards()

    payload: dict[str, Any] = {
        "version": 1,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "boards": {},
        "errors": [],
    }

    for board_name, seeds in boards.items():
        if limit is not None:
            seeds = seeds[:limit]
        rows: list[dict[str, Any]] = []
        for seed in seeds:
            row, err = _audit_one(seed, github_token)
            if row is not None:
                rows.append(row)
            if err is not None:
                payload["errors"].append(err)
        # Sort each board: highest score first; tiebreak by name.
        rows.sort(key=lambda r: (-r["score"], r["name"]))
        payload["boards"][board_name] = rows

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    log.info(
        "wrote %s (%d boards, %d errors)",
        out_path,
        len(payload["boards"]),
        len(payload["errors"]),
    )
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.saica_index.runner",
        description=(
            "Audit and score every seed repo and write the leaderboard JSON. "
            "With --limit, --out is required: a partial run never writes the "
            "published snapshot."
        ),
        epilog=(
            "GITHUB_TOKEN, when set, is sent to api.github.com to raise the "
            "request limit (one call per repo; 60 per hour without a token)."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output JSON path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Audit only the first N seeds per board (needs --out).",
    )
    parser.add_argument(
        "--boards",
        nargs="*",
        choices=["popular_oss"],
        default=None,
        help="Only run these boards (default: all).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-repo progress logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )

    boards = load_all_boards()
    if args.boards:
        boards = {b: boards[b] for b in args.boards if b in boards}  # type: ignore[misc]

    try:
        run_index(
            out_path=args.out,
            boards=boards,
            limit=args.limit,
            github_token=os.environ.get("GITHUB_TOKEN") or None,
        )
    except PartialRunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
