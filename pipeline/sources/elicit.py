"""Elicit discovery source.

Hard per-day budget: 100 queries/day. A JSON counter at
`.pipeline/elicit_usage_YYYY-MM-DD.json` is incremented before each call; if
the count is >= 100, the call is refused.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Optional

from pipeline.config import PIPELINE_STATE_DIR, optional_env
from pipeline.sources._http import USER_AGENT, rate_limited_session

log = logging.getLogger(__name__)

ENDPOINT = "https://elicit.com/api/v1/search"
DAILY_BUDGET = 100
_USAGE_DIR = PIPELINE_STATE_DIR

# Elicit has no strict published limit beyond the daily budget; be polite.
_SESSION = rate_limited_session(min_interval_s=1.0, user_agent=USER_AGENT)


class ElicitBudgetExceeded(RuntimeError):
    """Raised when the daily Elicit budget has been hit."""


def _usage_path(today: Optional[date] = None) -> Path:
    d = today or date.today()
    return _USAGE_DIR / f"elicit_usage_{d.isoformat()}.json"


def _read_usage(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("count", 0))
    except (OSError, ValueError, TypeError):
        return 0


def _write_usage(path: Path, count: int) -> None:
    _USAGE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"count": count, "date": path.stem}), encoding="utf-8")


def _increment_budget() -> int:
    """Increment the day-counter. Raises if budget would be exceeded."""
    _USAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = _usage_path()
    count = _read_usage(path)
    if count >= DAILY_BUDGET:
        raise ElicitBudgetExceeded(
            f"Elicit daily budget hit ({count}/{DAILY_BUDGET}) — see {path}"
        )
    _write_usage(path, count + 1)
    return count + 1


def _extract_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull normalized records from whatever top-level shape Elicit returned."""
    results = (
        payload.get("results")
        or payload.get("papers")
        or payload.get("documents")
        or payload.get("data")
        or []
    )
    if not isinstance(results, list):
        return []
    records: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = (
            item.get("url")
            or item.get("paperUrl")
            or item.get("paper_url")
            or item.get("pdfUrl")
            or item.get("doi")
        )
        if isinstance(url, str) and url and not url.startswith("http") and "/" in url:
            # Looks like a DOI path
            url = f"https://doi.org/{url}"
        records.append(
            {
                "url": url,
                "title": item.get("title"),
                "snippet": item.get("abstract") or item.get("summary") or item.get("snippet"),
                "raw": item,
            }
        )
    return records


def search(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Query Elicit and persist normalized records.

    Refuses (returns []) if the daily budget has been hit. The budget is
    incremented BEFORE the HTTP call — a failed call still counts toward the
    quota, which matches how the upstream provider bills.
    """
    api_key = optional_env("ELICIT_API_KEY")
    if not api_key:
        log.error("ELICIT_API_KEY not set; skipping elicit.search")
        return []

    try:
        used = _increment_budget()
        log.info("elicit budget: %d/%d used today", used, DAILY_BUDGET)
    except ElicitBudgetExceeded as exc:
        log.warning("%s", exc)
        return []

    from pipeline.db import insert_raw_result

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {"query": query, "num_results": int(limit)}

    try:
        resp = _SESSION.post(ENDPOINT, json=body, headers=headers, timeout=90)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("elicit request failed for %r: %s", query, exc)
        return []

    records = _extract_records(payload)[:limit]
    inserted: list[dict[str, Any]] = []
    for r in records:
        try:
            row_id = insert_raw_result(
                "elicit",
                query,
                url=r.get("url"),
                title=r.get("title"),
                snippet=r.get("snippet"),
                raw_json={"query": query, "result": r["raw"]},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("elicit insert failed for %s: %s", r.get("url"), exc)
            continue
        if row_id is not None:
            inserted.append({"id": row_id, **r})
    return inserted
