"""Tests for ``pipeline.maturity.score``.

Mostly hand-checked synthetic tools so future tweaks to weights /
thresholds become deliberate. One end-to-end pass over the real
corpus checks the distribution doesn't go pathological.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from pipeline.maturity.score import (
    RECENT_COMMIT_WINDOW_DAYS,
    STATUS_TIER_CAP,
    compute_maturity,
    effective_tier,
)


def _today() -> date:
    return date(2026, 5, 1)


def _tool(**kw):
    """Synthetic tool dict with sensible defaults."""
    base = dict(maturity_status="stable", last_updated="2026-04-01")
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Floor / ceiling
# ---------------------------------------------------------------------------


def test_empty_tool_lands_at_4() -> None:
    s = compute_maturity({}, today=_today())
    assert s.tier == "4"
    assert s.score == 0.0


def test_top_facets_lands_in_1A() -> None:
    """4+ papers + 3 docs + 3 evals + 50k stars + recent commit → 1A."""
    s = compute_maturity(
        _tool(
            cited_in=["a", "b", "c", "d", "e"],
            documented_in=["d1", "d2", "d3", "d4"],
            evaluated_on=["e1", "e2", "e3", "e4"],
            stars=50000,
        ),
        today=_today(),
    )
    assert s.tier == "1A"


# ---------------------------------------------------------------------------
# Per-facet contributions
# ---------------------------------------------------------------------------


def test_citation_count_caps_at_four() -> None:
    """Adding a 5th paper adds nothing — cap = 4."""
    s4 = compute_maturity(_tool(cited_in=["a", "b", "c", "d"]), today=_today())
    s5 = compute_maturity(
        _tool(cited_in=["a", "b", "c", "d", "e"]), today=_today()
    )
    assert s4.facets["paper_citations"] == s5.facets["paper_citations"]


def test_recent_commit_inside_window_scores() -> None:
    s = compute_maturity(_tool(last_updated="2026-04-01"), today=_today())
    assert s.facets["recent_commit"] > 0


def test_stale_commit_outside_window_scores_zero() -> None:
    stale = (_today() - timedelta(days=RECENT_COMMIT_WINDOW_DAYS + 30)).isoformat()
    s = compute_maturity(_tool(last_updated=stale), today=_today())
    assert s.facets["recent_commit"] == 0


def test_invalid_date_string_does_not_crash() -> None:
    s = compute_maturity(_tool(last_updated="not-a-date"), today=_today())
    assert s.facets["recent_commit"] == 0


def test_zero_stars_scores_zero() -> None:
    s = compute_maturity(_tool(stars=0), today=_today())
    assert s.facets["stars"] == 0


def test_stars_log_scale_does_not_explode_on_huge_repos() -> None:
    s_huge = compute_maturity(_tool(stars=10**7), today=_today())
    assert s_huge.facets["stars"] <= 2.1


# ---------------------------------------------------------------------------
# Maturity-status cap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", list(STATUS_TIER_CAP.keys()))
def test_status_caps_apply(status: str) -> None:
    """Even with strong facets, a deprecated/abandoned tool can't beat the cap."""
    s = compute_maturity(
        _tool(
            maturity_status=status,
            cited_in=["a", "b", "c", "d"],
            documented_in=["d1", "d2", "d3"],
            evaluated_on=["e1", "e2", "e3"],
            stars=50000,
        ),
        today=_today(),
    )
    assert s.tier == STATUS_TIER_CAP[status]
    # When a cap fires, notes carry the explanation.
    assert any("capped" in n for n in s.notes)


def test_stable_status_does_not_cap() -> None:
    s = compute_maturity(_tool(stars=50000, cited_in=["a", "b", "c", "d"]), today=_today())
    assert s.tier in {"1A", "1B"}
    assert s.notes == []


# ---------------------------------------------------------------------------
# Override resolution
# ---------------------------------------------------------------------------


def test_effective_tier_uses_override_when_present() -> None:
    tool = _tool(
        cited_in=[],  # would compute as 4
        maturity_override={"tier": "2A", "justification": "internal evidence"},
    )
    assert effective_tier(tool, today=_today()) == "2A"


def test_effective_tier_ignores_invalid_override() -> None:
    tool = _tool(maturity_override={"tier": "Z9", "justification": "bogus"})
    # Falls through to the computed tier — depends on _tool defaults
    # (recent commit + stable status). Just assert it's a valid tier.
    assert effective_tier(tool, today=_today()) in {"1A", "1B", "2A", "2B", "3", "4"}


def test_effective_tier_falls_back_to_computed() -> None:
    tool = _tool(stars=50000, cited_in=["a", "b", "c", "d"])
    assert effective_tier(tool, today=_today()) in {"1A", "1B"}


# ---------------------------------------------------------------------------
# Corpus smoke test
# ---------------------------------------------------------------------------


def test_real_corpus_distribution_is_not_pathological() -> None:
    """End-to-end: every committed tool YAML scores cleanly, distribution
    is roughly bell-ish, no tier hogs >70% of the corpus.

    This guards against a refactor that accidentally makes everything
    land in one tier.
    """
    import yaml
    from pathlib import Path

    tools_dir = Path(__file__).resolve().parents[3] / "data" / "tools"
    counts: dict[str, int] = {t: 0 for t in ("1A", "1B", "2A", "2B", "3", "4")}
    for yml in sorted(tools_dir.glob("*.yml")):
        doc = yaml.safe_load(yml.read_text()) or {}
        s = compute_maturity(doc, today=_today())
        counts[s.tier] += 1

    total = sum(counts.values())
    assert total > 50, "expected > 50 tools in corpus"
    # No single tier owns more than 70% of the distribution.
    assert all(
        c / total < 0.70 for c in counts.values()
    ), f"distribution skewed: {counts}"
