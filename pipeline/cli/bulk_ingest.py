"""CLI entry point: ``python -m pipeline.cli.bulk_ingest``.

Reads ``research/candidates_YYYYMMDD.json``, ranks by cross-list source
count, and walks each top-N candidate through GitHub API fetch + README
fetch + ``raw_search_results`` insert. Stops short of Kimi extraction —
run ``pipeline.cli.preprocess`` and ``pipeline.cli.extract`` separately to
control cost.

Examples:
    python -m pipeline.cli.bulk_ingest --top 50
    python -m pipeline.cli.bulk_ingest --top 50 --dry-run
    python -m pipeline.cli.bulk_ingest --min-stars 500 --top 50
    python -m pipeline.cli.bulk_ingest --since 2024-01-01 --top 50
    python -m pipeline.cli.bulk_ingest --from-file paths.json
    python -m pipeline.cli.bulk_ingest --top 50 --preprocess-after
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from pipeline.bulk import (
    DEFAULT_CANDIDATE_FILE,
    DEFAULT_REPORT_DIR,
    IngestResult,
    _STATUS_LABELS,
    render_report,
    run_bulk,
    write_report,
)


def _progress(i: int, total: int, res: IngestResult) -> None:
    label = _STATUS_LABELS.get(res.status, res.status)
    stars = "" if res.stars is None else f" ({res.stars}*)"
    print(
        f"[{i}/{total}] {res.candidate.full_name}{stars} -> {label}"
        + (f": {res.detail}" if res.detail else ""),
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.cli.bulk_ingest",
        description=(
            "Bulk ingest top-ranked awesome-list candidates into "
            "raw_search_results. Stops before Kimi extraction."
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Ingest at most this many ranked candidates (omit for all).",
    )
    parser.add_argument(
        "--min-stars",
        type=int,
        default=None,
        help="Drop candidates whose GitHub star count is below this threshold.",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Require pushed_at on or after this date (YYYY-MM-DD or ISO-8601).",
    )
    parser.add_argument(
        "--from-file",
        dest="from_file",
        default=None,
        help=(
            "Candidate JSON file (default: "
            f"{DEFAULT_CANDIDATE_FILE.relative_to(DEFAULT_CANDIDATE_FILE.parent.parent)})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Rank + dedup only; no GitHub API calls and no DB writes.",
    )
    parser.add_argument(
        "--preprocess-after",
        action="store_true",
        help="Run pipeline.nlp.pipeline.run() after ingest finishes.",
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
        help="Where to write the markdown report (default: research/).",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing the markdown report to disk.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable INFO-level logging.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    from pipeline.logging_config import configure_logging

    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging("INFO" if args.verbose else "WARNING")

    input_file = Path(args.from_file) if args.from_file else DEFAULT_CANDIDATE_FILE
    if not input_file.exists():
        print(f"error: candidate file not found: {input_file}", file=sys.stderr)
        return 2

    try:
        report = run_bulk(
            input_file=input_file,
            top=args.top,
            min_stars=args.min_stars,
            since=args.since,
            dry_run=args.dry_run,
            preprocess_after=args.preprocess_after,
            progress_fn=_progress,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Always print the summary to stdout.
    print()
    print(render_report(report))

    if args.dry_run or args.no_report:
        return 0

    out = write_report(report, out_dir=Path(args.report_dir))
    print(f"\nWrote report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
