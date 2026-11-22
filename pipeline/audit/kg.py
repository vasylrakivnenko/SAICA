"""KG lookups for the audit analyzer.

Every read goes through :mod:`pipeline.kg` (one loader, validated nodes,
one error policy). This module only adds what the audit needs on top: the
evidence tier of a tool × failure-mode pair and two small lookups.

The list of failure modes and their display names come from
``data/failure_modes/`` through that loader; nothing is typed in here.
"""

from __future__ import annotations

from pathlib import Path

from pipeline import kg as _kg

# Kept for the scripts that import it from here (validator/screen_*.py).
REPO_ROOT = Path(__file__).resolve().parents[2]

# Keyword set for "rationale mentions FM" tier-2 detection.
# Copied verbatim from research/plot_tool_fm_heatmap.py to keep the rule
# identical.
FM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fabrication": ("fabricat", "hallucin", "nonexistent api", "made-up", "confabulat"),
    "obsolescence": ("obsolesc", "deprecat", "outdated", "stale api", "api evolution"),
    "dependency_blindness": (
        "dependency blind",
        "dependency-blind",
        "reinvent",
        "home-rolled",
        "duplicate code",
        "reimplement",
    ),
    "logic_error": (
        "logic error",
        "logic bug",
        "reasoning error",
        "incorrect behavior",
        "wrong answer",
    ),
    "security_vulnerability": (
        "security vuln",
        "vulnerab",
        " cve",
        "insecure",
        "sast",
        "taint",
    ),
    "scope_creep": (
        "scope creep",
        "off-task",
        "off task",
        "unrelated change",
        "out-of-scope",
    ),
    "context_pollution": (
        "context polluti",
        "prompt inject",
        "jailbreak",
        "context manipul",
        "indirect injection",
    ),
    "supply_chain_attack": (
        "supply chain",
        "slopsquat",
        "typosquat",
        "malicious package",
        "malicious depend",
    ),
    "cascading_failure": (
        "cascading",
        "error propagat",
        "runaway",
        "cascade",
    ),
    "incomplete_execution": (
        "incomplete",
        "partial execution",
        "unfinished",
        "stop short",
        "half-done",
    ),
    "test_manipulation": (
        "test manipul",
        "test gaming",
        "reward hack",
        "spec gaming",
        "gaming the test",
    ),
}


# ---------------------------------------------------------------------------
# Loaders (thin wrappers over pipeline.kg)
# ---------------------------------------------------------------------------


def load_tool_index() -> dict[str, dict]:
    """``{tool_id: validated tool mapping}`` for every tool in the KG."""
    return _kg.load().tool_dicts()


def load_failure_modes() -> list[str]:
    """Failure-mode ids found in ``data/failure_modes/``, sorted."""
    return list(_kg.load().failure_mode_ids())


def fm_display(fm_id: str) -> str:
    """Display name of a failure mode, from its file's ``name``."""
    return (
        _kg.load().failure_mode_names().get(fm_id)
        or fm_id.replace("_", " ").capitalize()
    )


# ---------------------------------------------------------------------------
# Per-mapping evidence tier (mirrors research/plot_tool_fm_heatmap.py)
# ---------------------------------------------------------------------------


def _rationale_mentions(text: str, fm_id: str) -> bool:
    if not text:
        return False
    t = text.lower()
    if fm_id in t or fm_id.replace("_", " ") in t or fm_id.replace("_", "-") in t:
        return True
    for kw in FM_KEYWORDS.get(fm_id, ()):
        if kw in t:
            return True
    return False


def _has_citation_evidence(tool: dict) -> bool:
    return bool(
        tool.get("cited_in") or tool.get("documented_in") or tool.get("evaluated_on")
    )


def cell_tier(tool: dict, fm_id: str) -> int:
    """Compute evidence tier 0..3 for a single (tool, failure_mode) pair.

    1 — declared in ``addresses_failure_modes``.
    2 — + ``inclusion_rationale`` discusses the FM.
    3 — + tool has any ``cited_in`` / ``documented_in`` / ``evaluated_on``.
    """
    addressed = fm_id in (tool.get("addresses_failure_modes") or [])
    if not addressed:
        return 0
    mentioned = _rationale_mentions(tool.get("inclusion_rationale") or "", fm_id)
    cited = _has_citation_evidence(tool)
    if mentioned and cited:
        return 3
    if mentioned:
        return 2
    return 1


def tool_url(tool_id: str) -> str:
    """Site path of a tool page (``/tools/<id>``)."""
    return f"/tools/{tool_id}"


__all__ = [
    "FM_KEYWORDS",
    "REPO_ROOT",
    "cell_tier",
    "fm_display",
    "load_failure_modes",
    "load_tool_index",
    "tool_url",
]
