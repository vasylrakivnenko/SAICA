"""SAICA Index — weekly leaderboard of how well popular AI-adjacent
GitHub repos supervise their own AI-coding workflows.

Two boards:

  * ``kg_tools``     — auto-derived from ``data/tools/*.yml`` (every tool
    in the KG, audited against itself: "do supervisors supervise
    themselves?"). Free + meta + always in sync with the corpus.

  * ``popular_oss``  — curated list in ``data/saica_index/seed_repos.yml``
    of well-known OSS projects that AI coding agents touch a lot
    (FastAPI, langchain, Astro, Pydantic, etc.). The PR-/marketing-
    weight board.

Pipeline:

  1. ``seeds.load_boards()`` resolves both boards into
     ``list[SeedRepo]``.
  2. ``runner.run_index(boards)`` audits each repo via
     :func:`pipeline.audit.analyzer.audit_repo`, scores it with
     :func:`pipeline.saica_index.score.score_report`, and serialises
     the result.
  3. The resulting ``IndexSnapshot`` is written to
     ``site/public/saica_index.json`` so the static leaderboard page
     can render it without a backend.

The scoring formula is documented in
:mod:`pipeline.saica_index.score` (single source of truth).
"""

from pipeline.saica_index.score import (
    LetterGrade,
    RepoScore,
    grade_for,
    score_report,
)

__all__ = [
    "LetterGrade",
    "RepoScore",
    "grade_for",
    "score_report",
]
