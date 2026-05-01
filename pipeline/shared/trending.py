"""Trending boost for tool ranking.

The mining pipeline writes ``data/trending.json`` — a snapshot of repos
currently on github.com/trending that look relevant to AI-coding-agent
supervision. This module is the read-side: it loads the snapshot once
per process and exposes a ``effective_stars(tool)`` helper that boosts
a trending tool's effective rank above a non-trending peer with up to
+30% more raw stars.

Why a multiplier and not a flat add: a flat boost would surface trending
nano-projects above well-established tools on raw popularity. A 1.43x
multiplier means a trending tool with 1k stars beats a non-trending tool
with up to ~1.43k stars (~+43%) — close enough to the user's "+/-30%"
rule that the tie-break is decisive at the boundary.

If ``data/trending.json`` is missing or empty (e.g. on a fresh clone
before the trending scraper has ever run), the boost is a no-op:
:func:`effective_stars` returns the raw star count and
:func:`is_trending` returns ``False`` for everything.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
TRENDING_PATH = REPO / "data" / "trending.json"

# Multiplier for the trending boost. 1.43 is chosen so that a trending tool
# wins against a non-trending peer with up to +30% more raw stars
# (1 / 0.7 ≈ 1.43). Tunable; document the formula if you change it.
TRENDING_BOOST: float = 1.43


@lru_cache(maxsize=1)
def _load_trending_snapshot() -> dict[str, Any]:
    """Load the trending snapshot. Returns ``{}`` if the file is missing."""
    if not TRENDING_PATH.exists():
        return {}
    try:
        with TRENDING_PATH.open(encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(doc, dict):
        return {}
    return doc


@lru_cache(maxsize=1)
def trending_repository_urls() -> frozenset[str]:
    """Return the set of repository_urls currently on github.com/trending.

    Reads from ``data/trending.json`` under the key ``trending_repository_urls``
    (a list of canonical https URLs). Missing or malformed snapshots return
    an empty frozenset (i.e. the boost is a silent no-op).
    """
    snap = _load_trending_snapshot()
    urls = snap.get("trending_repository_urls") or []
    if not isinstance(urls, list):
        return frozenset()
    return frozenset(str(u) for u in urls if isinstance(u, str))


def is_trending(tool: dict[str, Any]) -> bool:
    """True if ``tool``'s ``repository_url`` is in the current trending snapshot."""
    url = tool.get("repository_url")
    if not isinstance(url, str):
        return False
    return url in trending_repository_urls()


def effective_stars(tool: dict[str, Any]) -> float:
    """Return star count with the trending boost applied (no-op if not trending)."""
    raw = float(tool.get("stars") or 0)
    return raw * TRENDING_BOOST if is_trending(tool) else raw


def reset_cache() -> None:
    """Test helper — drop the cached trending snapshot so a new file is picked up."""
    _load_trending_snapshot.cache_clear()
    trending_repository_urls.cache_clear()


__all__ = [
    "TRENDING_BOOST",
    "effective_stars",
    "is_trending",
    "reset_cache",
    "trending_repository_urls",
]
