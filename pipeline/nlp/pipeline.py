"""Orchestrator: read raw_search_results, classify, dedupe, upsert candidates.

Note on the ``pipeline.db`` contract: the contract stated in this agent's brief
(``raw_results_by_query(conn, since=...)``, ``upsert_candidate_* -> bool``)
doesn't match what ``pipeline/db.py`` ships with today
(``raw_results_by_query(source, query)``, ``upsert_candidate_* -> int``). This
module works with the *actual* ``db.py``: we iterate ``raw_search_results``
directly via ``get_conn()`` and track created-vs-updated by checking for
existing ``source_url`` rows before calling ``upsert_candidate_*``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Iterator, Optional

from pipeline.nlp.preprocess import (
    LOW_RELEVANCE_THRESHOLD,
    PROMOTION_THRESHOLD,
    canonical_url,
    classify_kind,
    extract_arxiv_ids,
    extract_dois,
    extract_github_urls,
    keyword_hits,
    relevance_score,
)


# Retained for back-compat with external callers; points at the new promotion
# threshold defined in ``pipeline.nlp.preprocess``.
MIN_RELEVANCE = PROMOTION_THRESHOLD


@dataclass
class RunSummary:
    rows_processed: int = 0
    candidates_created: int = 0
    candidates_updated: int = 0
    candidates_low_relevance: int = 0
    skipped_low_relevance: int = 0
    skipped_unclassified: int = 0
    skipped_no_source_url: int = 0
    errors: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        return (
            f"rows_processed={self.rows_processed} "
            f"candidates_created={self.candidates_created} "
            f"candidates_updated={self.candidates_updated} "
            f"candidates_low_relevance={self.candidates_low_relevance} "
            f"skipped_low_relevance={self.skipped_low_relevance} "
            f"skipped_unclassified={self.skipped_unclassified} "
            f"skipped_no_source_url={self.skipped_no_source_url} "
            f"errors={len(self.errors)}"
        )


def _kebab(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name or "").strip("-").lower()
    return s or "unnamed"


def _proposed_tool_id(github_url: str, title: Optional[str]) -> str:
    # github.com/owner/repo -> 'repo' kebab-cased.
    m = re.match(
        r"https?://github\.com/[^/]+/([^/?#]+)",
        github_url or "",
        re.IGNORECASE,
    )
    if m:
        return _kebab(m.group(1))
    if title:
        return _kebab(title)
    return _kebab(github_url)


def _proposed_paper_id(arxiv_id: Optional[str], doi: Optional[str], title: Optional[str]) -> str:
    if arxiv_id:
        return f"arxiv-{_kebab(arxiv_id)}"
    if doi:
        return f"doi-{_kebab(doi)}"
    return _kebab(title or "paper")


def _row_text(raw_row: dict) -> str:
    return "\n".join(
        str(raw_row.get(f) or "") for f in ("title", "snippet", "url")
    )


def _iter_raw_results(conn, since: Optional[datetime]) -> Iterator[dict]:
    """Stream ``raw_search_results`` rows, optionally filtered by ``fetched_at``."""
    from psycopg.rows import dict_row

    if since is None:
        sql = (
            "SELECT id, source, query, url, title, snippet, raw_json, "
            "fetched_at FROM raw_search_results ORDER BY fetched_at ASC"
        )
        params: tuple[Any, ...] = ()
    else:
        sql = (
            "SELECT id, source, query, url, title, snippet, raw_json, "
            "fetched_at FROM raw_search_results "
            "WHERE fetched_at >= %s ORDER BY fetched_at ASC"
        )
        params = (since,)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        for row in cur:
            yield row


def _source_url_exists(conn, table: str, source_url: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {table} WHERE source_url = %s LIMIT 1",
            (source_url,),
        )
        return cur.fetchone() is not None


def _mark_low_relevance(conn, table: str, source_url: str) -> None:
    """Set ``status='low_relevance'`` on a newly-written candidate row, but
    only if it's still ``pending`` (never downgrade a row a reviewer has
    already acted on)."""
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {table} SET status = 'low_relevance' "
            f"WHERE source_url = %s AND status = 'pending'",
            (source_url,),
        )
        conn.commit()


def _process_row(raw_row: dict, summary: RunSummary, *, conn, _db) -> None:
    """Classify + upsert one raw row."""
    summary.rows_processed += 1

    score = relevance_score(raw_row)
    if score < LOW_RELEVANCE_THRESHOLD:
        summary.skipped_low_relevance += 1
        return

    is_low_relevance = score < PROMOTION_THRESHOLD

    kind = classify_kind(raw_row)
    if kind not in ("tool", "paper"):
        summary.skipped_unclassified += 1
        return

    # Borderline rows are only written for tool candidates (reviewers see them
    # as a separate ``status='low_relevance'`` pool). Papers below the
    # promotion threshold are dropped — papers' entity signals (arxiv/doi) are
    # already strong enough that the few we'd rescue aren't worth the noise.
    if is_low_relevance and kind != "tool":
        summary.skipped_low_relevance += 1
        return

    text = _row_text(raw_row)
    hits = keyword_hits(text)
    nlp_tags = {
        "keyword_hits": hits,
        "relevance": round(score, 3),
        "source": raw_row.get("source"),
        "query": raw_row.get("query"),
    }
    if is_low_relevance:
        nlp_tags["low_relevance"] = True

    if kind == "tool":
        github_urls = extract_github_urls(text)
        if not github_urls:
            url = raw_row.get("url") or ""
            if "github.com" in url.lower():
                github_urls = extract_github_urls(url)
        if github_urls:
            source_url = canonical_url(github_urls[0])
            proposed_id = _proposed_tool_id(github_urls[0], raw_row.get("title"))
        elif is_low_relevance and raw_row.get("url"):
            # Borderline tool with no github entity — write it at the page URL
            # so reviewers can see the borderline pool. Only for low_relevance
            # rows so we never extract a listicle blog URL as if it were a
            # real repo.
            source_url = canonical_url(raw_row["url"])
            proposed_id = _proposed_tool_id(source_url, raw_row.get("title"))
        else:
            summary.skipped_no_source_url += 1
            return
        name = (raw_row.get("title") or proposed_id).strip()
        summary_text = (raw_row.get("snippet") or "").strip() or None
        existed = _source_url_exists(conn, "candidate_tools", source_url)
        _db.upsert_candidate_tool(
            source_url=source_url,
            proposed_id=proposed_id,
            name=name,
            summary=summary_text,
            nlp_tags=nlp_tags,
        )
        if is_low_relevance and not existed:
            # Only stamp the status on fresh rows — don't override a row that
            # already matured past 'pending'.
            _mark_low_relevance(conn, "candidate_tools", source_url)
            summary.candidates_low_relevance += 1
        elif existed:
            summary.candidates_updated += 1
        else:
            summary.candidates_created += 1
        return

    # paper
    arxiv_ids = extract_arxiv_ids(text)
    dois = extract_dois(text)
    arxiv_id = arxiv_ids[0] if arxiv_ids else None
    doi = dois[0] if dois else None
    row_url = raw_row.get("url") or ""
    if arxiv_id:
        source_url = f"https://arxiv.org/abs/{arxiv_id}"
    elif doi:
        source_url = f"https://doi.org/{doi}"
    elif row_url:
        source_url = canonical_url(row_url)
    else:
        summary.skipped_no_source_url += 1
        return

    proposed_id = _proposed_paper_id(arxiv_id, doi, raw_row.get("title"))
    title = (raw_row.get("title") or "").strip() or None
    existed = _source_url_exists(conn, "candidate_papers", source_url)
    _db.upsert_candidate_paper(
        source_url=source_url,
        proposed_id=proposed_id,
        title=title,
        arxiv_id=arxiv_id,
        doi=doi,
        nlp_tags=nlp_tags,
    )
    if existed:
        summary.candidates_updated += 1
    else:
        summary.candidates_created += 1


def run(since: Optional[datetime] = None) -> RunSummary:
    """Iterate raw_search_results rows, classify + upsert candidates.

    Returns a :class:`RunSummary`. Prints a summary line to stdout.
    """
    from pipeline import db  # local import: keeps CLI --help usable without psycopg.

    summary = RunSummary()
    with db.get_conn() as conn:
        for raw_row in _iter_raw_results(conn, since):
            try:
                _process_row(raw_row, summary, conn=conn, _db=db)
            except Exception as exc:  # pragma: no cover (defensive)
                summary.errors.append(f"row {raw_row.get('id')!r}: {exc!r}")

    print(f"[preprocess.run] {summary.as_text()}")
    return summary
