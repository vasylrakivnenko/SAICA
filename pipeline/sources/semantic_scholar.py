"""Semantic Scholar `/paper/search` discovery source.

Rate limit: 1 req/s cumulative per API key. We enforce ≥1.2s between calls.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, Sequence

from pipeline.sources._http import USER_AGENT, load_env, rate_limited_session

log = logging.getLogger(__name__)

ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
DEFAULT_FIELDS = (
    "paperId",
    "title",
    "abstract",
    "year",
    "venue",
    "authors",
    "externalIds",
    "url",
    "openAccessPdf",
    "citationCount",
)

# 1 req/s cumulative. Use 1.2 to be safe.
_SESSION = rate_limited_session(min_interval_s=1.2, user_agent=USER_AGENT)


def _canonical_url(item: dict[str, Any]) -> Optional[str]:
    ext = item.get("externalIds") or {}
    if isinstance(ext, dict):
        doi = ext.get("DOI")
        if doi:
            return f"https://doi.org/{doi}"
        arx = ext.get("ArXiv")
        if arx:
            return f"https://arxiv.org/abs/{arx}"
    return item.get("url")


def search(
    query: str,
    *,
    limit: int = 15,
    fields: Optional[Sequence[str]] = None,
    year: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Search Semantic Scholar and persist normalized records.

    Returns the list of inserted records.
    """
    load_env()
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")

    from pipeline.db import insert_raw_result

    params: dict[str, Any] = {
        "query": query,
        "limit": min(int(limit), 100),
        "fields": ",".join(fields or DEFAULT_FIELDS),
    }
    if year:
        params["year"] = year

    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    try:
        resp = _SESSION.get(ENDPOINT, params=params, headers=headers, timeout=60)
        if resp.status_code == 429:
            log.warning("semantic_scholar 429 rate-limited on %r", query)
            return []
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("semantic_scholar request failed for %r: %s", query, exc)
        return []

    data = payload.get("data") or []
    inserted: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = _canonical_url(item)
        title = item.get("title")
        snippet = item.get("abstract")
        try:
            row_id = insert_raw_result(
                "semantic_scholar",
                query,
                url=url,
                title=title,
                snippet=snippet,
                raw_json={"query": query, "params": params, "result": item},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("semantic_scholar insert failed for %s: %s", url, exc)
            continue
        if row_id is not None:
            inserted.append(
                {
                    "id": row_id,
                    "url": url,
                    "title": title,
                    "snippet": snippet,
                    "raw": item,
                }
            )
    return inserted
