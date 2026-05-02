"""Tests for ``pipeline.discovery.quality_gate``.

The gate is pure math + thresholds. We hand-construct synthetic
``CandidateSignals`` to lock the behaviour for each combination of
criteria. The intent is that future tweaks to ``MIN_PASSES`` or
the per-criterion thresholds become deliberate.
"""

from __future__ import annotations

import pytest

from pipeline.discovery.quality_gate import (
    AWESOME_LIST_THRESHOLD,
    CONTRIBUTORS_THRESHOLD,
    MIN_PASSES,
    PAPER_CITATIONS_THRESHOLD,
    STARS_THRESHOLD,
    CandidateSignals,
    GateDecision,
    evaluate,
    evaluate_batch,
)


# ---------------------------------------------------------------------------
# Boundary checks per criterion
# ---------------------------------------------------------------------------


def test_no_signals_at_all_fails() -> None:
    """A candidate with zero enrichment data must FAIL — gate cannot
    rule on absence."""
    r = evaluate(CandidateSignals())
    assert r.decision is GateDecision.FAIL
    assert r.n_passed == 0
    assert r.n_signals_present == 0
    assert "no signals present" in r.explanation


def test_single_criterion_below_threshold_fails() -> None:
    """One present signal that's BELOW its threshold = 0 passes."""
    r = evaluate(CandidateSignals(stars=500))
    assert r.decision is GateDecision.FAIL
    assert r.n_passed == 0
    assert r.n_signals_present == 1


def test_single_criterion_at_threshold_still_fails_overall() -> None:
    """One present signal AT its threshold passes the criterion but
    not the gate (need MIN_PASSES, default 2)."""
    r = evaluate(CandidateSignals(stars=STARS_THRESHOLD))
    assert r.decision is GateDecision.FAIL
    assert r.passed_criteria == ["stars"]
    assert r.n_passed == 1


def test_two_criteria_at_threshold_passes_gate() -> None:
    """The classic 'any 2 of 6' — exactly two pass, gate PASSES."""
    r = evaluate(
        CandidateSignals(
            stars=STARS_THRESHOLD,
            awesome_list_count=AWESOME_LIST_THRESHOLD,
        )
    )
    assert r.decision is GateDecision.PASS
    assert sorted(r.passed_criteria) == ["awesome_lists", "stars"]
    assert r.n_passed == MIN_PASSES


def test_paper_citations_threshold() -> None:
    """Paper citations must be >= threshold; below fails its check."""
    below = evaluate(
        CandidateSignals(
            paper_citations=PAPER_CITATIONS_THRESHOLD - 1,
            stars=STARS_THRESHOLD,
        )
    )
    assert "paper_citations" not in below.passed_criteria
    above = evaluate(
        CandidateSignals(
            paper_citations=PAPER_CITATIONS_THRESHOLD,
            stars=STARS_THRESHOLD,
        )
    )
    assert "paper_citations" in above.passed_criteria


def test_paper_artifact_link_is_true_or_false() -> None:
    """Boolean-shaped criterion: True passes, False doesn't."""
    yes = evaluate(
        CandidateSignals(paper_artifact_link=True, stars=STARS_THRESHOLD)
    )
    no = evaluate(
        CandidateSignals(paper_artifact_link=False, stars=STARS_THRESHOLD)
    )
    assert "paper_artifact" in yes.passed_criteria
    assert "paper_artifact" not in no.passed_criteria


def test_contributor_count_threshold() -> None:
    above = evaluate(
        CandidateSignals(
            contributor_count=CONTRIBUTORS_THRESHOLD,
            stars=STARS_THRESHOLD,
        )
    )
    assert "contributors" in above.passed_criteria
    below = evaluate(
        CandidateSignals(
            contributor_count=CONTRIBUTORS_THRESHOLD - 1,
            stars=STARS_THRESHOLD,
        )
    )
    assert "contributors" not in below.passed_criteria


def test_alignment_org_match_is_case_insensitive() -> None:
    """Owner string match is case-insensitive."""
    r = evaluate(
        CandidateSignals(
            org="REDwOOdrEsEArch",
            stars=STARS_THRESHOLD,
        )
    )
    assert "alignment_org" in r.passed_criteria


def test_alignment_org_unknown_does_not_pass_check() -> None:
    r = evaluate(
        CandidateSignals(
            org="some-startup-llc",
            stars=STARS_THRESHOLD,
        )
    )
    assert "alignment_org" not in r.passed_criteria


# ---------------------------------------------------------------------------
# Conservative behaviour on missing data
# ---------------------------------------------------------------------------


def test_unknown_signals_dont_count_as_failures() -> None:
    """A None criterion is treated as 'no signal,' not 'failed' —
    so a candidate with 2 of 2 KNOWN signals at threshold still PASSes
    even though 4 criteria are unknown."""
    r = evaluate(
        CandidateSignals(
            stars=STARS_THRESHOLD,
            awesome_list_count=AWESOME_LIST_THRESHOLD,
            # rest stay None
        )
    )
    assert r.decision is GateDecision.PASS
    assert r.n_signals_present == 2
    assert r.n_passed == 2


def test_all_signals_present_but_only_one_passes_fails() -> None:
    """Discriminator: even when caller has filled every criterion,
    only criteria above their threshold count toward the pass total."""
    r = evaluate(
        CandidateSignals(
            stars=10,                      # below
            paper_citations=0,             # below
            paper_artifact_link=False,
            contributor_count=1,           # below
            awesome_list_count=1,          # below
            org="some-randomer",
        )
    )
    assert r.decision is GateDecision.FAIL
    assert r.passed_criteria == []
    assert r.n_signals_present == 6
    assert r.n_passed == 0


# ---------------------------------------------------------------------------
# Real-world cases that motivated the gate
# ---------------------------------------------------------------------------


def test_context7_like_candidate_passes_gate() -> None:
    """The motivating case: high stars, active, but only 1 awesome-
    list source. Old ranker buried it; the gate must rescue it."""
    r = evaluate(
        CandidateSignals(
            stars=25_000,                 # huge — alone passes
            awesome_list_count=1,         # below threshold
            contributor_count=20,         # well above threshold
            org="upstash",                # not alignment-org
        )
    )
    # stars + contributors + stars_exceptional → 3 passes → PASS
    assert r.decision is GateDecision.PASS
    assert "stars" in r.passed_criteria
    assert "contributors" in r.passed_criteria


def test_exceptional_stars_alone_passes_gate() -> None:
    """Sparse-enrichment case: only stars provided, but stars are
    huge — must still PASS via the stars_exceptional override.

    This is the cheap-fetch scenario: when discovery enrichment only
    fills stars (not contributor count, citation graph, etc.), a
    25k-star tool would otherwise fail with 1-of-6. The override
    rescues it — exceptional popularity is its own signal."""
    r = evaluate(CandidateSignals(stars=25_000))
    assert r.decision is GateDecision.PASS
    assert "stars" in r.passed_criteria
    assert "stars_exceptional" in r.passed_criteria
    assert r.n_passed >= 2


def test_high_but_not_exceptional_stars_alone_still_fails() -> None:
    """A 5k-star tool with no other signals: above the regular stars
    threshold but below the exceptional one. Must FAIL — one signal
    of mid-strength isn't enough."""
    r = evaluate(CandidateSignals(stars=5_000))
    assert r.decision is GateDecision.FAIL
    assert r.passed_criteria == ["stars"]


def test_alignment_org_lone_repo_with_low_stars_passes() -> None:
    """A 200-star repo from an alignment org should still get past
    the gate as long as one other signal fires."""
    r = evaluate(
        CandidateSignals(
            stars=200,                    # below
            contributor_count=5,          # above
            org="redwoodresearch",        # alignment org
        )
    )
    # contributors + alignment_org → 2 passes → PASS
    assert r.decision is GateDecision.PASS
    assert sorted(r.passed_criteria) == ["alignment_org", "contributors"]


def test_typical_long_tail_junk_fails() -> None:
    """A small awesome-list candidate with no other signals — the gate
    is what keeps these out of the curator queue."""
    r = evaluate(
        CandidateSignals(
            stars=42,
            awesome_list_count=1,
            contributor_count=1,
            org="random-user",
        )
    )
    assert r.decision is GateDecision.FAIL


# ---------------------------------------------------------------------------
# Batch helper smoke test
# ---------------------------------------------------------------------------


def test_evaluate_batch_returns_in_order() -> None:
    cs = [
        CandidateSignals(stars=STARS_THRESHOLD, awesome_list_count=AWESOME_LIST_THRESHOLD),
        CandidateSignals(stars=10),
    ]
    rs = evaluate_batch(cs)
    assert len(rs) == 2
    assert rs[0].decision is GateDecision.PASS
    assert rs[1].decision is GateDecision.FAIL
