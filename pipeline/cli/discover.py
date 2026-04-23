"""Unified discovery CLI.

Examples:
    python -m pipeline.cli.discover perplexity --query "AI coding agent supervision Q2 2026"
    python -m pipeline.cli.discover semantic_scholar --query "LLM code generation failure taxonomy"
    python -m pipeline.cli.discover elicit --query "How are multi-agent systems supervised?"
    python -m pipeline.cli.discover github --topic ai-agent --min-stars 500
    python -m pipeline.cli.discover runbook    # predefined SAICA-relevant batch
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from pipeline.cost_caps import CallBudget, CostCapExceeded

log = logging.getLogger("pipeline.cli.discover")

# Conservative default for the paid discovery source (Perplexity). 10 calls
# at current Sonar-Pro pricing is well under a dollar. Free sources (GitHub,
# Semantic Scholar, Elicit) don't get a budget gate — they self-throttle.
DEFAULT_PERPLEXITY_MAX_CALLS = 10

# Exit code reserved pipeline-wide for "budget hit".
EXIT_BUDGET_HIT = 3


# --------------------------------------------------------------------------- #
# runbook definitions
# --------------------------------------------------------------------------- #

RUNBOOK_PERPLEXITY = [
    "Recently launched (Q1-Q2 2026) tools for supervising autonomous coding agents",
    "New open-source AI coding agents released 2025-2026 with > 1000 GitHub stars",
    "Recent (2025-2026) documented incidents of hallucinated package names or slopsquatting in LLM code generation",
]

RUNBOOK_SEMANTIC_SCHOLAR = [
    "supervising AI coding agents",
    "LLM code generation hallucination",
    "MCP server security slopsquatting",
    "faceted classification knowledge graph",
]

# Exactly 4 queries — well under the 100/day budget.
RUNBOOK_ELICIT = [
    "What supervision frameworks exist for autonomous AI coding agents published in 2025 or 2026?",
    "Recent empirical studies of failure modes in LLM agents",
    "Knowledge graph based classification of AI tools and libraries",
    "Human-in-the-loop controls for coding agents",
]

RUNBOOK_GITHUB = [
    "topic:ai-agent stars:>500 pushed:>2026-01-01",
    "topic:llm-guardrails stars:>100 pushed:>2026-01-01",
    "topic:code-generation topic:agent stars:>500",
]


# --------------------------------------------------------------------------- #
# individual commands
# --------------------------------------------------------------------------- #


def _run_perplexity(
    query: str,
    model: str,
    recency: Optional[str],
    limit: Optional[int],
    *,
    budget: Optional[CallBudget] = None,
) -> int:
    from pipeline.sources import perplexity

    inserted = perplexity.search(
        query, model=model, recency_filter=recency, limit=limit, budget=budget
    )
    print(f"[perplexity] {query!r} -> {len(inserted)} rows")
    return len(inserted)


def _run_semantic_scholar(query: str, limit: int, year: Optional[str]) -> int:
    from pipeline.sources import semantic_scholar

    inserted = semantic_scholar.search(query, limit=limit, year=year)
    print(f"[semantic_scholar] {query!r} -> {len(inserted)} rows")
    return len(inserted)


def _run_elicit(query: str, limit: int) -> int:
    from pipeline.sources import elicit

    inserted = elicit.search(query, limit=limit)
    print(f"[elicit] {query!r} -> {len(inserted)} rows")
    return len(inserted)


def _run_github(
    topic: Optional[str],
    language: Optional[str],
    min_stars: int,
    pushed_after: Optional[str],
    per_page: int,
    raw_query: Optional[str] = None,
) -> int:
    from pipeline.sources import github

    inserted = github.search_code(
        topic=topic,
        language=language,
        min_stars=min_stars,
        pushed_after=pushed_after,
        per_page=per_page,
        raw_query=raw_query,
    )
    label = raw_query or f"topic={topic} lang={language} stars>{min_stars} pushed>{pushed_after}"
    print(f"[github] {label!r} -> {len(inserted)} rows")
    return len(inserted)


def _run_runbook() -> int:
    total = 0
    log.info("runbook: perplexity (%d queries)", len(RUNBOOK_PERPLEXITY))
    for q in RUNBOOK_PERPLEXITY:
        try:
            total += _run_perplexity(q, "sonar-pro", None, None)
        except Exception as exc:  # noqa: BLE001
            log.warning("perplexity runbook query failed: %s", exc)

    log.info("runbook: semantic_scholar (%d queries)", len(RUNBOOK_SEMANTIC_SCHOLAR))
    for q in RUNBOOK_SEMANTIC_SCHOLAR:
        try:
            total += _run_semantic_scholar(q, 15, "2024-")
        except Exception as exc:  # noqa: BLE001
            log.warning("semantic_scholar runbook query failed: %s", exc)

    log.info("runbook: elicit (%d queries, budget-guarded)", len(RUNBOOK_ELICIT))
    for q in RUNBOOK_ELICIT:
        try:
            total += _run_elicit(q, 10)
        except Exception as exc:  # noqa: BLE001
            log.warning("elicit runbook query failed: %s", exc)

    log.info("runbook: github (%d queries)", len(RUNBOOK_GITHUB))
    for q in RUNBOOK_GITHUB:
        try:
            total += _run_github(
                topic=None, language=None, min_stars=0, pushed_after=None, per_page=50, raw_query=q
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("github runbook query failed: %s", exc)

    print(f"[runbook] total rows inserted: {total}")
    return total


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pipeline.cli.discover", description="Run discovery-source searches")
    sub = p.add_subparsers(dest="command", required=True)

    pp = sub.add_parser("perplexity", help="Perplexity sonar web search")
    pp.add_argument("--query", required=True)
    pp.add_argument("--model", default="sonar-pro")
    pp.add_argument("--recency", default=None, help="month|week|day|hour")
    pp.add_argument("--limit", type=int, default=None)
    pp.add_argument(
        "--max-calls",
        type=int,
        default=DEFAULT_PERPLEXITY_MAX_CALLS,
        help=(
            f"hard cap on Perplexity HTTP calls for this run "
            f"(default {DEFAULT_PERPLEXITY_MAX_CALLS}). "
            f"Exits with code {EXIT_BUDGET_HIT} when exceeded."
        ),
    )
    pp.add_argument(
        "--max-cost-tokens",
        type=int,
        default=None,
        help="optional soft cap on total tokens across the run",
    )

    ps = sub.add_parser("semantic_scholar", help="Semantic Scholar paper search")
    ps.add_argument("--query", required=True)
    ps.add_argument("--limit", type=int, default=15)
    ps.add_argument("--year", default=None, help="e.g. '2024-' or '2020-2026'")

    pe = sub.add_parser("elicit", help="Elicit systematic-review search")
    pe.add_argument("--query", required=True)
    pe.add_argument("--limit", type=int, default=10)

    pg = sub.add_parser("github", help="GitHub repo search")
    pg.add_argument("--topic", default=None)
    pg.add_argument("--language", default=None)
    pg.add_argument("--min-stars", type=int, default=500)
    pg.add_argument("--pushed-after", default=None, help="YYYY-MM-DD")
    pg.add_argument("--per-page", type=int, default=50)
    pg.add_argument("--raw-query", default=None, help="verbatim GitHub search string")

    sub.add_parser("runbook", help="Run the predefined SAICA-relevant batch of queries")

    return p


def main(argv: Optional[list[str]] = None) -> int:
    from pipeline.config import load_env_once
    from pipeline.logging_config import configure_logging

    configure_logging()
    load_env_once()

    args = build_parser().parse_args(argv)
    cmd = args.command

    if cmd == "perplexity":
        budget = CallBudget(
            max_calls=args.max_calls,
            max_tokens_estimate=args.max_cost_tokens,
        )
        try:
            _run_perplexity(
                args.query, args.model, args.recency, args.limit, budget=budget
            )
        except CostCapExceeded as exc:
            print(
                f"[budget] cost cap hit: {exc}; {budget.summary()}",
                file=sys.stderr,
            )
            return EXIT_BUDGET_HIT
    elif cmd == "semantic_scholar":
        _run_semantic_scholar(args.query, args.limit, args.year)
    elif cmd == "elicit":
        _run_elicit(args.query, args.limit)
    elif cmd == "github":
        _run_github(
            args.topic, args.language, args.min_stars, args.pushed_after, args.per_page, args.raw_query
        )
    elif cmd == "runbook":
        _run_runbook()
    else:  # pragma: no cover
        print(f"unknown command {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
