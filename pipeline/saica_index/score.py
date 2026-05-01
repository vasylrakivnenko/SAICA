"""SAICA Index — scoring formula (single source of truth).

This module turns a ``pipeline.audit.schemas.AuditReport`` into a single
number in ``[0, 1]``, a letter grade, and the side-metadata the
leaderboard page renders alongside.

DESIGN GOAL
-----------
The score answers a *practitioner* question:

    "For the AI-coding failure modes that matter most, does this repo
    have credible defenses installed?"

It deliberately does NOT measure:
  * tool count (a repo with 12 tools that all guard ``security_vulnerability``
    is worse-supervised than one with 5 tools spread across 8 FMs)
  * code quality, test pass rate, or anything orthogonal to supervision
  * the *correctness* of how those tools are configured (we trust the
    declared coverage from the KG)

FORMULA
-------

Step 1 — per-failure-mode coverage ``c(f) ∈ [0, 1]``
    For each of the 11 failure modes ``f``, look at every supervision
    tool the audit detected that declares coverage for ``f``. Take the
    *best* evidence tier across those tools (tier ∈ {0, 1, 2, 3} from
    the audit's coverage grid):

        tier 0  →  c(f) = 0.00   (no tool addresses it)
        tier 1  →  c(f) = 0.40   (declared, no rationale evidence)
        tier 2  →  c(f) = 0.70   (rationale-level evidence)
        tier 3  →  c(f) = 1.00   (citation-level evidence)

    Plus a paradigm-diversity bonus: ``+0.10`` if **≥ 2 distinct
    control paradigms** (prevention/detection/correction/recovery) cover
    ``f``. Capped at 1.0.

    Why diversity matters: layered defence is qualitatively stronger
    than a single paradigm. Having both prevention *and* detection for
    ``security_vulnerability`` is materially better than either alone.

Step 2 — aggregate, weighted by FM priority
    Priorities live in ``data/failure_mode_priorities.yml`` as
    ``likelihood × impact`` (see file header for sourcing). Compute:

        score = Σ priority(f) × c(f)  /  Σ priority(f)

    The denominator ensures the score is always ``∈ [0, 1]`` regardless
    of how the priority table is later rescaled.

Step 3 — letter grade
    Thresholds are deliberately harsh — a freshly-init'd repo should be
    F, our own well-supervised repo should sit around C/B, and an A
    should feel earned (i.e. broad coverage with high evidence tiers).

        ≥ 0.80 → A    "broad coverage, high evidence"
        ≥ 0.60 → B    "most FMs covered, some shallow"
        ≥ 0.40 → C    "half-covered, gaps in priorities"
        ≥ 0.20 → D    "minimal supervision"
        <  0.20 → F   "effectively unsupervised"

KNOBS
-----
The tier weights (0.40 / 0.70 / 1.00), the paradigm bonus (0.10), and
the grade thresholds (0.80 / 0.60 / 0.40 / 0.20) are gut-calibrated, not
empirically fitted. Any future calibration should:

  1. Audit a held-out set of well-known repos by hand,
  2. Have humans assign expected grades,
  3. Pick parameters that minimise disagreement.

Until then, the values are constants at the top of this module so any
recalibration is one PR.

The formula is intentionally simple: the leaderboard page renders the
*per-paradigm counts* alongside the score, so a reader can always see
the structure underneath the grade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from pipeline.audit.schemas import AuditReport, CoverageCell, Paradigm

# ---------------------------------------------------------------------------
# Tunable constants — see KNOBS section in the module docstring.
# ---------------------------------------------------------------------------

TIER_WEIGHT: dict[int, float] = {
    0: 0.00,
    1: 0.40,
    2: 0.70,
    3: 1.00,
}

PARADIGM_DIVERSITY_BONUS: float = 0.10
"""Added to ``c(f)`` when ≥2 paradigms cover the FM, capped at 1.0."""

LetterGrade = Literal["A", "B", "C", "D", "F"]

GRADE_THRESHOLDS: list[tuple[float, LetterGrade]] = [
    (0.80, "A"),
    (0.60, "B"),
    (0.40, "C"),
    (0.20, "D"),
    (0.00, "F"),
]


# ---------------------------------------------------------------------------
# Priority loader (cached — same file, all callers).
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_priorities(path: Path | None = None) -> dict[str, float]:
    """Load ``failure_mode_priorities.yml`` and return ``{fm_id: priority}``.

    ``priority = likelihood × impact``.
    """
    if path is None:
        path = (
            Path(__file__).resolve().parent.parent.parent
            / "data"
            / "failure_mode_priorities.yml"
        )
    raw = yaml.safe_load(path.read_text())
    out: dict[str, float] = {}
    for fm_id, rec in (raw.get("priorities") or {}).items():
        likelihood = float(rec.get("likelihood", 0.0))
        impact = float(rec.get("impact", 0))
        out[fm_id] = likelihood * impact
    return out


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class RepoScore:
    """The result of scoring one ``AuditReport``."""

    score: float  # ∈ [0, 1]
    grade: LetterGrade
    per_fm: dict[str, float]  # fm_id → c(f) ∈ [0, 1]
    paradigm_counts: dict[str, int]  # paradigm → number of FMs it covers
    is_balanced: bool  # True iff all 4 paradigms cover ≥1 FM
    failure_modes_covered: int
    failure_modes_total: int
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def grade_for(score: float) -> LetterGrade:
    """Map ``score ∈ [0, 1]`` to a letter grade per ``GRADE_THRESHOLDS``."""
    for threshold, letter in GRADE_THRESHOLDS:
        if score >= threshold:
            return letter
    return "F"  # unreachable; defensive


def _per_fm_score(cells_for_fm: list[CoverageCell]) -> float:
    """Compute ``c(f)`` for one failure mode from its coverage cells.

    Each cell is one (FM, paradigm) intersection with a ``tier``. We:
      * take the best tier across paradigms,
      * map it to a base score via ``TIER_WEIGHT``,
      * add the paradigm-diversity bonus when ≥2 paradigms have tier ≥ 1.

    Returns 0.0 when no cell has any non-zero tier.
    """
    if not cells_for_fm:
        return 0.0

    best_tier = max(cell.tier for cell in cells_for_fm)
    base = TIER_WEIGHT[best_tier]
    if base == 0.0:
        return 0.0

    paradigms_with_coverage = {cell.paradigm for cell in cells_for_fm if cell.tier >= 1}
    if len(paradigms_with_coverage) >= 2:
        return min(1.0, base + PARADIGM_DIVERSITY_BONUS)
    return base


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def score_report(
    report: AuditReport,
    *,
    priorities: dict[str, float] | None = None,
) -> RepoScore:
    """Score one ``AuditReport`` per the formula in this module's docstring.

    ``priorities`` can be passed for tests; defaults to the cached
    ``failure_mode_priorities.yml`` table.
    """
    if priorities is None:
        priorities = load_priorities()

    # Group cells by FM.
    cells_by_fm: dict[str, list[CoverageCell]] = {}
    for cell in report.coverage.cells:
        cells_by_fm.setdefault(cell.failure_mode, []).append(cell)

    # Per-FM score.
    per_fm: dict[str, float] = {}
    for fm in priorities:
        per_fm[fm] = _per_fm_score(cells_by_fm.get(fm, []))

    # Weighted aggregate.
    numerator = sum(priorities[fm] * per_fm[fm] for fm in priorities)
    denominator = sum(priorities.values())
    score = numerator / denominator if denominator > 0 else 0.0

    # Side metadata for the UI.
    paradigm_counts = _count_paradigms(report.coverage.cells)
    is_balanced = all(paradigm_counts.get(p, 0) >= 1 for p in _ALL_PARADIGMS)

    fms_covered = sum(1 for v in per_fm.values() if v > 0)

    return RepoScore(
        score=round(score, 4),
        grade=grade_for(score),
        per_fm={k: round(v, 3) for k, v in per_fm.items()},
        paradigm_counts=paradigm_counts,
        is_balanced=is_balanced,
        failure_modes_covered=fms_covered,
        failure_modes_total=len(priorities),
        notes=_explain(score, fms_covered, paradigm_counts),
    )


# ---------------------------------------------------------------------------
# Internal helpers (paradigm counting, prose)
# ---------------------------------------------------------------------------

_ALL_PARADIGMS: tuple[Paradigm, ...] = (
    "prevention",
    "detection",
    "correction",
    "recovery",
)


def _count_paradigms(cells: list[CoverageCell]) -> dict[str, int]:
    """For each paradigm, count distinct FMs it covers (tier ≥ 1)."""
    by_paradigm: dict[str, set[str]] = {p: set() for p in _ALL_PARADIGMS}
    for cell in cells:
        if cell.tier >= 1:
            by_paradigm[cell.paradigm].add(cell.failure_mode)
    return {p: len(fms) for p, fms in by_paradigm.items()}


def _explain(
    score: float, fms_covered: int, paradigm_counts: dict[str, int]
) -> list[str]:
    """One- or two-bullet human prose for the leaderboard tooltip."""
    notes: list[str] = []
    notes.append(
        f"{fms_covered}/11 failure modes guarded by at least one detected tool."
    )
    missing = [p for p in _ALL_PARADIGMS if paradigm_counts.get(p, 0) == 0]
    if missing:
        notes.append(
            "No coverage in paradigm(s): " + ", ".join(missing) + "."
        )
    return notes
