"""Tests for ``pipeline.maturity.score`` (activity bands A–F).

Mostly hand-checked synthetic tools so future tweaks to weights /
thresholds become deliberate. One end-to-end pass over the real
corpus checks the distribution doesn't go pathological.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from pipeline.maturity import score as score_module
from pipeline.maturity.score import (
    BAND_MEANING,
    BANDS,
    RECENT_PUSH_WINDOW_DAYS,
    SCALE_DESCRIPTION,
    STATUS_BAND_CAP,
    compute_maturity,
    effective_band,
    reference_date,
)

AS_OF = date(2026, 5, 1)


def _tool(**kw):
    """Synthetic tool dict with sensible defaults."""
    base = dict(maturity_status="stable", upstream_pushed_at="2026-04-01")
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Floor / ceiling
# ---------------------------------------------------------------------------


def test_empty_tool_lands_in_f() -> None:
    s = compute_maturity({}, as_of=AS_OF)
    assert s.band == "F"
    assert s.score == 0.0


def test_top_facets_land_in_a() -> None:
    """4+ papers + 3 docs + 3 evals + 50k stars + recent push → A."""
    s = compute_maturity(
        _tool(
            cited_in=["a", "b", "c", "d", "e"],
            documented_in=["d1", "d2", "d3", "d4"],
            evaluated_on=["e1", "e2", "e3", "e4"],
            stars=50000,
        ),
        as_of=AS_OF,
    )
    assert s.band == "A"


# ---------------------------------------------------------------------------
# No clock: the reference date is an argument
# ---------------------------------------------------------------------------


def test_as_of_is_required() -> None:
    with pytest.raises(TypeError):
        compute_maturity(_tool())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        compute_maturity(_tool(), as_of="2026-05-01")  # type: ignore[arg-type]


def test_module_never_reads_the_clock() -> None:
    source = inspect.getsource(score_module)
    assert ".today(" not in source and ".now(" not in source


def test_same_input_same_band_whatever_the_day() -> None:
    tool = _tool(stars=4000, integration_surfaces=["cli", "ci_app"])
    assert compute_maturity(tool, as_of=AS_OF) == compute_maturity(tool, as_of=AS_OF)
    later = compute_maturity(tool, as_of=AS_OF + timedelta(days=800))
    assert later.facets["recent_push"] == 0  # only an explicit as_of moves it


def test_reference_date_is_the_newest_check_date() -> None:
    tools = [
        {"last_updated": "2026-04-15", "stars_updated_at": "2026-04-23"},
        {"last_reviewed": date(2026, 11, 21), "upstream_pushed_at": "2026-11-02"},
        {"last_updated": "not a date"},
        {},
    ]
    assert reference_date(tools) == date(2026, 11, 21)
    assert reference_date([]) is None
    assert reference_date([{"stars": 5}]) is None


# ---------------------------------------------------------------------------
# Per-facet contributions
# ---------------------------------------------------------------------------


def test_citation_count_caps_at_four() -> None:
    """Adding a 5th paper adds nothing — cap = 4."""
    s4 = compute_maturity(_tool(cited_in=["a", "b", "c", "d"]), as_of=AS_OF)
    s5 = compute_maturity(_tool(cited_in=["a", "b", "c", "d", "e"]), as_of=AS_OF)
    assert s4.facets["paper_citations"] == s5.facets["paper_citations"]


def test_recent_push_inside_window_scores() -> None:
    s = compute_maturity(_tool(upstream_pushed_at="2026-04-01"), as_of=AS_OF)
    assert s.facets["recent_push"] > 0


def test_recent_push_falls_back_to_last_updated_on_older_nodes() -> None:
    old_style = {"maturity_status": "stable", "last_updated": "2026-04-01"}
    assert compute_maturity(old_style, as_of=AS_OF).facets["recent_push"] > 0
    both = _tool(upstream_pushed_at="2024-01-01", last_updated="2026-04-01")
    assert compute_maturity(both, as_of=AS_OF).facets["recent_push"] == 0


def test_stale_push_outside_window_scores_zero() -> None:
    stale = (AS_OF - timedelta(days=RECENT_PUSH_WINDOW_DAYS + 30)).isoformat()
    s = compute_maturity(_tool(upstream_pushed_at=stale), as_of=AS_OF)
    assert s.facets["recent_push"] == 0


def test_invalid_date_string_does_not_crash() -> None:
    s = compute_maturity(_tool(upstream_pushed_at="not-a-date"), as_of=AS_OF)
    assert s.facets["recent_push"] == 0


def test_zero_stars_scores_zero() -> None:
    s = compute_maturity(_tool(stars=0), as_of=AS_OF)
    assert s.facets["stars"] == 0


def test_stars_log_scale_does_not_explode_on_huge_repos() -> None:
    s_huge = compute_maturity(_tool(stars=10**7), as_of=AS_OF)
    assert s_huge.facets["stars"] <= 2.1


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", list(STATUS_BAND_CAP.keys()))
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
        as_of=AS_OF,
    )
    assert s.band == STATUS_BAND_CAP[status]
    # When a cap fires, notes carry the explanation.
    assert any("capped" in n for n in s.notes)


def test_stable_status_does_not_cap() -> None:
    s = compute_maturity(_tool(stars=50000, cited_in=["a", "b", "c", "d"]), as_of=AS_OF)
    assert s.band in {"A", "B"}
    assert s.notes == []


def test_archived_repository_is_band_f() -> None:
    s = compute_maturity(
        _tool(stars=70000, integration_surfaces=["cli", "library"], archived=True),
        as_of=AS_OF,
    )
    assert s.band == "F"
    assert any("archived" in n for n in s.notes)


# ---------------------------------------------------------------------------
# Names: a band must not promise evidence
# ---------------------------------------------------------------------------


def test_band_names_are_letters_not_evidence_levels() -> None:
    assert BANDS == ("A", "B", "C", "D", "E", "F")
    assert set(BAND_MEANING) == set(BANDS)


def test_no_band_text_claims_a_paper_or_peer_review() -> None:
    """Review E9: the old tier texts said "peer-reviewed paper" and "at least
    one paper citation" for tiers that 41 of 49 uncited tools were in."""
    texts = " ".join(BAND_MEANING.values()).lower()
    for claim in ("peer-reviewed", "paper", "citation", "research", "validated"):
        assert claim not in texts
    assert "not a level of evidence" in SCALE_DESCRIPTION


def test_a_tool_without_citation_reaches_a_high_band_and_that_is_fine() -> None:
    """Stars + recent push + surfaces alone reach band C or better; the band
    description must therefore not mention citations (see test above)."""
    s = compute_maturity(
        _tool(stars=30000, integration_surfaces=["cli", "ci_app", "ide_plugin"]),
        as_of=AS_OF,
    )
    assert s.facets["paper_citations"] == 0
    assert s.band in {"B", "C"}


# ---------------------------------------------------------------------------
# Override resolution
# ---------------------------------------------------------------------------


def test_effective_band_uses_override_when_present() -> None:
    tool = _tool(
        cited_in=[],
        maturity_override={"tier": "C", "justification": "internal evidence"},
    )
    assert effective_band(tool, as_of=AS_OF) == "C"


def test_effective_band_ignores_invalid_override() -> None:
    for bogus in ("Z9", "2A", "1B"):
        tool = _tool(maturity_override={"tier": bogus, "justification": "bogus"})
        assert (
            effective_band(tool, as_of=AS_OF)
            == compute_maturity(tool, as_of=AS_OF).band
        )


def test_effective_band_falls_back_to_computed() -> None:
    tool = _tool(stars=50000, cited_in=["a", "b", "c", "d"])
    assert effective_band(tool, as_of=AS_OF) in {"A", "B"}


# ---------------------------------------------------------------------------
# Corpus smoke test
# ---------------------------------------------------------------------------


def test_real_corpus_distribution_is_not_pathological() -> None:
    """End-to-end: every committed tool YAML scores cleanly and no band
    holds more than 70% of the catalogue.

    This guards against a refactor that accidentally makes everything
    land in one band.
    """
    tools_dir = Path(__file__).resolve().parents[3] / "data" / "tools"
    docs = [
        yaml.safe_load(p.read_text()) or {} for p in sorted(tools_dir.glob("*.yml"))
    ]
    as_of = reference_date(docs)
    assert as_of is not None
    counts: dict[str, int] = {b: 0 for b in BANDS}
    for doc in docs:
        counts[compute_maturity(doc, as_of=as_of).band] += 1

    total = sum(counts.values())
    # 49 tools after the 2026-11 tag audit; keep a floor so the skew check
    # below stays statistically meaningful.
    assert total >= 30, "expected >= 30 tools in corpus"
    assert all(
        c / total < 0.70 for c in counts.values()
    ), f"distribution skewed: {counts}"
