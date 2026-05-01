"""GitHub repository-search discovery source.

Uses `GET /search/repositories`. Authenticates with `GITHUB_TOKEN` if set
(5000/hr), else unauthenticated (60/hr). Also offers `fetch_readme(owner, repo)`
which inserts the decoded README into `raw_readmes`.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Optional

from pipeline.sources._http import USER_AGENT, load_env, rate_limited_session

log = logging.getLogger(__name__)

SEARCH_ENDPOINT = "https://api.github.com/search/repositories"
README_ENDPOINT = "https://api.github.com/repos/{owner}/{repo}/readme"
# GitHub search caps at 30/min with auth, 10/min without. Be polite.
_SESSION = rate_limited_session(min_interval_s=2.5, user_agent=USER_AGENT)


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _build_query(
    topic: Optional[str],
    language: Optional[str],
    min_stars: int,
    pushed_after: Optional[str],
) -> str:
    parts: list[str] = []
    if topic:
        for t in (topic,) if isinstance(topic, str) else topic:
            parts.append(f"topic:{t}")
    if language:
        parts.append(f"language:{language}")
    if min_stars:
        parts.append(f"stars:>{int(min_stars)}")
    if pushed_after:
        parts.append(f"pushed:>{pushed_after}")
    return " ".join(parts) if parts else "stars:>1000"


def search_code(
    topic: Optional[str] = None,
    language: Optional[str] = None,
    *,
    min_stars: int = 500,
    pushed_after: Optional[str] = None,
    per_page: int = 50,
    raw_query: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Search GitHub repositories and insert normalized records.

    Either pass structured filters (``topic``/``language``/``min_stars``/``pushed_after``)
    or a fully-formed ``raw_query`` string (used by the runbook).
    """
    load_env()

    from pipeline.db import insert_raw_result

    q = raw_query or _build_query(topic, language, min_stars, pushed_after)
    params: dict[str, Any] = {
        "q": q,
        "sort": "stars",
        "order": "desc",
        "per_page": min(int(per_page), 100),
    }

    try:
        resp = _SESSION.get(
            SEARCH_ENDPOINT, params=params, headers=_headers(), timeout=60
        )
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            log.warning("github search rate-limited on %r", q)
            return []
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("github search failed for %r: %s", q, exc)
        return []

    items = payload.get("items") or []
    inserted: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("html_url")
        title = item.get("full_name") or item.get("name")
        snippet = item.get("description")
        try:
            row_id = insert_raw_result(
                "github",
                q,
                url=url,
                title=title,
                snippet=snippet,
                raw_json={"query": q, "result": item},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("github insert failed for %s: %s", url, exc)
            continue
        if row_id is not None:
            inserted.append(
                {"id": row_id, "url": url, "title": title, "snippet": snippet}
            )
    return inserted


def fetch_readme(owner: str, repo: str) -> Optional[str]:
    """Fetch a repo's README, insert into raw_readmes, and return the decoded text."""
    load_env()
    from pipeline.db import insert_readme

    url = README_ENDPOINT.format(owner=owner, repo=repo)
    try:
        resp = _SESSION.get(url, headers=_headers(), timeout=60)
        if resp.status_code == 404:
            log.info("github: no README for %s/%s", owner, repo)
            return None
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("github readme fetch failed for %s/%s: %s", owner, repo, exc)
        return None

    content_b64 = payload.get("content") or ""
    try:
        content = (
            base64.b64decode(content_b64).decode("utf-8", errors="replace")
            if content_b64
            else ""
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("github readme decode failed for %s/%s: %s", owner, repo, exc)
        return None

    html_url = payload.get("html_url") or f"https://github.com/{owner}/{repo}#readme"
    try:
        insert_readme(html_url, content)
    except Exception as exc:  # noqa: BLE001
        log.warning("raw_readmes insert failed for %s: %s", html_url, exc)
    return content
