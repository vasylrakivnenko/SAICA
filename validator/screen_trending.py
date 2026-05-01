"""Orchestrator: turn github.com/trending into ``data/trending.json``.

Reads the KG tool index, fetches the eight trending pages
(``daily`` + ``weekly`` × ``all/python/typescript/rust``), classifies each
unique repo as either:

* **matched_in_kg** — the repo is already in ``data/tools/*.yml``. We emit
  a small object so the consumer can render a "trending now" badge without
  re-loading the YAML.
* **new_candidates** — not in the KG yet. We fetch the README, score it
  against :data:`pipeline.sources.github_trending.RELEVANCE_KEYWORDS`, and
  keep only repos whose score crosses
  :data:`pipeline.sources.github_trending.RELEVANCE_THRESHOLD`. For each
  surviving candidate we infer SAICA failure-mode ids from the README (via
  :data:`pipeline.audit.kg.FM_KEYWORDS`) so editorial review can confirm
  the taxonomy hits.

Outputs:

* ``data/trending.json`` — the live snapshot consumed by
  :mod:`pipeline.shared.trending`.
* ``research/trending_candidates_<YYYY-MM-DD>.md`` — human-readable report
  of new candidates for editorial triage.

CLI::

    .venv/bin/python -m validator.screen_trending [--dry] [--no-network]

``--dry``        — score + report but don't write the snapshot or markdown.
``--no-network`` — read trending pages from ``.cache/trending/`` only; skip
  README fetches. Useful in CI / offline tests.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sys
from typing import Any, Iterable, Optional

from pipeline.audit.kg import REPO_ROOT, load_tool_index
from pipeline.sources.github_trending import (
    RELEVANCE_THRESHOLD,
    fetch_readme,
    fetch_trending_page,
    infer_failure_modes,
    iter_default_pages,
    normalize_repository_url,
    page_source_label,
    readme_excerpt,
    score_relevance,
    write_json,
)

log = logging.getLogger("validator.screen_trending")

DATA_DIR = REPO_ROOT / "data"
RESEARCH_DIR = REPO_ROOT / "research"
TRENDING_JSON = DATA_DIR / "trending.json"


# ---------------------------------------------------------------------------
# KG matching
# ---------------------------------------------------------------------------


def build_url_to_tool_id(tool_index: dict[str, dict]) -> dict[str, str]:
    """Reverse map: normalized ``repository_url`` → ``tool_id``."""
    out: dict[str, str] = {}
    for tid, tool in tool_index.items():
        url = tool.get("repository_url")
        if not isinstance(url, str) or not url:
            continue
        out[normalize_repository_url(url)] = tid
    return out


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _trending_in(language: Optional[str], since: str) -> str:
    """Compact label for the per-candidate ``trending_in`` array."""
    if language is None:
        return since
    return f"{language}:{since}"


def collect_pages(
    pages: Iterable[tuple[Optional[str], str]],
    *,
    use_network: bool,
    today_iso: str,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Fetch each ``(language, since)`` page, dedupe by normalized URL.

    Returns ``(by_url, sources)``:

    * ``by_url`` — ``{normalized_url: candidate_dict}`` where each
      candidate gathers a ``trending_in`` list across the slices that
      surfaced it.
    * ``sources`` — labels of the pages we *attempted* (so the snapshot's
      ``sources`` field documents the input set even if a particular page
      came back empty).
    """
    by_url: dict[str, dict[str, Any]] = {}
    sources: list[str] = []
    for language, since in pages:
        sources.append(page_source_label(language, since))
        items = fetch_trending_page(
            language=language,
            since=since,
            today_iso=today_iso,
            use_network=use_network,
        )
        log.info(
            "trending: %s ?since=%s -> %d repos",
            language or "all",
            since,
            len(items),
        )
        slice_label = _trending_in(language, since)
        for item in items:
            url_n = normalize_repository_url(item.get("repository_url", ""))
            if not url_n:
                continue
            existing = by_url.get(url_n)
            if existing is None:
                by_url[url_n] = {
                    **item,
                    "repository_url": url_n,
                    "trending_in": [slice_label],
                }
            else:
                if slice_label not in existing["trending_in"]:
                    existing["trending_in"].append(slice_label)
                # Keep the highest stars seen across slices (GitHub
                # sometimes shows slightly different counts per page).
                if int(item.get("stars_total") or 0) > int(
                    existing.get("stars_total") or 0
                ):
                    existing["stars_total"] = int(item.get("stars_total") or 0)
                if not existing.get("description") and item.get("description"):
                    existing["description"] = item["description"]
                if not existing.get("language") and item.get("language"):
                    existing["language"] = item["language"]
    return by_url, sources


# ---------------------------------------------------------------------------
# Classification + scoring
# ---------------------------------------------------------------------------


def classify(
    by_url: dict[str, dict[str, Any]],
    url_to_tool_id: dict[str, str],
    *,
    use_network: bool,
    threshold: float = RELEVANCE_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split candidates into ``matched_in_kg`` and ``new_candidates``."""
    matched: list[dict[str, Any]] = []
    new: list[dict[str, Any]] = []

    for url_n, item in by_url.items():
        trending_in = sorted(set(item.get("trending_in") or []))
        tool_id = url_to_tool_id.get(url_n)
        if tool_id:
            matched.append(
                {
                    "tool_id": tool_id,
                    "repository_url": url_n,
                    "stars": int(item.get("stars_total") or 0),
                    "trending_in": trending_in,
                }
            )
            continue

        # New candidate — fetch README + score.
        description = item.get("description") or ""
        readme_text = fetch_readme(
            url_n,
            use_network=use_network,
            description_fallback=description,
        )
        # Score against README + description (description carries signal too).
        scoring_text = f"{description}\n\n{readme_text}".strip()
        score = score_relevance(scoring_text)
        if score < threshold:
            log.debug("trending: skip %s (score=%.2f)", url_n, score)
            continue

        fms = infer_failure_modes(scoring_text)
        excerpt = readme_excerpt(readme_text or description, max_chars=400)
        owner_repo = url_n.rsplit("/", 1)[-1] if "/" in url_n else url_n
        new.append(
            {
                "repository_url": url_n,
                "name": owner_repo,
                "stars": int(item.get("stars_total") or 0),
                "primary_language": item.get("language") or "",
                "trending_in": trending_in,
                "relevance_score": round(score, 3),
                "suggested_failure_modes": fms,
                "readme_excerpt": excerpt,
            }
        )

    matched.sort(key=lambda r: (-int(r.get("stars") or 0), r["repository_url"]))
    new.sort(
        key=lambda r: (-float(r.get("relevance_score") or 0), -int(r.get("stars") or 0))
    )
    return matched, new


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def build_snapshot(
    *,
    by_url: dict[str, dict[str, Any]],
    matched: list[dict[str, Any]],
    new: list[dict[str, Any]],
    sources: list[str],
    scraped_at: Optional[str] = None,
) -> dict[str, Any]:
    ts = scraped_at or _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    # ``trending_repository_urls`` is the *flat* canonical list — both
    # matched-in-KG and new candidates that survived relevance go here, so
    # the consumer (pipeline.shared.trending) can boost matched tools.
    matched_urls = [m["repository_url"] for m in matched]
    new_urls = [c["repository_url"] for c in new]
    trending_urls = sorted(set(matched_urls) | set(new_urls))
    return {
        "scraped_at": ts,
        "sources": sources,
        "trending_repository_urls": trending_urls,
        "matched_in_kg": matched,
        "new_candidates": new,
    }


def render_markdown(new: list[dict[str, Any]], today_iso: str) -> str:
    if not new:
        return (
            f"# Trending candidates — {today_iso}\n\n"
            "_No new repositories cleared the relevance threshold._\n"
        )
    lines: list[str] = [
        f"# Trending candidates — {today_iso}",
        "",
        f"_{len(new)} repository(ies) above relevance threshold "
        f"{RELEVANCE_THRESHOLD:.2f}; sorted by relevance × stars._",
        "",
    ]
    for c in new:
        lines.append(f"## {c['name']}")
        lines.append("")
        lines.append(f"- **Repository:** {c['repository_url']}")
        lines.append(f"- **Stars:** {c['stars']:,}")
        lang = c.get("primary_language") or "(unknown)"
        lines.append(f"- **Primary language:** {lang}")
        lines.append(
            f"- **Trending in:** {', '.join(c.get('trending_in') or []) or '(none)'}"
        )
        lines.append(f"- **Relevance score:** {c['relevance_score']}")
        fms = c.get("suggested_failure_modes") or []
        lines.append(
            "- **Suggested failure modes:** "
            + (", ".join(fms) if fms else "_(none inferred — review manually)_")
        )
        lines.append("")
        lines.append("> " + (c.get("readme_excerpt") or "(no excerpt)"))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Score + report but don't write data/trending.json or the markdown.",
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Use only cached trending pages; skip README fetches.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=RELEVANCE_THRESHOLD,
        help=f"Relevance score cutoff (default {RELEVANCE_THRESHOLD}).",
    )
    args = parser.parse_args(argv)

    today_iso = _dt.date.today().isoformat()
    use_network = not args.no_network

    tool_index = load_tool_index()
    url_to_tool_id = build_url_to_tool_id(tool_index)
    log.info("loaded %d KG tools", len(url_to_tool_id))

    by_url, sources = collect_pages(
        iter_default_pages(),
        use_network=use_network,
        today_iso=today_iso,
    )
    log.info(
        "collected %d unique trending repos across %d pages", len(by_url), len(sources)
    )

    matched, new = classify(
        by_url,
        url_to_tool_id,
        use_network=use_network,
        threshold=args.threshold,
    )
    log.info(
        "classification: %d matched_in_kg, %d new_candidates above %.2f",
        len(matched),
        len(new),
        args.threshold,
    )

    snapshot = build_snapshot(
        by_url=by_url,
        matched=matched,
        new=new,
        sources=sources,
    )
    md = render_markdown(new, today_iso)

    if args.dry:
        log.info("--dry: skipping writes")
        return 0

    write_json(TRENDING_JSON, snapshot)
    md_path = RESEARCH_DIR / f"trending_candidates_{today_iso}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    log.info("wrote %s", TRENDING_JSON)
    log.info("wrote %s", md_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
