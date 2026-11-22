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

  1. ``seeds.load_all_boards()`` reads the seed list into ``SeedRepo`` rows.
  2. ``runner.run_index()`` audits each repo with
     :func:`pipeline.audit.analyzer.audit_repo`, scores it with
     :func:`pipeline.saica_index.score.score_report` and writes the rows
     to ``site/public/saica_index.json``, which the leaderboard page reads.
     A run with ``--limit`` must name another output file.

What the grade can and cannot say: the audit detects fewer than half of
the catalog's tools and cannot assess some failure modes at all (see the
"Limits" section of any audit report), so a grade reflects what the audit
can see, and grade A is out of reach today.

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
