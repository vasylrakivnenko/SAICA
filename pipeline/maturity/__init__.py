"""Activity band of a tool (A–F), computed from its YAML alone.

The band is a bin of a score built from stars, a recent upstream push and
the number of integration surfaces (plus citations and evaluations where
the catalogue records them). It measures popularity and activity; it is
not a level of evidence. Until 2026-11-21 the bands were called tiers 1A,
1B, 2A, 2B, 3, 4, after clinical-evidence levels they did not honour.

Curators may override the computed band with a ``maturity_override``
block in the tool YAML; it must carry a justification.

See :mod:`pipeline.maturity.score` for the formula and
:mod:`pipeline.maturity.evidence` for what SAICA-Bench measured.
"""

from pipeline.maturity.score import (
    ActivityBand,
    MaturityScore,
    compute_maturity,
    effective_band,
    reference_date,
)

__all__ = [
    "ActivityBand",
    "MaturityScore",
    "compute_maturity",
    "effective_band",
    "reference_date",
]
