"""Perplexity Sonar discovery source.

Calls the OpenAI-compatible chat-completion endpoint and extracts the web
search citations Perplexity returns alongside the assistant message. Each
citation is inserted into raw_search_results with source='perplexity'.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from pipeline.cost_caps import CallBudget
from pipeline.sources._http import USER_AGENT, load_env, rate_limited_session

log = logging.getLogger(__name__)

ENDPOINT = "https://api.perplexity.ai/chat/completions"
# Perplexity has no strict published rate limit for sonar-pro; be polite.
_SESSION = rate_limited_session(min_interval_s=0.5, user_agent=USER_AGENT)


def _extract_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize Perplexity web-search results into `url/title/snippet/raw` records.

    Perplexity returns citations in a few possible shapes depending on model.
    We try `search_results` (new), `citations` (legacy list of urls), and
    `choices[0].message.citations`. If only bare URLs exist, we keep them.
    """
    records: list[dict[str, Any]] = []

    # Preferred: structured search_results
    search_results = payload.get("search_results")
    if isinstance(search_results, list):
        for r in search_results:
            if not isinstance(r, dict):
                continue
            records.append(
                {
                    "url": r.get("url"),
                    "title": r.get("title") or r.get("name"),
                    "snippet": r.get("snippet")
                    or r.get("description")
                    or r.get("text"),
                    "raw": r,
                }
            )
        if records:
            return records

    # Fallback: top-level `citations` list (urls) + optional search_results_metadata
    citations = payload.get("citations")
    if isinstance(citations, list):
        for c in citations:
            if isinstance(c, str):
                records.append(
                    {"url": c, "title": None, "snippet": None, "raw": {"url": c}}
                )
            elif isinstance(c, dict):
                records.append(
                    {
                        "url": c.get("url"),
                        "title": c.get("title"),
                        "snippet": c.get("snippet") or c.get("text"),
                        "raw": c,
                    }
                )
        if records:
            return records

    # Fallback: inside message.citations
    try:
        msg = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        msg = None
    if isinstance(msg, dict):
        msg_cits = msg.get("citations")
        if isinstance(msg_cits, list):
            for c in msg_cits:
                if isinstance(c, str):
                    records.append(
                        {"url": c, "title": None, "snippet": None, "raw": {"url": c}}
                    )
                elif isinstance(c, dict):
                    records.append(
                        {
                            "url": c.get("url"),
                            "title": c.get("title"),
                            "snippet": c.get("snippet") or c.get("text"),
                            "raw": c,
                        }
                    )
    return records


def search(
    query: str,
    *,
    model: str = "sonar-pro",
    recency_filter: Optional[str] = None,
    limit: Optional[int] = None,
    budget: Optional[CallBudget] = None,
    session: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """Run a Perplexity web search and insert normalized citations.

    Returns the list of inserted records (those where insert_raw_result did
    not return None due to dedupe). Callers typically just len() it.

    When ``budget`` is non-None, one ``budget.consume`` is recorded for the
    HTTP call; a ``CostCapExceeded`` is propagated to the caller (the CLI
    catches it and exits with code 3). ``session`` is injectable for tests.
    """
    load_env()
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        log.error("PERPLEXITY_API_KEY not set; skipping perplexity.search")
        return []

    from pipeline.db import insert_raw_result  # imported lazily

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a research assistant. Answer concisely and ground "
                    "every claim in web sources. Prefer recent, authoritative results."
                ),
            },
            {"role": "user", "content": query},
        ],
        "return_citations": True,
    }
    if recency_filter:
        body["search_recency_filter"] = recency_filter

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Consume BEFORE dispatching so a tripped budget never puts a request on
    # the wire. The CostCapExceeded propagates to the caller (CLI exit 3).
    if budget is not None:
        budget.consume(call=True, tokens=0)

    http = session if session is not None else _SESSION
    try:
        resp = http.post(ENDPOINT, json=body, headers=headers, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("perplexity request failed for %r: %s", query, exc)
        return []

    records = _extract_records(payload)
    if limit is not None:
        records = records[:limit]

    inserted: list[dict[str, Any]] = []
    for r in records:
        try:
            row_id = insert_raw_result(
                "perplexity",
                query,
                url=r.get("url"),
                title=r.get("title"),
                snippet=r.get("snippet"),
                raw_json={"query": query, "model": model, "result": r["raw"]},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("perplexity insert failed for %s: %s", r.get("url"), exc)
            continue
        if row_id is not None:
            inserted.append({"id": row_id, **r})
    return inserted
