"""Orchestrator: turn recent arXiv submissions into ``data/arxiv_candidates.json``.

Walks the configured arXiv categories (default ``cs.SE``, ``cs.AI``,
``cs.LG``) for the last ``--lookback-days`` of submissions, dedupes by
arxiv id (a single paper often appears in multiple categories), and
classifies each unique entry as either:

* **matched_in_kg** — the arxiv id is already represented in
  ``data/papers/*.yml``. We emit a tiny pointer object so the consumer
  knows the paper resurfaced inside the lookback window.
* **new_candidates** — not in the KG yet. We score the title + abstract
  against :data:`pipeline.sources.arxiv_recent.RELEVANCE_KEYWORDS` and
  keep only entries whose score crosses
  :data:`pipeline.sources.arxiv_recent.RELEVANCE_THRESHOLD`. For each
  surviving candidate we infer SAICA failure-mode ids from the
  title+abstract (via :data:`pipeline.audit.kg.FM_KEYWORDS`) and propose
  a SAICA-style paper id (``<surname>-<year>-<short-slug>``) so editorial
  review can drop it straight into ``data/papers/``.

Outputs:

* ``data/arxiv_candidates.json`` — the live snapshot.
* ``research/arxiv_candidates_<YYYY-MM-DD>.md`` — human-readable triage
  report.

CLI::

    .venv/bin/python -m validator.screen_arxiv \\
        [--dry] [--no-network] [--threshold 0.4] \\
        [--lookback-days 30] [--categories cs.SE,cs.AI,cs.LG]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
from typing import Any, Iterable, Optional

from pipeline.audit.kg import REPO_ROOT
from pipeline.sources.arxiv_recent import (
    DEFAULT_CATEGORIES,
    DEFAULT_LOOKBACK_DAYS,
    RELEVANCE_THRESHOLD,
    abstract_excerpt,
    fetch_recent,
    infer_failure_modes,
    load_kg_arxiv_ids,
    match_against_kg,
    score_relevance,
    suggested_id,
    write_json,
)

log = logging.getLogger("validator.screen_arxiv")

DATA_DIR = REPO_ROOT / "data"
RESEARCH_DIR = REPO_ROOT / "research"
ARXIV_JSON = DATA_DIR / "arxiv_candidates.json"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def collect_categories(
    categories: Iterable[str],
    *,
    lookback_days: int,
    use_network: bool,
    today_iso: str,
) -> dict[str, dict[str, Any]]:
    """Fetch each category's recent feed, dedupe by arxiv id.

    Returns ``{arxiv_id: entry}``; an entry that surfaces in multiple
    categories accumulates them in its ``categories`` field, but the
    primary_category is preserved from the first sighting.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for cat in categories:
        items = fetch_recent(
            category=cat,
            lookback_days=lookback_days,
            today_iso=today_iso,
            use_network=use_network,
        )
        log.info("arxiv: %s -> %d entries", cat, len(items))
        for it in items:
            aid = it.get("arxiv_id") or ""
            if not aid:
                continue
            existing = by_id.get(aid)
            if existing is None:
                by_id[aid] = dict(it)
            else:
                for c in it.get("categories") or []:
                    if c not in existing.get("categories", []):
                        existing.setdefault("categories", []).append(c)
    return by_id


# ---------------------------------------------------------------------------
# Scoring + classification
# ---------------------------------------------------------------------------


def _year_of(entry: dict[str, Any]) -> int:
    pub = entry.get("first_published") or entry.get("updated") or ""
    if pub and len(pub) >= 4 and pub[:4].isdigit():
        return int(pub[:4])
    return _dt.date.today().year


def score_and_filter(
    new_entries: list[dict[str, Any]],
    *,
    threshold: float = RELEVANCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Score (title + abstract), drop below-threshold, decorate the rest.

    Each surviving entry gets:
    - ``relevance_score`` (rounded to 3 decimals)
    - ``suggested_failure_modes`` (sorted list of FM ids)
    - ``abstract_excerpt`` (~400 chars)
    - ``suggested_id``
    """
    out: list[dict[str, Any]] = []
    for entry in new_entries:
        title = entry.get("title") or ""
        abstract = entry.get("abstract") or ""
        scoring_text = f"{title}\n\n{abstract}".strip()
        score = score_relevance(scoring_text)
        if score < threshold:
            log.debug("arxiv: skip %s (score=%.2f)", entry.get("arxiv_id"), score)
            continue
        fms = infer_failure_modes(scoring_text)
        out.append(
            {
                "arxiv_id": entry.get("arxiv_id", ""),
                "title": title,
                "authors": entry.get("authors") or [],
                "first_published": entry.get("first_published", ""),
                "abstract_excerpt": abstract_excerpt(abstract, max_chars=400),
                "primary_category": entry.get("primary_category", ""),
                "categories": sorted(set(entry.get("categories") or [])),
                "relevance_score": round(score, 3),
                "suggested_failure_modes": fms,
                "suggested_id": suggested_id(
                    entry.get("authors") or [],
                    _year_of(entry),
                    title,
                ),
            }
        )
    out.sort(
        key=lambda r: (
            -float(r.get("relevance_score") or 0),
            r.get("first_published") or "",
        ),
        reverse=False,
    )
    # The compound key above sorts ascending by date within score; flip the
    # date so newest-first wins ties.
    out.sort(
        key=lambda r: (
            -float(r.get("relevance_score") or 0),
            -_date_int(r.get("first_published") or ""),
        )
    )
    return out


def _date_int(iso: str) -> int:
    """Return ``YYYYMMDD`` int for an ISO date, ``0`` if unparseable."""
    if not iso or len(iso) < 10:
        return 0
    s = iso[:10].replace("-", "")
    return int(s) if s.isdigit() else 0


# ---------------------------------------------------------------------------
# Snapshot + markdown
# ---------------------------------------------------------------------------


def build_snapshot(
    *,
    categories: list[str],
    lookback_days: int,
    matched: list[dict[str, Any]],
    new: list[dict[str, Any]],
    scraped_at: Optional[str] = None,
) -> dict[str, Any]:
    ts = scraped_at or _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "scraped_at": ts,
        "categories": categories,
        "lookback_days": lookback_days,
        "matched_in_kg": matched,
        "new_candidates": new,
    }


def render_markdown(
    matched: list[dict[str, Any]],
    new: list[dict[str, Any]],
    today_iso: str,
    *,
    categories: list[str],
    lookback_days: int,
) -> str:
    lines: list[str] = [
        f"# arXiv candidates - {today_iso}",
        "",
        f"_Categories: {', '.join(categories)} | Lookback: {lookback_days} days "
        f"| Threshold: {RELEVANCE_THRESHOLD:.2f}_",
        "",
        f"- **Matched in KG (resurfaced):** {len(matched)}",
        f"- **New candidates above threshold:** {len(new)}",
        "",
    ]
    if matched:
        lines.append("## Matched in KG")
        lines.append("")
        for m in matched:
            aid = m.get("arxiv_id", "")
            pid = m.get("paper_id", "")
            title = m.get("title") or "(no title)"
            date = m.get("first_published") or ""
            lines.append(
                f"- `{pid}` - arXiv [{aid}](https://arxiv.org/abs/{aid}) "
                f"({date}) - {title}"
            )
        lines.append("")
    if not new:
        lines.append("## New candidates")
        lines.append("")
        lines.append("_No new arXiv submissions cleared the relevance threshold._")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    lines.append("## New candidates")
    lines.append("")
    for c in new:
        aid = c.get("arxiv_id", "")
        title = c.get("title") or "(no title)"
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"- **arXiv id:** [{aid}](https://arxiv.org/abs/{aid})")
        lines.append(f"- **Suggested SAICA id:** `{c.get('suggested_id', '')}`")
        authors = c.get("authors") or []
        lines.append(
            "- **Authors:** "
            + (
                ", ".join(authors[:5]) + (" et al." if len(authors) > 5 else "")
                if authors
                else "(unknown)"
            )
        )
        lines.append(f"- **First published:** {c.get('first_published', '')}")
        cats = c.get("categories") or []
        lines.append(
            f"- **Primary category:** {c.get('primary_category', '')}"
            + (
                f" (also: {', '.join(x for x in cats if x != c.get('primary_category'))})"
                if len(cats) > 1
                else ""
            )
        )
        lines.append(f"- **Relevance score:** {c.get('relevance_score', 0)}")
        fms = c.get("suggested_failure_modes") or []
        lines.append(
            "- **Suggested failure modes:** "
            + (", ".join(fms) if fms else "_(none inferred - review manually)_")
        )
        lines.append("")
        lines.append("> " + (c.get("abstract_excerpt") or "(no excerpt)"))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_categories(arg: str) -> list[str]:
    out: list[str] = []
    for piece in (arg or "").split(","):
        s = piece.strip()
        if s:
            out.append(s)
    return out or list(DEFAULT_CATEGORIES)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Score + report but don't write data/arxiv_candidates.json or markdown.",
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Use only cached arXiv responses; skip network calls.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=RELEVANCE_THRESHOLD,
        help=f"Relevance score cutoff (default {RELEVANCE_THRESHOLD}).",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Days of arXiv submissions to scan (default {DEFAULT_LOOKBACK_DAYS}).",
    )
    parser.add_argument(
        "--categories",
        type=str,
        default=",".join(DEFAULT_CATEGORIES),
        help=(
            "Comma-separated arXiv categories "
            f"(default '{','.join(DEFAULT_CATEGORIES)}'). "
            "Add cs.CL to also scan computational linguistics."
        ),
    )
    args = parser.parse_args(argv)

    today_iso = _dt.date.today().isoformat()
    use_network = not args.no_network
    categories = _parse_categories(args.categories)

    kg_ids = load_kg_arxiv_ids()
    log.info("loaded %d KG papers with arxiv ids", len(kg_ids))

    by_id = collect_categories(
        categories,
        lookback_days=args.lookback_days,
        use_network=use_network,
        today_iso=today_iso,
    )
    log.info(
        "collected %d unique arXiv entries across %d categories",
        len(by_id),
        len(categories),
    )

    matched, new_raw = match_against_kg(list(by_id.values()), kg_ids)
    new = score_and_filter(new_raw, threshold=args.threshold)
    log.info(
        "classification: %d matched_in_kg, %d new_candidates above %.2f "
        "(of %d unique fetched)",
        len(matched),
        len(new),
        args.threshold,
        len(by_id),
    )

    snapshot = build_snapshot(
        categories=categories,
        lookback_days=args.lookback_days,
        matched=matched,
        new=new,
    )
    md = render_markdown(
        matched,
        new,
        today_iso,
        categories=categories,
        lookback_days=args.lookback_days,
    )

    if args.dry:
        log.info("--dry: skipping writes")
        return 0

    write_json(ARXIV_JSON, snapshot)
    md_path = RESEARCH_DIR / f"arxiv_candidates_{today_iso}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    log.info("wrote %s", ARXIV_JSON)
    log.info("wrote %s", md_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
