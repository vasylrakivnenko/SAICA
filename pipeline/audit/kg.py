"""KG loader and lookup helpers for the audit analyzer.

Loads ``data/tools/*.yml`` and ``data/failure_modes/*.yml`` from the repo
root into in-memory dicts and exposes simple lookups used by detectors,
coverage grid construction, and gap recommendations.

Self-contained: no imports from ``pipeline.ask`` or other pipeline packages
(per Phase-1 hard constraint). Mirrors the YAML field names directly.
"""
from __future__ import annotations

import glob
from functools import lru_cache
from pathlib import Path

import yaml

# Resolve the repo root from this file: pipeline/audit/kg.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "data" / "tools"
FM_DIR = REPO_ROOT / "data" / "failure_modes"

# The 11-mode canonical set used by the heatmap.  Source of truth is the
# YAML stems, but we expose the constant so callers can iterate in stable
# order without re-globbing.
CANONICAL_FAILURE_MODES: tuple[str, ...] = (
    "cascading_failure",
    "context_pollution",
    "dependency_blindness",
    "fabrication",
    "incomplete_execution",
    "logic_error",
    "obsolescence",
    "scope_creep",
    "security_vulnerability",
    "supply_chain_attack",
    "test_manipulation",
)

# Display labels (matches research/plot_tool_fm_heatmap.py).
FM_DISPLAY: dict[str, str] = {
    "fabrication": "Fabrication",
    "obsolescence": "Obsolescence",
    "dependency_blindness": "Dependency Blindness",
    "logic_error": "Logic Error",
    "security_vulnerability": "Security Vulnerability",
    "scope_creep": "Scope Creep",
    "context_pollution": "Context Pollution",
    "supply_chain_attack": "Supply-Chain Attack",
    "cascading_failure": "Cascading Failure",
    "incomplete_execution": "Incomplete Execution",
    "test_manipulation": "Test Manipulation",
}

# Keyword set for "rationale mentions FM" tier-2 detection.
# Copied verbatim from research/plot_tool_fm_heatmap.py to keep the rule
# identical.
FM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fabrication": ("fabricat", "hallucin", "nonexistent api", "made-up", "confabulat"),
    "obsolescence": ("obsolesc", "deprecat", "outdated", "stale api", "api evolution"),
    "dependency_blindness": (
        "dependency blind", "dependency-blind", "reinvent", "home-rolled",
        "duplicate code", "reimplement",
    ),
    "logic_error": (
        "logic error", "logic bug", "reasoning error", "incorrect behavior",
        "wrong answer",
    ),
    "security_vulnerability": (
        "security vuln", "vulnerab", " cve", "insecure", "sast", "taint",
    ),
    "scope_creep": (
        "scope creep", "off-task", "off task", "unrelated change",
        "out-of-scope",
    ),
    "context_pollution": (
        "context polluti", "prompt inject", "jailbreak", "context manipul",
        "indirect injection",
    ),
    "supply_chain_attack": (
        "supply chain", "slopsquat", "typosquat", "malicious package",
        "malicious depend",
    ),
    "cascading_failure": (
        "cascading", "error propagat", "runaway", "cascade",
    ),
    "incomplete_execution": (
        "incomplete", "partial execution", "unfinished", "stop short",
        "half-done",
    ),
    "test_manipulation": (
        "test manipul", "test gaming", "reward hack", "spec gaming",
        "gaming the test",
    ),
}


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_tool_index() -> dict[str, dict]:
    """Return ``{tool_id: tool_yaml_dict}`` for every tool in ``data/tools``."""
    index: dict[str, dict] = {}
    for path in sorted(glob.glob(str(TOOLS_DIR / "*.yml"))):
        try:
            doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(doc, dict):
            continue
        tid = doc.get("id") or Path(path).stem
        index[str(tid)] = doc
    return index


@lru_cache(maxsize=1)
def load_failure_modes() -> list[str]:
    """Return list of failure-mode ids found on disk, sorted."""
    if not FM_DIR.exists():
        return list(CANONICAL_FAILURE_MODES)
    ids = sorted(p.stem for p in FM_DIR.glob("*.yml"))
    return ids or list(CANONICAL_FAILURE_MODES)


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
        tool.get("cited_in")
        or tool.get("documented_in")
        or tool.get("evaluated_on")
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


# ---------------------------------------------------------------------------
# Convenience lookups
# ---------------------------------------------------------------------------

def tools_by_failure_mode(fm: str) -> list[dict]:
    """Return all KG tools whose ``addresses_failure_modes`` includes ``fm``."""
    out = []
    for tool in load_tool_index().values():
        fms = tool.get("addresses_failure_modes") or []
        if fm in fms:
            out.append(tool)
    return out


def tools_by_surface(surface: str) -> list[dict]:
    """Return KG tools whose ``integration_surfaces`` includes ``surface``."""
    out = []
    for tool in load_tool_index().values():
        surfaces = tool.get("integration_surfaces") or []
        if surface in surfaces:
            out.append(tool)
    return out


def tier_sum(tool: dict, fm_ids: list[str] | None = None) -> int:
    """Sum of cell tiers across all FMs (for ranking)."""
    fms = fm_ids if fm_ids is not None else load_failure_modes()
    return sum(cell_tier(tool, fm) for fm in fms)


def tool_url(tool_id: str) -> str:
    """Site URL for a tool, matching the /tools/<id> convention."""
    return f"/tools/{tool_id}"


__all__ = [
    "CANONICAL_FAILURE_MODES",
    "FM_DISPLAY",
    "FM_KEYWORDS",
    "REPO_ROOT",
    "cell_tier",
    "load_failure_modes",
    "load_tool_index",
    "tier_sum",
    "tool_url",
    "tools_by_failure_mode",
    "tools_by_surface",
]
