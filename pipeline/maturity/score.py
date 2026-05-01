"""Deterministic maturity-tier scoring (Stage 9 of the v2 ingestion pipeline).

DESIGN
------
Each tool gets a tier in ``{1A, 1B, 2A, 2B, 3, 4}`` derived from
observable facets in its YAML. The notation mirrors clinical-evidence
levels (PharmGKB, CPIC) so curators reading the KG can map the tier
to a familiar concept:

  * 1A — peer-reviewed paper *and* heavy substantive use *and* mature
         development signals
  * 1B — peer-reviewed paper *and* moderate corroboration
  * 2A — at least one paper citation *and* active development
  * 2B — implemented in research, less validation
  * 3  — active development, no scholarly grounding
  * 4  — experimental / single-author / low activity / abandoned

WHY DETERMINISTIC
-----------------
Calibrated thresholds cost a labeled holdout (Stage 0a of the v2 spec
— deferred). Until then we use editor-set thresholds that work today
and are explicit about being calibration-pending. Every facet is
observable from the tool YAML alone — no live API calls, no caching
issues, no flaky CI.

FACETS (only those we already record per-tool today)
----------------------------------------------------
+-----------------------------+--------+----------------------------------+
| Facet                       | Weight | Source field                     |
+-----------------------------+--------+----------------------------------+
| Cited in N papers           | 3      | ``cited_in`` (count)             |
| Documented in M sources     | 2      | ``documented_in`` (count)        |
| Evaluated on K benchmarks   | 2      | ``evaluated_on`` (count)         |
| GitHub stars (log-scaled)   | 2      | ``stars``                        |
| Recent commit (≤ 12 mo)     | 2      | ``last_updated``                 |
| Integration surfaces        | 0.5/ea | ``integration_surfaces`` (count) |
| Maturity status             | varies | ``maturity_status`` enum         |
+-----------------------------+--------+----------------------------------+

CALIBRATION NOTE
----------------
The current corpus has a sparse citation graph (~95% of tools have
``cited_in: []``), so without ``integration_surfaces`` as a spreading
facet the distribution collapsed to a single bin. Tier thresholds
below were set against the actual score distribution on the
2026-05-01 corpus (min=1.3, median=4.5, max=8.0) so each tier holds
~10-30% of the corpus — bell-ish, not flat. Re-tune when:
  (a) Stage 0a labeled holdout lands (Stage 5 brings real
      substantive-use signal), or
  (b) the corpus grows past ~200 tools and the distribution shifts.

``maturity_status`` is editorial input, not raw observation, so it
acts as a multiplicative gate (``deprecated``/``abandoned`` cap the
tier at 4 regardless of citations). The other facets sum into a raw
score; tier bins are set so the distribution across the current 87
tools roughly matches gut intuition (semgrep → 1B, brand-new
2-citation tool → 3).

KNOBS — calibrate against a labeled holdout when Stage 0a lands.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal, Optional

MaturityTier = Literal["1A", "1B", "2A", "2B", "3", "4"]

# Tunable constants. Names mirror the spec's facet names.
WEIGHT_PAPER_CITATION = 3.0     # per paper in cited_in, capped
WEIGHT_DOCUMENTED_IN = 2.0      # per documentation source, capped
WEIGHT_EVALUATED_ON = 2.0       # per benchmark, capped
WEIGHT_STARS_FACTOR = 2.0       # log10(stars + 1) * factor
WEIGHT_RECENT_COMMIT = 2.0      # binary (active or not)
WEIGHT_INTEGRATION_SURFACE = 0.5  # per declared surface, capped

CAP_PAPERS = 4                  # ≥4 papers all count the same
CAP_DOCS = 3
CAP_EVALS = 3
CAP_SURFACES = 5

RECENT_COMMIT_WINDOW_DAYS = 365

# Tier thresholds — score → tier. Order matters; first match wins.
# Calibrated against the 2026-05-01 corpus (87 tools); see CALIBRATION
# NOTE in the module docstring. Re-tune when Stage 0a holdout exists
# or the corpus grows substantially.
TIER_THRESHOLDS: list[tuple[float, MaturityTier]] = [
    (7.0, "1A"),
    (5.5, "1B"),
    (4.7, "2A"),
    (4.0, "2B"),
    (2.5, "3"),
    (0.0, "4"),
]

# Maturity-status caps. A tool flagged deprecated by the editor cannot
# be promoted by raw citations.
STATUS_TIER_CAP: dict[str, MaturityTier] = {
    "deprecated": "4",
    "abandoned": "4",
    "at_risk": "3",
    "experimental": "2B",
}


@dataclass
class MaturityScore:
    """Result of scoring one tool YAML."""

    tier: MaturityTier
    score: float
    facets: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure scorer
# ---------------------------------------------------------------------------


def _coerce_count(field_value: Any, *, cap: int) -> int:
    """Length of a list field, capped — None / non-list returns 0."""
    if not isinstance(field_value, list):
        return 0
    return min(len(field_value), cap)


def _stars_score(stars: Any) -> float:
    """log10(stars + 1) × WEIGHT_STARS_FACTOR. Caps at log10(100k) = 5."""
    if not isinstance(stars, (int, float)) or stars <= 0:
        return 0.0
    return min(5.0, math.log10(stars + 1)) * WEIGHT_STARS_FACTOR / 5.0


def _recent_commit_score(last_updated: Any, *, today: date) -> float:
    """1 × WEIGHT if ``last_updated`` is within RECENT_COMMIT_WINDOW_DAYS."""
    if isinstance(last_updated, str):
        try:
            last_updated = date.fromisoformat(last_updated)
        except ValueError:
            return 0.0
    if not isinstance(last_updated, date):
        return 0.0
    if today - last_updated <= timedelta(days=RECENT_COMMIT_WINDOW_DAYS):
        return WEIGHT_RECENT_COMMIT
    return 0.0


def compute_maturity(
    tool: dict[str, Any], *, today: Optional[date] = None
) -> MaturityScore:
    """Score one tool dict (loaded from its YAML) and bin to a tier.

    Pure — no I/O, no live API calls, no caching. Reads only the
    facets documented above. Missing fields contribute 0.
    """
    if today is None:
        today = date.today()

    facets: dict[str, float] = {}

    # Citation-shaped facets — count list lengths up to a cap.
    n_papers = _coerce_count(tool.get("cited_in"), cap=CAP_PAPERS)
    n_docs = _coerce_count(tool.get("documented_in"), cap=CAP_DOCS)
    n_evals = _coerce_count(tool.get("evaluated_on"), cap=CAP_EVALS)
    facets["paper_citations"] = n_papers * WEIGHT_PAPER_CITATION
    facets["documented_in"] = n_docs * WEIGHT_DOCUMENTED_IN
    facets["evaluated_on"] = n_evals * WEIGHT_EVALUATED_ON

    # Integration breadth — proxy for "how usable across stacks." Cheap
    # spreading facet that distinguishes well-rounded supervisors from
    # single-surface ones.
    n_surfaces = _coerce_count(tool.get("integration_surfaces"), cap=CAP_SURFACES)
    facets["integration_surfaces"] = n_surfaces * WEIGHT_INTEGRATION_SURFACE

    # Popularity proxy. Stars are noisy but cheap.
    facets["stars"] = _stars_score(tool.get("stars"))

    # Recency.
    facets["recent_commit"] = _recent_commit_score(
        tool.get("last_updated"), today=today
    )

    raw_score = sum(facets.values())

    # Bin to tier from thresholds.
    tier: MaturityTier = "4"
    for threshold, label in TIER_THRESHOLDS:
        if raw_score >= threshold:
            tier = label
            break

    # Editorial maturity-status cap.
    notes: list[str] = []
    status = str(tool.get("maturity_status") or "").lower()
    cap = STATUS_TIER_CAP.get(status)
    if cap is not None and _tier_rank(tier) < _tier_rank(cap):
        notes.append(
            f"capped from {tier} to {cap} by maturity_status={status!r}"
        )
        tier = cap

    return MaturityScore(
        tier=tier,
        score=round(raw_score, 2),
        facets={k: round(v, 2) for k, v in facets.items()},
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Override resolution (effective tier seen by callers)
# ---------------------------------------------------------------------------


def effective_tier(tool: dict[str, Any], *, today: Optional[date] = None) -> MaturityTier:
    """Return the tier downstream consumers should treat as authoritative.

    Resolution order:
      1. ``maturity_override.tier`` if set in the YAML (curator override).
      2. ``compute_maturity(tool).tier`` otherwise.

    The override is required to carry a justification (enforced by the
    Pydantic model — see ``MaturityOverride`` in ``pipeline.models``).
    """
    override = tool.get("maturity_override")
    if isinstance(override, dict):
        ot = override.get("tier")
        if isinstance(ot, str) and ot in {"1A", "1B", "2A", "2B", "3", "4"}:
            return ot  # type: ignore[return-value]
    return compute_maturity(tool, today=today).tier


# ---------------------------------------------------------------------------
# Helper: ordering (for the maturity-status cap)
# ---------------------------------------------------------------------------

_TIER_ORDER: tuple[MaturityTier, ...] = ("1A", "1B", "2A", "2B", "3", "4")


def _tier_rank(t: MaturityTier) -> int:
    """0 = best (1A), 5 = worst (4). Used to compare two tier labels."""
    return _TIER_ORDER.index(t)


__all__ = [
    "MaturityScore",
    "MaturityTier",
    "compute_maturity",
    "effective_tier",
]
