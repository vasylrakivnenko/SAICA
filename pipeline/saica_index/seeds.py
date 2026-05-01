"""Seed-list resolution for the SAICA Index.

One board:

  * ``popular_oss`` — read from ``data/saica_index/seed_repos.yml``
    (curated list of repos AI coding agents touch a lot).

The previous ``kg_tools`` auto-derived board (every supervisor in the
KG, audited against itself) was removed in v0.3.1.1. Its label
("supervisors supervising themselves") promised something the score
didn't measure — repo hygiene of maintainer teams ≠ tool quality —
and the board is conceptually inconsistent with v0.3.1's scope
("SAICA helps tools, doesn't evaluate them"). Trivially re-addable
if needed: restore ``load_kg_tools_board()`` from git history.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

Board = Literal["popular_oss"]

_REPO = Path(__file__).resolve().parent.parent.parent
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
    """Return all boards in one dict, ready for the runner."""
    return {
        "popular_oss": load_popular_oss_board(),
    }
