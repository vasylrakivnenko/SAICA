"""Stage 4 — composite quality gate (PGxMine-style "any-N-of-M" rescue).

WHY THIS EXISTS
---------------
v0.4.x ranked discovery candidates by *awesome-list source count alone*.
That ranking buried high-popularity tools that happened to land in only
one curated list. The canonical example is ``upstash/context7`` — it
appeared in exactly one awesome-list (1 source), got sorted to row
2,488 of 2,675 in the candidates report, and was never reviewed,
despite having ~25k GitHub stars and being a widely-deployed MCP
server for up-to-date library docs.

This module implements the v2-pipeline Stage 4 fix: a candidate
*passes* the gate if it satisfies **at least N of M** independent
quality signals. The gate is intentionally lenient (any 2 of 6) so
that genuinely strong candidates from a single source still get
through, but hopelessly weak ones (no stars, no citations, single
source, abandoned) get filtered before any expensive downstream stage.

CRITERIA (any 2 of 6 → PASS)
----------------------------
  1. ``stars >= 1000``                  — popular on GitHub
  2. ``paper_citations >= 2``           — cited / implemented in ≥2 papers
  3. ``paper_artifact_link``            — linked from a paper's artifact section
  4. ``contributor_count >= 3``         — non-trivial team
  5. ``awesome_list_count >= 2``        — corroborated across curated indexes
  6. ``org in ALIGNMENT_ORGS``          — affiliated with a known alignment/
                                          safety lab

The threshold (``MIN_PASSES = 2``) and the per-criterion thresholds
are knobs at module top — when we ship the v2 Stage 0a labeled
holdout, calibrate against it.

DESIGN CHOICES
--------------
* **Pure / no I/O.** The gate operates on a ``CandidateSignals``
  dataclass the caller has already populated. Fetching stars,
  counting contributors, and matching paper citations are upstream
  responsibilities — keeps this module testable and cheap to call
  on every candidate batch.
* **Conservative when data is missing.** A criterion the caller
  can't fill (e.g. paper_citations is None because the S2 lookup
  hasn't happened yet) is treated as "no signal" — it neither passes
  nor fails the criterion. The gate just says PASS when ≥2 of the
  *available* signals fire. False positives at this stage are cheap
  (one Kimi extraction); false negatives are expensive (a real tool
  silently lost from the queue forever).
* **Per-criterion attribution in the result.** ``QualityGateResult``
  carries the list of criteria that fired so the candidate report
  can render *why* a tool passed (e.g. "stars + alignment-org") and
  curators can sanity-check the gate's behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Tunable constants — recalibrate when Stage 0a labeled holdout exists.
# ---------------------------------------------------------------------------

MIN_PASSES: int = 2
"""How many of the 6 criteria must fire for the candidate to PASS."""

STARS_THRESHOLD: int = 1000
STARS_EXCEPTIONAL_THRESHOLD: int = 10_000
"""Stars at or above this count single-handedly pass the gate.

Rationale: when enrichment only fills the stars field (no citation
graph, no contributor count) — which is the cheap-fetch case — a
25k-star widely-used tool would otherwise fail the gate (1-of-6 fires).
Exceptional popularity is itself a 2-criterion-strength signal.
Lowering this constant or removing the override is fine when
enrichment is rich enough that multiple criteria fire reliably.
"""

PAPER_CITATIONS_THRESHOLD: int = 2
CONTRIBUTORS_THRESHOLD: int = 3
AWESOME_LIST_THRESHOLD: int = 2

# Known alignment / safety orgs. Affiliation is a strong "this is
# serious supervision research, look at it" signal even when the
# repo itself is small. Match is case-insensitive, exact owner
# string match against ``CandidateSignals.org``. Deliberately narrow
# — adding a generic AI org (openai, anthropic, etc.) would let a
# huge volume of unrelated tooling through.
ALIGNMENT_ORGS: frozenset[str] = frozenset(
    o.lower()
    for o in (
        "redwoodresearch",
        "ARC-Evals",
        "METR-evals",
        "metr",
        "MATSProgram",
        "mats-program",
        "ApolloResearch",
        "apollo-research",
        "alignmentforum",
        "anthropics",  # narrow: only the named-by-Anthropic org account
        "deepmind",  # google-deepmind / deepmind shared safety repos
        "google-deepmind",
        "anthropic-experimental",
        "ml-alignment-theory-scholars",
        "AI-Safety-Camp",
        "open-philanthropy",
        "centre-for-effective-altruism",
        "longtermrisk",
        "FAR-AI",
        "far-ai",
    )
)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


class GateDecision(str, Enum):
    """The two buckets a candidate can land in."""

    PASS = "pass"
    FAIL = "fail"


@dataclass
class CandidateSignals:
    """Per-candidate signals the gate operates on.

    Unknown values stay None — the gate treats them as "no signal,"
    not "criterion failed." This is the conservative behaviour
    documented in the module docstring.
    """

    stars: Optional[int] = None
    paper_citations: Optional[int] = None
    paper_artifact_link: Optional[bool] = None
    contributor_count: Optional[int] = None
    awesome_list_count: Optional[int] = None
    org: Optional[str] = None

    # Side-info the gate doesn't read but that the caller / report
    # may want to keep with the decision (e.g. last commit date for
    # downstream freshness filters).
    last_commit_date: Optional[date] = None
    archived: Optional[bool] = None


@dataclass
class GateResult:
    """The verdict on one candidate."""

    decision: GateDecision
    passed_criteria: list[str] = field(default_factory=list)
    n_passed: int = 0
    n_signals_present: int = 0
    explanation: str = ""


# ---------------------------------------------------------------------------
# Per-criterion checks (each returns True / False / None)
# ---------------------------------------------------------------------------


def _check_stars(s: CandidateSignals) -> Optional[bool]:
    return None if s.stars is None else s.stars >= STARS_THRESHOLD


def _check_paper_citations(s: CandidateSignals) -> Optional[bool]:
    return (
        None
        if s.paper_citations is None
        else s.paper_citations >= PAPER_CITATIONS_THRESHOLD
    )


def _check_paper_artifact(s: CandidateSignals) -> Optional[bool]:
    return None if s.paper_artifact_link is None else bool(s.paper_artifact_link)


def _check_contributors(s: CandidateSignals) -> Optional[bool]:
    return (
        None
        if s.contributor_count is None
        else s.contributor_count >= CONTRIBUTORS_THRESHOLD
    )


def _check_awesome_lists(s: CandidateSignals) -> Optional[bool]:
    return (
        None
        if s.awesome_list_count is None
        else s.awesome_list_count >= AWESOME_LIST_THRESHOLD
    )


def _check_alignment_org(s: CandidateSignals) -> Optional[bool]:
    if s.org is None:
        return None
    return s.org.strip().lower() in ALIGNMENT_ORGS


_CRITERIA: tuple[tuple[str, Any], ...] = (
    ("stars", _check_stars),
    ("paper_citations", _check_paper_citations),
    ("paper_artifact", _check_paper_artifact),
    ("contributors", _check_contributors),
    ("awesome_lists", _check_awesome_lists),
    ("alignment_org", _check_alignment_org),
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate(signals: CandidateSignals) -> GateResult:
    """Run the gate on one candidate's signals."""
    passed: list[str] = []
    n_signals = 0
    for name, check in _CRITERIA:
        verdict = check(signals)
        if verdict is None:
            continue
        n_signals += 1
        if verdict:
            passed.append(name)
    n_passed = len(passed)

    # "Exceptional stars" override — a 10k+ star repo single-handedly
    # passes the gate even when other enrichment fields are missing.
    # See STARS_EXCEPTIONAL_THRESHOLD docstring for rationale.
    exceptional = (
        signals.stars is not None
        and signals.stars >= STARS_EXCEPTIONAL_THRESHOLD
    )
    if exceptional and "stars_exceptional" not in passed:
        passed.append("stars_exceptional")
        n_passed += 1

    decision = GateDecision.PASS if n_passed >= MIN_PASSES else GateDecision.FAIL
    return GateResult(
        decision=decision,
        passed_criteria=passed,
        n_passed=n_passed,
        n_signals_present=n_signals,
        explanation=_explain(decision, passed, n_signals),
    )


def evaluate_batch(
    candidates: Iterable[CandidateSignals],
) -> list[GateResult]:
    """Apply :func:`evaluate` to a sequence of candidates."""
    return [evaluate(c) for c in candidates]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _explain(
    decision: GateDecision, passed: list[str], n_signals: int
) -> str:
    if decision is GateDecision.PASS:
        return (
            f"PASS — {len(passed)} criteria fired ({', '.join(passed)})"
            f"; threshold = {MIN_PASSES} of 6."
        )
    if n_signals == 0:
        return (
            "FAIL — no signals present. Caller must enrich the candidate "
            "(stars, contributors, citations) before the gate can rule."
        )
    return (
        f"FAIL — only {len(passed)} criteria fired"
        f" ({', '.join(passed) if passed else 'none'})"
        f"; threshold = {MIN_PASSES} of 6."
    )


__all__ = [
    "ALIGNMENT_ORGS",
    "AWESOME_LIST_THRESHOLD",
    "CONTRIBUTORS_THRESHOLD",
    "CandidateSignals",
    "GateDecision",
    "GateResult",
    "MIN_PASSES",
    "PAPER_CITATIONS_THRESHOLD",
    "STARS_THRESHOLD",
    "evaluate",
    "evaluate_batch",
]
