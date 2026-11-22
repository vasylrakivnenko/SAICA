"""Failure-mode priority and tool popularity: the two numbers the catalog
recommender multiplies.

Both are editorial inputs, not measurements:

* ``priority(fm)`` is ``likelihood × impact`` from
  ``data/failure_mode_priorities.yml`` (hand-set weights; that file says
  where they come from). Read through :mod:`pipeline.kg`.
* ``popularity(tool)`` is ``log10(stars + 1)`` plus a fixed adjustment for
  the tool's ``maturity_status``. It says how well known a tool is and
  whether it is maintained. It does not say how well it works; where
  SAICA-Bench measured a tool, that result is used elsewhere
  (:mod:`pipeline.maturity.evidence`).

Until 2026-11-21 this score was called "reliability" and had two more
terms: a bonus per citing paper (2 of 49 tools had one) and a bonus for
repositories on a May 2026 GitHub-trending snapshot (0 of 49 matched).
Both are removed. ``reliability`` is kept as an alias of ``popularity``
for callers that still use the old name.
"""

from __future__ import annotations

import math
from typing import Any

from pipeline import kg

# ---------------------------------------------------------------------------
# Priority — likelihood × impact, per failure mode
# ---------------------------------------------------------------------------

_DEFAULT_PRIORITY = 0.0  # for any failure mode not listed in the YAML


def priority(failure_mode: str) -> float:
    """Return likelihood × impact for one failure mode. Unknown ids give 0.0."""
    return kg.load_priorities().get(failure_mode, _DEFAULT_PRIORITY)


def all_priorities() -> dict[str, float]:
    """``{fm: priority(fm)}`` for every mode in the YAML, highest first."""
    return dict(sorted(kg.load_priorities().items(), key=lambda kv: -kv[1]))


# ---------------------------------------------------------------------------
# Popularity — per tool
# ---------------------------------------------------------------------------

_MATURITY_SCORE: dict[str, float] = {
    "stable": 0.5,
    "experimental": 0.2,
    "at_risk": -0.3,
    "deprecated": -1.0,
    "abandoned": -2.0,
}


def popularity(tool: dict[str, Any]) -> float:
    """``log10(stars + 1)`` plus the adjustment for ``maturity_status``.

    Ten times the stars adds 1.0. A deprecated tool with many stars still
    ranks below a maintained one with a few thousand.
    """
    stars = max(0.0, float(tool.get("stars") or 0))
    maturity = _MATURITY_SCORE.get(str(tool.get("maturity_status") or ""), 0.0)
    return math.log10(stars + 1.0) + maturity


# Old name, same function.
reliability = popularity


def coverage_value(tool: dict[str, Any], fms_covered: set[str]) -> float:
    """Σ priority(fm) over the modes in ``fms_covered`` that the tool is tagged for.

    The "what does this tool add?" term of the greedy pick. The caller
    passes the modes still open.
    """
    addressed = set(tool.get("addresses_failure_modes") or [])
    return sum(priority(fm) for fm in (addressed & fms_covered))


def reset_cache() -> None:
    """Test helper: forget the parsed KG (and with it the priorities)."""
    kg.reset()


__all__ = [
    "all_priorities",
    "coverage_value",
    "popularity",
    "priority",
    "reliability",
    "reset_cache",
]
