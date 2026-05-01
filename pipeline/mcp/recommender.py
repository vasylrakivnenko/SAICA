"""Recommendation engine for the SAICA-KG MCP server.

Two modes, per the v0.2.1 design:

* **Targeted** — caller passes a list of failure modes; we return supervisors
  that declare coverage for those failure modes.
* **Full suite** (default) — caller passes no failure modes; we return the
  minimum set of supervisors that *together* cover all 11 failure modes.
  Greedy set cover, then a small depth pad of the highest-evidence
  remaining supervisors.

Two filter layers gate every recommendation:

1. **CODING_AGENT_IDS.** As of v0.3.1 the KG no longer catalogs coding-
   agent systems themselves (Claude Code, Cursor, Replit Agent, Codex,
   etc.) — SAICA is for *modular supervisors you add to a stack*, not
   for the agents that consume that stack. This frozenset is kept as
   a defense-in-depth safety net: if a coding-agent YAML ever re-lands
   in ``data/tools/`` (by accident or via an upstream PR), the
   recommender still won't surface it. Empty on the happy path.

2. **RECOMMENDATION_BLOCKLIST.** A tiny list of tools whose role is too
   ambiguous to be a confident recommendation regardless of who's asking
   (e.g. an image-diffusion GUI that incidentally declares ``scope_creep``
   coverage but doesn't supervise *coding* in any practical sense).
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

import yaml

from pipeline.shared.priorities import coverage_value, reliability
from pipeline.shared.trending import effective_stars, is_trending

# Resolve REPO at import time so subprocess invocations from any CWD work.
REPO = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO / "data" / "tools"

# ---------------------------------------------------------------------------
# Filter layers
# ---------------------------------------------------------------------------

# Defense-in-depth. As of v0.3.1, none of these IDs exist in
# ``data/tools/`` — coding-agent systems were removed from the catalog
# because SAICA recommends supervisors *for* agents, not agents
# themselves. We keep the list so that if any of these YAMLs ever
# re-lands (accidentally or via an upstream PR), the recommender still
# refuses to surface it. Frameworks / libraries / MCP servers / proxy
# gateways stay in the catalog and are NOT in this list.
CODING_AGENT_IDS: frozenset[str] = frozenset(
    {
        # IDE / desktop coding agents
        "cursor",
        "windsurf",
        "zed-agent",
        # Hosted coding agents
        "replit-agent",
        "v0",
        "devin",
        # IDE-extension coding agents
        "github-copilot",
        "continue-dev",
        "sourcegraph-cody",
        # CLI coding agents
        "claude-code",
        "aider",
        "openhands",
        "swe-agent",
        "codex-cli",
        "gemini-cli",
        "cline",
    }
)

# Tools we never recommend, regardless of asker. Reserved for genuinely
# ambiguous cases — e.g. an image-generation GUI whose declared FM coverage
# doesn't translate to "stop bugs in coding agents." Keep this list as
# small as possible; prefer fixing the YAML facets to better reflect role
# over silently blocking.
RECOMMENDATION_BLOCKLIST: frozenset[str] = frozenset(
    {
        "comfyui",  # diffusion-model GUI; declared scope_creep coverage is for image workflows, not code.
    }
)

# All 11 failure modes, kept stable here so the full-suite mode doesn't
# silently drift if a new FM lands in data/failure_modes/.
ALL_FAILURE_MODES: tuple[str, ...] = (
    "fabrication",
    "obsolescence",
    "dependency_blindness",
    "logic_error",
    "security_vulnerability",
    "scope_creep",
    "context_pollution",
    "supply_chain_attack",
    "cascading_failure",
    "incomplete_execution",
    "test_manipulation",
)


# ---------------------------------------------------------------------------
# KG access
# ---------------------------------------------------------------------------

_TOOL_INDEX_CACHE: dict[str, dict[str, Any]] | None = None


def _load_tools() -> dict[str, dict[str, Any]]:
    """Load all tool YAMLs as a dict keyed by id, cached per process."""
    global _TOOL_INDEX_CACHE
    if _TOOL_INDEX_CACHE is not None:
        return _TOOL_INDEX_CACHE
    out: dict[str, dict[str, Any]] = {}
    for path in glob.glob(str(TOOLS_DIR / "*.yml")):
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        if isinstance(doc, dict) and doc.get("id"):
            out[str(doc["id"])] = doc
    _TOOL_INDEX_CACHE = out
    return out


def _eligible(
    tool: dict[str, Any],
    *,
    agent_kind: str | None,
) -> bool:
    """True if `tool` may be recommended given the asking agent."""
    tid = str(tool.get("id") or "")
    if tid in RECOMMENDATION_BLOCKLIST:
        return False
    if agent_kind and agent_kind in CODING_AGENT_IDS:
        # Asking agent is a coding agent — drop all coding-agent peers
        # AND the asker itself (don't recommend X to X).
        if tid in CODING_AGENT_IDS:
            return False
    return True


def _score_for_fm(
    tool: dict[str, Any],
    fm: str,
) -> tuple[int, int, float]:
    """Score a tool for a single FM. Higher is better.

    (paradigm_pref, evidence_tier, effective_stars) — paradigm_pref is +1 for
    prevention/detection (proactive), 0 for correction/recovery (reactive).
    Evidence tier is the same 0..3 from the heatmap (declared / + rationale
    mention / + external citation), folded down to a 0/1 here for ranking
    simplicity. The third coordinate is *effective* stars: real stars
    multiplied by ``TRENDING_BOOST`` when the tool's repository is on
    github.com/trending. This makes a trending tool with 1k stars beat a
    non-trending peer with up to ~1.43k stars without overriding tools
    that are genuinely much more popular.
    """
    paradigm = str(tool.get("control_paradigm") or "")
    paradigm_pref = 1 if paradigm in ("prevention", "detection") else 0
    rationale = str(tool.get("inclusion_rationale") or "").lower()
    fm_keywords = (fm, fm.replace("_", " "), fm.replace("_", "-"))
    evidence = 1 if any(k in rationale for k in fm_keywords) else 0
    return (paradigm_pref, evidence, effective_stars(tool))


def _to_recommendation_dict(tool: dict[str, Any]) -> dict[str, Any]:
    """Reduce a tool YAML to the public recommendation shape returned by MCP."""
    tid = str(tool.get("id") or "")
    return {
        "tool_id": tid,
        "tool_name": str(tool.get("name") or tid),
        "control_paradigm": str(tool.get("control_paradigm") or ""),
        "temporal_phase": str(tool.get("temporal_phase") or ""),
        "autonomy_level": str(tool.get("autonomy_level") or ""),
        "integration_surfaces": list(tool.get("integration_surfaces") or []),
        "addresses_failure_modes": list(tool.get("addresses_failure_modes") or []),
        "stars": (int(tool["stars"]) if tool.get("stars") is not None else None),
        "trending": is_trending(tool),
        "url": f"/tools/{tid}",
        "tagline": tool.get("tagline"),
    }


# ---------------------------------------------------------------------------
# Mode 1: targeted recommendation for a specific list of failure modes
# ---------------------------------------------------------------------------


def recommend_for_failure_modes(
    failure_modes: list[str],
    *,
    agent_kind: str | None = None,
    per_fm: int = 3,
) -> dict[str, Any]:
    """Return up to ``per_fm`` supervisors for each requested failure mode.

    Output shape (returned to the MCP caller as a dict):

    .. code-block:: json

        {
          "mode": "targeted",
          "agent_kind": "claude-code",
          "by_failure_mode": {
            "scope_creep": [Recommendation, ...],
            ...
          }
        }
    """
    unknown = [fm for fm in failure_modes if fm not in ALL_FAILURE_MODES]
    if unknown:
        raise ValueError(
            f"unknown failure_mode(s): {unknown}. Valid: {list(ALL_FAILURE_MODES)}"
        )

    tools = _load_tools()
    by_fm: dict[str, list[dict[str, Any]]] = {}
    for fm in failure_modes:
        candidates = [
            t
            for t in tools.values()
            if fm in (t.get("addresses_failure_modes") or [])
            and _eligible(t, agent_kind=agent_kind)
        ]
        candidates.sort(key=lambda t: _score_for_fm(t, fm), reverse=True)
        by_fm[fm] = [_to_recommendation_dict(t) for t in candidates[:per_fm]]
    return {
        "mode": "targeted",
        "agent_kind": agent_kind,
        "by_failure_mode": by_fm,
    }


# ---------------------------------------------------------------------------
# Three-tier coverage modes (replace the prior "full_suite" with-pad design)
#
# All three use weighted greedy selection where the score for adding a tool
# is sum(priority(fm) for fm in newly-covered) * reliability(tool).
# Eligibility / blocklist / coding-agent-peer filters are applied identically.
#
#   minimum (1 tool):  the single highest-scoring tool. Best "starter".
#   optimal (3 tools): greedy weighted set cover capped at 3. Best
#                      "responsible kit" — covers the highest-priority FMs
#                      with the smallest practical stack.
#   full (variable N): greedy weighted set cover until ALL 11 FMs are
#                      covered (no pad). Best "MECE coverage" — answers
#                      "what's the smallest set that addresses every FM
#                      we know about?". Typically 4-5 tools.
# ---------------------------------------------------------------------------

LEVELS: tuple[str, ...] = ("minimum", "optimal", "full")
DEFAULT_LEVEL: str = "optimal"
OPTIMAL_K: int = 3


def _eligible_pool(agent_kind: str | None) -> list[dict[str, Any]]:
    """Tools eligible to be recommended given the asker's agent kind."""
    return [
        t
        for t in _load_tools().values()
        if _eligible(t, agent_kind=agent_kind)
        and (t.get("addresses_failure_modes") or [])
    ]


def _greedy_weighted_pick(
    pool: list[dict[str, Any]],
    *,
    target_fms: set[str],
    already_covered: set[str],
) -> tuple[dict[str, Any] | None, float]:
    """Pick the tool maximising weighted_coverage * reliability over the
    FMs in ``target_fms`` not yet in ``already_covered``. Returns (tool, score).
    """
    remaining = target_fms - already_covered
    best: dict[str, Any] | None = None
    best_score: float = float("-inf")
    for t in pool:
        new_value = coverage_value(t, remaining)
        if new_value <= 0:
            continue
        score = new_value * (1.0 + reliability(t))
        if score > best_score:
            best, best_score = t, score
    return best, best_score


def recommend_minimum(*, agent_kind: str | None = None) -> dict[str, Any]:
    """Return the single highest-priority * reliability tool. Best starter."""
    pool = _eligible_pool(agent_kind)
    chosen, _ = _greedy_weighted_pick(
        pool,
        target_fms=set(ALL_FAILURE_MODES),
        already_covered=set(),
    )
    selected = [chosen] if chosen is not None else []
    covered = set(chosen.get("addresses_failure_modes") or []) if chosen else set()
    return {
        "mode": "minimum",
        "level": "minimum",
        "agent_kind": agent_kind,
        "tools": [_to_recommendation_dict(t) for t in selected],
        "covered_failure_modes": sorted(covered),
        "uncovered_failure_modes": sorted(set(ALL_FAILURE_MODES) - covered),
        "coverage_complete": False,
        "summary": (
            f"1 tool covers {len(covered)} of {len(ALL_FAILURE_MODES)} "
            f"failure modes (highest-priority single pick)."
            if chosen
            else "No eligible tool found."
        ),
    }


def recommend_optimal(
    *,
    agent_kind: str | None = None,
    k: int = OPTIMAL_K,
) -> dict[str, Any]:
    """Greedy weighted set cover capped at ``k`` tools. Best responsible kit."""
    pool = _eligible_pool(agent_kind)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    covered: set[str] = set()

    while len(selected) < k:
        # filter out already-picked tools without rebuilding the whole pool
        candidates = [t for t in pool if t["id"] not in selected_ids]
        chosen, _ = _greedy_weighted_pick(
            candidates,
            target_fms=set(ALL_FAILURE_MODES),
            already_covered=covered,
        )
        if chosen is None:
            break
        selected.append(chosen)
        selected_ids.add(str(chosen["id"]))
        covered |= set(chosen.get("addresses_failure_modes") or [])

    return {
        "mode": "optimal",
        "level": "optimal",
        "agent_kind": agent_kind,
        "k": k,
        "tools": [_to_recommendation_dict(t) for t in selected],
        "covered_failure_modes": sorted(covered),
        "uncovered_failure_modes": sorted(set(ALL_FAILURE_MODES) - covered),
        "coverage_complete": covered == set(ALL_FAILURE_MODES),
        "summary": (
            f"{len(selected)} tools cover {len(covered)} of "
            f"{len(ALL_FAILURE_MODES)} failure modes "
            f"(weighted set cover, capped at {k})."
        ),
    }


def recommend_full(*, agent_kind: str | None = None) -> dict[str, Any]:
    """Greedy weighted set cover until every FM is covered (no pad). MECE."""
    pool = _eligible_pool(agent_kind)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    covered: set[str] = set()
    target = set(ALL_FAILURE_MODES)

    while covered != target:
        candidates = [t for t in pool if t["id"] not in selected_ids]
        chosen, _ = _greedy_weighted_pick(
            candidates,
            target_fms=target,
            already_covered=covered,
        )
        if chosen is None:
            break  # uncoverable
        selected.append(chosen)
        selected_ids.add(str(chosen["id"]))
        covered |= set(chosen.get("addresses_failure_modes") or [])

    return {
        "mode": "full",
        "level": "full",
        "agent_kind": agent_kind,
        "tools": [_to_recommendation_dict(t) for t in selected],
        "covered_failure_modes": sorted(covered),
        "uncovered_failure_modes": sorted(target - covered),
        "coverage_complete": covered == target,
        "summary": (
            f"{len(selected)} tools cover {len(covered)} of "
            f"{len(ALL_FAILURE_MODES)} failure modes "
            f"(minimum weighted set cover)."
        ),
    }


# ---------------------------------------------------------------------------
# Public entrypoint used by the MCP tool
# ---------------------------------------------------------------------------


def recommend(
    failure_modes: list[str] | None = None,
    *,
    agent_kind: str | None = None,
    level: str | None = None,
) -> dict[str, Any]:
    """Three-tier dispatcher.

    Either ``failure_modes`` or ``level`` may be passed (not both).
      - ``failure_modes`` non-empty list → targeted mode.
      - ``level`` in ('minimum', 'optimal', 'full') → that tier.
      - both None → defaults to ``DEFAULT_LEVEL`` ('optimal').
    """
    if failure_modes and level:
        raise ValueError("pass either `failure_modes` or `level`, not both")
    if failure_modes:
        return recommend_for_failure_modes(failure_modes, agent_kind=agent_kind)
    chosen_level = (level or DEFAULT_LEVEL).strip().lower()
    if chosen_level not in LEVELS:
        raise ValueError(f"unknown level: {chosen_level!r}; valid: {list(LEVELS)}")
    if chosen_level == "minimum":
        return recommend_minimum(agent_kind=agent_kind)
    if chosen_level == "full":
        return recommend_full(agent_kind=agent_kind)
    return recommend_optimal(agent_kind=agent_kind)


__all__ = [
    "ALL_FAILURE_MODES",
    "CODING_AGENT_IDS",
    "DEFAULT_LEVEL",
    "LEVELS",
    "OPTIMAL_K",
    "RECOMMENDATION_BLOCKLIST",
    "recommend",
    "recommend_for_failure_modes",
    "recommend_full",
    "recommend_minimum",
    "recommend_optimal",
]
