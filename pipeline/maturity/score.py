"""Activity band A–F for a tool (formerly "maturity tier" 1A … 4).

WHAT IT MEASURES
----------------
A band is a bin of a score that adds up, from the tool's YAML alone:

+------------------------------+--------+------------------------------------+
| Facet                        | Weight | Source field                       |
+------------------------------+--------+------------------------------------+
| GitHub stars (log scale)     | 0–2    | ``stars``                          |
| Upstream push in the 12      | 2      | ``upstream_pushed_at`` (older      |
| months before ``as_of``      |        | nodes: ``last_updated``)           |
| Integration surfaces         | 0.5/ea | ``integration_surfaces`` (max 5)   |
| Papers that cite the tool    | 3/ea   | ``cited_in`` (max 4)               |
| Documentation sources        | 2/ea   | ``documented_in`` (max 3)          |
| Benchmark evaluations        | 2/ea   | ``evaluated_on`` (max 3)           |
+------------------------------+--------+------------------------------------+

On the 2026-11 data 47 of 49 tools have nothing in the last three rows, so
in practice the band says how popular a tool is, whether its repository
was pushed to recently, and how many ways it can be installed. It is NOT a
level of evidence. No band means that a paper cites the tool or that
anyone measured it; look at ``cited_in`` and ``evaluated_on`` for that.

The earlier names (1A, 1B, 2A, 2B, 3, 4 → A, B, C, D, E, F) copied
clinical-evidence levels, and their definitions required citations that 41
of 49 tools did not have (review 2026-11-21, E9). The thresholds are
unchanged; only the names and the claims attached to them are.

NO CLOCK
--------
``compute_maturity`` takes the reference date as the required ``as_of``
argument. It never reads today's date, so the same YAML gives the same
band on every day. Callers that score the whole catalogue pass
:func:`reference_date` (the newest check date found in the tool files) and
store it next to the result.

``maturity_status`` is an editor's judgement, so it caps the band:
``deprecated`` / ``abandoned`` → F, ``at_risk`` → E, ``experimental`` → D.
An archived upstream repository (``archived: true``) caps at F.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Literal

ActivityBand = Literal["A", "B", "C", "D", "E", "F"]

BANDS: tuple[ActivityBand, ...] = ("A", "B", "C", "D", "E", "F")

# Tunable constants.
WEIGHT_PAPER_CITATION = 3.0  # per paper in cited_in, capped
WEIGHT_DOCUMENTED_IN = 2.0  # per documentation source, capped
WEIGHT_EVALUATED_ON = 2.0  # per benchmark, capped
WEIGHT_STARS_FACTOR = 2.0  # log10(stars + 1) scaled to 0..2
WEIGHT_RECENT_PUSH = 2.0  # binary
WEIGHT_INTEGRATION_SURFACE = 0.5  # per declared surface, capped

CAP_PAPERS = 4  # ≥4 papers all count the same
CAP_DOCS = 3
CAP_EVALS = 3
CAP_SURFACES = 5

RECENT_PUSH_WINDOW_DAYS = 365

# Score → band. Order matters; first match wins. Set by hand against the
# 2026-05-01 catalogue (87 tools) so that no band held most of it.
BAND_THRESHOLDS: list[tuple[float, ActivityBand]] = [
    (7.0, "A"),
    (5.5, "B"),
    (4.7, "C"),
    (4.0, "D"),
    (2.5, "E"),
    (0.0, "F"),
]

BAND_MEANING: dict[str, str] = {
    "A": "score 7.0 or more",
    "B": "score 5.5 to 6.9",
    "C": "score 4.7 to 5.4",
    "D": "score 4.0 to 4.6",
    "E": "score 2.5 to 3.9",
    "F": "score below 2.5, or deprecated, abandoned or archived",
}

SCALE_DESCRIPTION = (
    "Activity band A to F: a bin of a score that adds GitHub stars (log scale),"
    " a push to the upstream repository in the 12 months before `as_of`, the"
    " number of declared integration surfaces and, where the catalogue records"
    " them, citing papers and benchmark evaluations. It measures popularity"
    " and activity. It is not a level of evidence: no band means a paper cites"
    " the tool or that it was measured."
)

# maturity_status caps. An editor's "deprecated" outranks stars.
STATUS_BAND_CAP: dict[str, ActivityBand] = {
    "deprecated": "F",
    "abandoned": "F",
    "at_risk": "E",
    "experimental": "D",
}

# Fields that say when a tool entry was last looked at, newest first choice.
_CHECK_DATE_FIELDS = (
    "last_reviewed",
    "stars_updated_at",
    "upstream_pushed_at",
    "last_updated",
)


@dataclass
class MaturityScore:
    """Result of scoring one tool YAML."""

    band: ActivityBand
    score: float
    facets: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def reference_date(tools: Iterable[dict[str, Any]]) -> date | None:
    """The newest date on which any tool entry was checked or updated.

    This is the ``as_of`` to score a whole catalogue against: it moves only
    when the data moves, never with the calendar. ``None`` for an empty
    catalogue or one without dates.
    """
    newest: date | None = None
    for tool in tools:
        for name in _CHECK_DATE_FIELDS:
            found = _as_date(tool.get(name))
            if found is not None and (newest is None or found > newest):
                newest = found
    return newest


# ---------------------------------------------------------------------------
# Pure scorer
# ---------------------------------------------------------------------------


def _coerce_count(field_value: Any, *, cap: int) -> int:
    """Length of a list field, capped — None / non-list returns 0."""
    if not isinstance(field_value, list):
        return 0
    return min(len(field_value), cap)


def _stars_score(stars: Any) -> float:
    """log10(stars + 1), capped at 5 (100k stars), scaled to 0..2."""
    if isinstance(stars, bool) or not isinstance(stars, (int, float)) or stars <= 0:
        return 0.0
    return min(5.0, math.log10(stars + 1)) * WEIGHT_STARS_FACTOR / 5.0


def _recent_push_score(pushed: Any, *, as_of: date) -> float:
    """``WEIGHT_RECENT_PUSH`` when the last upstream push is within the
    window before ``as_of``; 0 when it is older, missing or unreadable."""
    pushed_on = _as_date(pushed)
    if pushed_on is None:
        return 0.0
    if as_of - pushed_on <= timedelta(days=RECENT_PUSH_WINDOW_DAYS):
        return WEIGHT_RECENT_PUSH
    return 0.0


def compute_maturity(tool: dict[str, Any], *, as_of: date) -> MaturityScore:
    """Score one tool dict (loaded from its YAML) and bin it to a band.

    Pure: no I/O, no network, no clock. ``as_of`` is the date the recency
    facet is judged against. Missing fields contribute 0.
    """
    if not isinstance(as_of, date):
        raise TypeError("as_of must be a datetime.date")

    facets: dict[str, float] = {}

    n_papers = _coerce_count(tool.get("cited_in"), cap=CAP_PAPERS)
    n_docs = _coerce_count(tool.get("documented_in"), cap=CAP_DOCS)
    n_evals = _coerce_count(tool.get("evaluated_on"), cap=CAP_EVALS)
    facets["paper_citations"] = n_papers * WEIGHT_PAPER_CITATION
    facets["documented_in"] = n_docs * WEIGHT_DOCUMENTED_IN
    facets["evaluated_on"] = n_evals * WEIGHT_EVALUATED_ON

    n_surfaces = _coerce_count(tool.get("integration_surfaces"), cap=CAP_SURFACES)
    facets["integration_surfaces"] = n_surfaces * WEIGHT_INTEGRATION_SURFACE

    facets["stars"] = _stars_score(tool.get("stars"))

    facets["recent_push"] = _recent_push_score(
        tool.get("upstream_pushed_at") or tool.get("last_updated"), as_of=as_of
    )

    raw_score = sum(facets.values())

    band: ActivityBand = "F"
    for threshold, label in BAND_THRESHOLDS:
        if raw_score >= threshold:
            band = label
            break

    notes: list[str] = []
    status = str(tool.get("maturity_status") or "").lower()
    cap = STATUS_BAND_CAP.get(status)
    if cap is not None and _band_rank(band) < _band_rank(cap):
        notes.append(f"capped from {band} to {cap} by maturity_status={status!r}")
        band = cap
    if tool.get("archived") is True and band != "F":
        notes.append(f"capped from {band} to F: the upstream repository is archived")
        band = "F"

    return MaturityScore(
        band=band,
        score=round(raw_score, 2),
        facets={k: round(v, 2) for k, v in facets.items()},
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Override resolution (the band callers should show)
# ---------------------------------------------------------------------------


def effective_band(tool: dict[str, Any], *, as_of: date) -> ActivityBand:
    """Return the band to show for a tool.

    1. ``maturity_override.tier`` when the YAML sets a valid band (the
       override must carry a justification; ``pipeline.models`` enforces it).
    2. Otherwise ``compute_maturity(tool, as_of=as_of).band``.
    """
    override = tool.get("maturity_override")
    if isinstance(override, dict):
        chosen = override.get("tier")
        if isinstance(chosen, str) and chosen in BANDS:
            return chosen  # type: ignore[return-value]
    return compute_maturity(tool, as_of=as_of).band


def _band_rank(band: ActivityBand) -> int:
    """0 = A (highest), 5 = F (lowest)."""
    return BANDS.index(band)


__all__ = [
    "ActivityBand",
    "BANDS",
    "BAND_MEANING",
    "BAND_THRESHOLDS",
    "MaturityScore",
    "RECENT_PUSH_WINDOW_DAYS",
    "SCALE_DESCRIPTION",
    "STATUS_BAND_CAP",
    "compute_maturity",
    "effective_band",
    "reference_date",
]
