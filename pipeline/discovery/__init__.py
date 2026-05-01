"""Discovery-stage helpers (Stage 3 of the v2 ingestion pipeline).

Top-level entry: :func:`pipeline.discovery.novelty.classify`. Given a
candidate's canonical id (github URL / arXiv id / DOI / kebab slug),
returns one of:

  * ``DROP``           — already in the KG, no new evidence; curator queue
                          stays clean.
  * ``UPDATE_QUEUE``   — already in the KG, but the candidate carries new
                          evidence (paper citation, FM hit, fresher
                          release) — route to the lighter update workflow.
  * ``CONTINUE``       — genuinely new; pass to Stage 4 (composite quality
                          gate) and beyond.

PharmGKB does this against PharmGKB; without it, curators waste time
re-reviewing tools they already merged.
"""

from pipeline.discovery.novelty import (
    NoveltyDecision,
    NoveltyOutcome,
    classify,
    extract_canonical_ids,
)

__all__ = [
    "NoveltyDecision",
    "NoveltyOutcome",
    "classify",
    "extract_canonical_ids",
]
