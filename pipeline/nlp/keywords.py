"""Failure-mode keyword dictionary for SAICA-KG NLP pre-processing.

Maps query terms + synonyms to SAICA-KG FailureMode ids. Used by
``pipeline.nlp.preprocess.keyword_hits`` for keyword-level tagging of
raw discovery results.
"""

from __future__ import annotations


FAILURE_MODE_KEYWORDS: dict[str, list[str]] = {
    "fabrication": [
        "hallucination",
        "hallucinate",
        "hallucinated",
        "fabrication",
        "non-existent api",
        "imagined package",
        "phantom dependency",
        "invented function",
    ],
    "obsolescence": [
        "deprecated",
        "retired api",
        "stale api",
        "outdated library",
        "version drift",
        "library evolution",
        "deprecation",
    ],
    "dependency_blindness": [
        "reinvention",
        "reinvent",
        "duplicate implementation",
        "code copycat",
        "reimplements",
        "reimplementing",
        "ecosystem duplication",
        "ignores existing",
        # Structural-duplication framing — sentrux et al. surface this
        # as a "redundancy" metric across files rather than as a
        # per-call reinvention. The first three terms are how those
        # tools talk about it; the last is the canonical compsci name.
        "redundant implementation",
        "scattered responsibilities",
        "duplicated functionality",
        "code duplication",
    ],
    "logic_error": [
        "incorrect logic",
        "silent fail",
        "compiles but wrong",
        "passes type check fails correctness",
    ],
    "security_vulnerability": [
        "injection",
        "sql injection",
        "xss",
        "secret leak",
        "weak crypto",
        "insecure deserialization",
        "cve",
        "bandit",
        "semgrep",
    ],
    "scope_creep": [
        "scope creep",
        "unauthorized action",
        "boundary violation",
        "role violation",
        "acted outside",
        "unsanctioned",
    ],
    "context_pollution": [
        "context drift",
        "hallucination spiral",
        "context window overflow",
        "trajectory drift",
        "long-context degradation",
        "memory poisoning",
    ],
    "cascading_failure": [
        # Generic regression-cascade vocabulary used by DAPLab and
        # follow-on writeups.
        "cascading failure",
        "cascading error",
        "regression cascade",
        "recovery loop",
        "fix introduced new",
        "spiral",
        # Architectural-decay framing — the way sentrux et al. describe
        # the same compounding-quality-loss pattern at codebase rather
        # than agent-action granularity. Picked up via Stage 0b synonym
        # queries against discovery sources.
        "architectural decay",
        "structural drift",
        "modularity degradation",
        "dependency cycle",
        "circular dependency",
        "session-over-session degradation",
    ],
    "supply_chain_attack": [
        "slopsquatting",
        "typosquatting",
        "compromised package",
        "malicious mcp",
        "compromised mcp server",
        "supply chain attack",
        "supply-chain vulnerability",
        "asi04",
    ],
}

# High-signal publisher/venue names — a hit bumps relevance.
HIGH_SIGNAL_ORGS: list[str] = [
    "anthropic",
    "openai",
    "google",
    "microsoft",
    "meta",
    "huggingface",
    "langchain",
    "deeplearning.ai",
    "nvidia",
    "sourcegraph",
]

# Tool-shape signals (heuristic: is this a Tool or a Paper?)
#
# Kept for back-compat with ``classify_kind``: coarse category words that steer
# the tool-vs-paper decision. Don't use for relevance boosting — use
# ``TOOL_SHAPE_SIGNALS`` below for that, which is a richer domain-weighted set.
TOOL_SIGNALS: list[str] = [
    "cli",
    "framework",
    "sdk",
    "agent",
    "guardrails",
    "sandbox",
    "registry",
    "platform",
    "extension",
]

# Tool-shape signals used by relevance scoring. Each is a distinct phrase that
# indicates "this source is about a real supervision/agent-safety tool or
# platform" — even when no failure-mode keyword matches. Each hit contributes
# a small bump to relevance (see ``pipeline.nlp.preprocess.relevance_score``),
# capped so no one signal dominates. Phrases are matched case-insensitively
# with word boundaries.
TOOL_SHAPE_SIGNALS: list[str] = [
    # MCP / model-context-protocol ecosystem
    "mcp-server",
    "mcp server",
    "model context protocol",
    "mcp tool",
    # guardrails
    "guardrail",
    "guardrails",
    "guardrail framework",
    # supervision / oversight
    "supervisor",
    "supervise",
    "supervision",
    "oversight",
    # sandboxing / isolated execution
    "sandbox",
    "sandboxed",
    "isolated execution",
    # evaluation harnesses
    "evaluator",
    "eval framework",
    "llm-as-judge",
    # observability
    "observability",
    "tracing",
    "tracer",
    "telemetry",
    # red-teaming / adversarial
    "red team",
    "red-team",
    "red-teaming",
    "adversarial test",
    # structured output / constrained decoding
    "structured output",
    "constrained decoding",
    "tool calling",
    # agent frameworks / runtimes
    "agent framework",
    "agent orchestration",
    "agent runtime",
    # policy enforcement
    "policy enforcement",
    "policy engine",
    "allow-list",
    "deny-list",
    # architectural / structural-health sensors (sentrux-class)
    "architectural sensor",
    "structural health",
    "modularity score",
    "dependency graph",
    "treemap",
    "code health",
    "quality signal",
]

PAPER_SIGNALS: list[str] = [
    "arxiv",
    "ieee",
    "usenix",
    "icse",
    "fse",
    "naacl",
    "emnlp",
    "neurips",
    "iclr",
    "acm",
    "aaai",
]
