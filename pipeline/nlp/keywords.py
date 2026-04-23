"""Failure-mode keyword dictionary for SAICA-KG NLP pre-processing.

Maps query terms + synonyms to SAICA-KG FailureMode ids. Used by
``pipeline.nlp.preprocess.keyword_hits`` for keyword-level tagging of
raw discovery results.
"""

from __future__ import annotations


FAILURE_MODE_KEYWORDS: dict[str, list[str]] = {
    "fabrication": [
        "hallucination", "hallucinate", "hallucinated", "fabrication",
        "non-existent api", "imagined package", "phantom dependency",
        "invented function",
    ],
    "obsolescence": [
        "deprecated", "retired api", "stale api", "outdated library",
        "version drift", "library evolution", "deprecation",
    ],
    "dependency_blindness": [
        "reinvention", "reinvent", "duplicate implementation", "code copycat",
        "reimplements", "reimplementing", "ecosystem duplication",
        "ignores existing",
    ],
    "logic_error": [
        "incorrect logic", "silent fail", "compiles but wrong",
        "passes type check fails correctness",
    ],
    "security_vulnerability": [
        "injection", "sql injection", "xss", "secret leak", "weak crypto",
        "insecure deserialization", "cve", "bandit", "semgrep",
    ],
    "scope_creep": [
        "scope creep", "unauthorized action", "boundary violation",
        "role violation", "acted outside", "unsanctioned",
    ],
    "context_pollution": [
        "context drift", "hallucination spiral", "context window overflow",
        "trajectory drift", "long-context degradation", "memory poisoning",
    ],
    "supply_chain_attack": [
        "slopsquatting", "typosquatting", "compromised package",
        "malicious mcp", "compromised mcp server", "supply chain attack",
        "supply-chain vulnerability", "asi04",
    ],
}

# High-signal publisher/venue names — a hit bumps relevance.
HIGH_SIGNAL_ORGS: list[str] = [
    "anthropic", "openai", "google", "microsoft", "meta", "huggingface",
    "langchain", "deeplearning.ai", "nvidia", "sourcegraph",
]

# Tool-shape signals (heuristic: is this a Tool or a Paper?)
TOOL_SIGNALS: list[str] = [
    "cli", "framework", "sdk", "agent", "guardrails", "sandbox",
    "registry", "platform", "extension",
]

PAPER_SIGNALS: list[str] = [
    "arxiv", "ieee", "usenix", "icse", "fse", "naacl", "emnlp",
    "neurips", "iclr", "acm", "aaai",
]
