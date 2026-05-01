"""Stage 9 — deterministic maturity tier (Levels-of-Evidence analog).

Borrows the PharmGKB / CPIC notation pattern: each tool gets a tier
in ``{1A, 1B, 2A, 2B, 3, 4}`` derived from observable facets. The
mapping is deterministic and re-computable from the YAML alone, so
the leaderboard / web pages can render tiers without storing them.

Curators may override the computed tier by adding a
``maturity_override`` block to the tool YAML; the override carries a
required justification and is rendered publicly so the override is
auditable.

See :mod:`pipeline.maturity.score` for the formula. CLI:
``python -m pipeline.maturity.cli``.
"""

from pipeline.maturity.score import (
    MaturityScore,
    MaturityTier,
    compute_maturity,
    effective_tier,
)

__all__ = [
    "MaturityScore",
    "MaturityTier",
    "compute_maturity",
    "effective_tier",
]
