"""Seed-list resolution for the SAICA Index.

Two boards:

  * ``kg_tools``     — auto-derived from ``data/tools/*.yml``. Every tool
    that has a non-empty ``repository_url`` becomes a board entry. The
    list is regenerated on each run, so adding a tool to the KG
    automatically expands the leaderboard.

  * ``popular_oss``  — read from ``data/saica_index/seed_repos.yml``
    (curated by hand).

Both produce ``list[SeedRepo]``. The runner consumes them uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

Board = Literal["kg_tools", "popular_oss"]

_REPO = Path(__file__).resolve().parent.parent.parent
_TOOLS_DIR = _REPO / "data" / "tools"
_SEED_FILE = _REPO / "data" / "saica_index" / "seed_repos.yml"


@dataclass(frozen=True)
class SeedRepo:
    """One row of a leaderboard before scoring."""

    board: Board
    url: str
    category: str
    name: str  # display name (org/repo)
    note: str | None = None


# ---------------------------------------------------------------------------
# Board loaders
# ---------------------------------------------------------------------------


def load_kg_tools_board() -> list[SeedRepo]:
    """Every KG tool with a non-empty ``repository_url``."""
    out: list[SeedRepo] = []
    for yml in sorted(_TOOLS_DIR.glob("*.yml")):
        try:
            doc = yaml.safe_load(yml.read_text()) or {}
        except yaml.YAMLError:
            continue
        url = (doc.get("repository_url") or "").strip()
        if not url.startswith("https://github.com/"):
            continue
        # Skip any URL that points to a subdirectory or branch.
        if "/tree/" in url or "/blob/" in url:
            continue
        out.append(
            SeedRepo(
                board="kg_tools",
                url=url.rstrip("/"),
                category=str(doc.get("control_paradigm") or "uncategorised"),
                name=str(doc.get("id") or yml.stem),
                note=str(doc.get("tagline") or "") or None,
            )
        )
    return out


def load_popular_oss_board() -> list[SeedRepo]:
    """The curated ``data/saica_index/seed_repos.yml``."""
    if not _SEED_FILE.exists():
        return []
    raw = yaml.safe_load(_SEED_FILE.read_text()) or {}
    out: list[SeedRepo] = []
    for entry in raw.get("repos") or []:
        url = (entry.get("url") or "").strip().rstrip("/")
        if not url.startswith("https://github.com/"):
            continue
        owner_repo = url.removeprefix("https://github.com/")
        out.append(
            SeedRepo(
                board="popular_oss",
                url=url,
                category=str(entry.get("category") or "uncategorised"),
                name=owner_repo,
                note=entry.get("note"),
            )
        )
    return out


def load_all_boards() -> dict[Board, list[SeedRepo]]:
    """Return both boards in one dict, ready for the runner."""
    return {
        "kg_tools": load_kg_tools_board(),
        "popular_oss": load_popular_oss_board(),
    }
