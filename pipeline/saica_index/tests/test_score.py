"""Unit tests for ``pipeline.saica_index.score``.

Pure-math tests — we build synthetic ``AuditReport`` objects rather than
running the full audit pipeline. The goal is to lock the scoring
formula so future tweaks are deliberate.
"""

from __future__ import annotations

from datetime import date

import pytest

from pipeline.audit.schemas import (
    AuditReport,
    CoverageCell,
    CoverageGrid,
    DetectedStack,
)
from pipeline.saica_index.score import (
    GRADE_THRESHOLDS,
    PARADIGM_DIVERSITY_BONUS,
    TIER_WEIGHT,
    grade_for,
    score_report,
)

# A simple 3-FM priority table so the math is hand-checkable.
_TEST_PRIORITIES = {
    "fm_a": 2.0,
    "fm_b": 1.0,
    "fm_c": 1.0,
}


def _empty_stack() -> DetectedStack:
    return DetectedStack(
        languages=[],
        runtime_hints=[],
        ci_providers=[],
        package_managers=[],
        agents=[],
        supervision_tools=[],
        unresolved_tools=[],
    )


def _report(cells: list[CoverageCell]) -> AuditReport:
    return AuditReport(
        repo_url="https://github.com/test/test",
        audited_at=date(2026, 5, 1),
        stack=_empty_stack(),
        coverage=CoverageGrid(
            cells=cells,
            failure_modes_covered=sorted({c.failure_mode for c in cells if c.tier > 0}),
            failure_modes_missing=[],
            paradigm_balance={},
        ),
        gaps=[],
        summary="test",
        markdown="test",
    )


# ---------------------------------------------------------------------------
# Grade thresholds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score, expected",
    [
        (1.00, "A"),
        (0.80, "A"),
        (0.799, "B"),
        (0.60, "B"),
        (0.40, "C"),
        (0.20, "D"),
        (0.00, "F"),
    ],
)
def test_grade_for(score: float, expected: str) -> None:
    assert grade_for(score) == expected


def test_grade_thresholds_are_monotone() -> None:
    """Each grade boundary must be strictly higher than the next."""
    thresholds = [t for t, _ in GRADE_THRESHOLDS]
    assert thresholds == sorted(thresholds, reverse=True)


# ---------------------------------------------------------------------------
# Per-FM score
# ---------------------------------------------------------------------------


def test_no_coverage_scores_zero() -> None:
    report = _report([])
    s = score_report(report, priorities=_TEST_PRIORITIES)
    assert s.score == 0.0
    assert s.grade == "F"
    assert s.failure_modes_covered == 0


def test_tier_weights_match_constants() -> None:
    """One FM at one tier each should yield exactly the constant weight."""
    for tier in (1, 2, 3):
        cells = [
            CoverageCell(
                failure_mode="fm_a",
                paradigm="detection",
                tier=tier,
                contributing_tools=["t"],
            ),
        ]
        report = _report(cells)
        s = score_report(report, priorities={"fm_a": 1.0})
        assert s.score == TIER_WEIGHT[tier], f"tier={tier} mismatch"


def test_paradigm_diversity_bonus_applied_when_two_paradigms() -> None:
    """Two paradigms covering one FM at tier 1 → 0.40 + 0.10 = 0.50."""
    cells = [
        CoverageCell(failure_mode="fm_a", paradigm="prevention", tier=1, contributing_tools=["t1"]),
        CoverageCell(failure_mode="fm_a", paradigm="detection", tier=1, contributing_tools=["t2"]),
    ]
    report = _report(cells)
    s = score_report(report, priorities={"fm_a": 1.0})
    assert s.score == pytest.approx(TIER_WEIGHT[1] + PARADIGM_DIVERSITY_BONUS)


def test_paradigm_bonus_capped_at_one() -> None:
    """Tier 3 + 4 paradigms still tops out at 1.0 (not 1.10)."""
    cells = [
        CoverageCell(failure_mode="fm_a", paradigm="prevention", tier=3, contributing_tools=["t"]),
        CoverageCell(failure_mode="fm_a", paradigm="detection", tier=3, contributing_tools=["t"]),
        CoverageCell(failure_mode="fm_a", paradigm="correction", tier=3, contributing_tools=["t"]),
        CoverageCell(failure_mode="fm_a", paradigm="recovery", tier=3, contributing_tools=["t"]),
    ]
    report = _report(cells)
    s = score_report(report, priorities={"fm_a": 1.0})
    assert s.score == 1.0
    assert s.grade == "A"
    assert s.is_balanced is True


def test_priority_weighting() -> None:
    """fm_a (priority 2) covered, fm_b/c (priority 1 each) not covered.

    Expected: 2.0 * 0.40 / (2.0 + 1.0 + 1.0) = 0.80 / 4.0 = 0.20.
    """
    cells = [
        CoverageCell(failure_mode="fm_a", paradigm="detection", tier=1, contributing_tools=["t"]),
    ]
    report = _report(cells)
    s = score_report(report, priorities=_TEST_PRIORITIES)
    assert s.score == pytest.approx(0.20, abs=0.001)
    assert s.grade == "D"


def test_full_coverage_scores_one() -> None:
    """All 3 FMs at tier 3, single paradigm each → 1.00 weighted."""
    cells = [
        CoverageCell(failure_mode=fm, paradigm="detection", tier=3, contributing_tools=["t"])
        for fm in _TEST_PRIORITIES
    ]
    report = _report(cells)
    s = score_report(report, priorities=_TEST_PRIORITIES)
    assert s.score == 1.0
    assert s.grade == "A"


def test_paradigm_counts_distinct_per_fm() -> None:
    """A paradigm covering 2 different FMs counts as 2, not 1."""
    cells = [
        CoverageCell(failure_mode="fm_a", paradigm="detection", tier=1, contributing_tools=["t"]),
        CoverageCell(failure_mode="fm_b", paradigm="detection", tier=1, contributing_tools=["t"]),
    ]
    report = _report(cells)
    s = score_report(report, priorities=_TEST_PRIORITIES)
    assert s.paradigm_counts["detection"] == 2
    assert s.paradigm_counts["prevention"] == 0
    assert s.is_balanced is False


def test_is_balanced_requires_all_four_paradigms() -> None:
    cells = [
        CoverageCell(failure_mode="fm_a", paradigm=p, tier=1, contributing_tools=["t"])
        for p in ("prevention", "detection", "correction", "recovery")
    ]
    report = _report(cells)
    s = score_report(report, priorities={"fm_a": 1.0})
    assert s.is_balanced is True


def test_real_priority_table_loads() -> None:
    """Smoke test: the real priorities YAML loads + sums to a positive number.

    Catches breaks if anyone restructures `data/failure_mode_priorities.yml`.
    """
    from pipeline.saica_index.score import load_priorities

    p = load_priorities()
    assert len(p) >= 11, "expected at least the 11 canonical FMs"
    assert sum(p.values()) > 0


def test_explain_lists_missing_paradigms() -> None:
    cells = [
        CoverageCell(failure_mode="fm_a", paradigm="detection", tier=1, contributing_tools=["t"]),
    ]
    report = _report(cells)
    s = score_report(report, priorities={"fm_a": 1.0})
    note_text = " ".join(s.notes)
    assert "prevention" in note_text
    assert "correction" in note_text
    assert "recovery" in note_text
