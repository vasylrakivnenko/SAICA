"""Failure-mode priority + tool reliability — shared scoring primitives.

The MCP recommender, the audit gap-analyzer, and the heatmap generator all
need a way to ask "how important is this FM?" and "how reliable is this
tool?". Both questions are answered here so the formulae stay in one place.

Inputs:
  - data/failure_mode_priorities.yml — likelihood + impact per FM, hand-
    edited and reviewable. See that file's header for the source policy.
  - The tool's own YAML — stars, trending status (via shared.trending),
    citation count, maturity_status.

Outputs:
  - priority(fm)   → float in [0, ~3]   (likelihood × impact)
  - reliability(t) → float in [~0, ~6]  (a log-stars + trending + citation
                                          + maturity combiner)

The combiners are kept *additive on log-stars*, *bounded on citations and
maturity*, so a single dimension can't dominate. Any change to weights here
should bump the version field in the YAML and document the rationale.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from pipeline.shared.trending import effective_stars, is_trending

REPO = Path(__file__).resolve().parents[2]
PRIORITIES_PATH = REPO / "data" / "failure_mode_priorities.yml"

# ---------------------------------------------------------------------------
# Priority — likelihood × impact, per FM
# ---------------------------------------------------------------------------

_DEFAULT_PRIORITY = 0.0  # for any FM not listed in the YAML


@lru_cache(maxsize=1)
def _load_priorities() -> dict[str, dict[str, Any]]:
    """Load and cache data/failure_mode_priorities.yml. Raises if file missing."""
    with PRIORITIES_PATH.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    return dict(doc.get("priorities") or {})


def priority(failure_mode: str) -> float:
    """Return likelihood × impact for a single FM. Unknown FMs return 0.0."""
    rec = _load_priorities().get(failure_mode)
    if not rec:
        return _DEFAULT_PRIORITY
    return float(rec.get("likelihood", 0.0)) * float(rec.get("impact", 0))


def all_priorities() -> dict[str, float]:
    """Return {fm: priority(fm)} for every FM in the YAML, sorted desc by priority."""
    raw = _load_priorities()
    return dict(
        sorted(
            ((fm, priority(fm)) for fm in raw),
            key=lambda kv: -kv[1],
        )
    )


def expected_priority_ordering() -> list[str]:
    """The ordering committed in the YAML — used by tests to detect drift."""
    with PRIORITIES_PATH.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    return list(doc.get("expected_priority_ordering") or [])


# ---------------------------------------------------------------------------
# Reliability — per tool
# ---------------------------------------------------------------------------

_MATURITY_SCORE: dict[str, float] = {
    "stable": 0.5,
    "experimental": 0.2,
    "at_risk": -0.3,
    "deprecated": -1.0,
    "abandoned": -2.0,
}


def reliability(tool: dict[str, Any]) -> float:
    """Return a per-tool reliability score, ~0 to ~6, higher is better.

    Combiner (kept simple and bounded):
      reliability = log10(effective_stars + 1)         # popularity, range 0..5
                  + 0.30 × len(cited_in)               # citation evidence, capped at 6
                  + maturity_score                     # see _MATURITY_SCORE
                  + (0.20 if trending else 0.0)        # secondary trending bump
                                                       # on top of the trending boost
                                                       # already baked into
                                                       # effective_stars

    Notes:
      - log10 of effective_stars means a 10× difference in popularity
        adds ~1.0 — meaningful but not crushing.
      - Citation contribution is capped because we don't want one
        massively-cited tool to dominate every recommendation.
      - Maturity can subtract — a deprecated tool with high stars still
        gets penalised below a fresh stable one.
    """
    es = max(0.0, float(effective_stars(tool)))
    log_pop = math.log10(es + 1.0)
    citations = min(6, len(tool.get("cited_in") or []))
    maturity = _MATURITY_SCORE.get(str(tool.get("maturity_status") or ""), 0.0)
    trending_bump = 0.20 if is_trending(tool) else 0.0
    return log_pop + 0.30 * citations + maturity + trending_bump


def coverage_value(tool: dict[str, Any], fms_covered: set[str]) -> float:
    """Σ priority(fm) over the FMs in ``fms_covered`` that this tool addresses.

    Used as the "what does this tool buy us?" term in greedy weighted set
    cover. Caller passes the set of FMs they still care about (e.g.
    full coverage = all 11; remaining-in-cover = those not yet covered).
    """
    addressed = set(tool.get("addresses_failure_modes") or [])
    return sum(priority(fm) for fm in (addressed & fms_covered))


def reset_cache() -> None:
    """Test helper — invalidate the priorities cache."""
    _load_priorities.cache_clear()


__all__ = [
    "all_priorities",
    "coverage_value",
    "expected_priority_ordering",
    "priority",
    "reliability",
    "reset_cache",
]
