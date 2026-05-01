"""SAICA Index — weekly leaderboard of how well popular AI-adjacent
GitHub repos supervise their own AI-coding workflows.

One board:

  * ``popular_oss``  — curated list in ``data/saica_index/seed_repos.yml``
    of well-known OSS projects that AI coding agents touch a lot
    (FastAPI, langchain, Astro, Pydantic, etc.).

The previous ``kg_tools`` board (KG supervisors audited against
themselves) was removed in v0.3.1.1 — its label promised something the
score didn't deliver, and self-evaluating the catalog conflicts with
the "SAICA helps tools, doesn't evaluate them" stance from v0.3.1.

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
