"""Recommendation engine for the SAICA-KG MCP server.

Two modes, per the v0.2.1 design:

* **Targeted** — caller passes a list of failure modes; we return supervisors
  that declare coverage for those failure modes.
* **Full suite** (default) — caller passes no failure modes; we return the
  minimum set of supervisors that *together* cover all 11 failure modes.
  Greedy set cover, then a small depth pad of the highest-evidence
  remaining supervisors.

Two filter layers gate every recommendation:

1. **CODING_AGENT_IDS.** The whole point of MCP-served recommendations is
   *supervision for the asking agent*. Suggesting Replit Agent to a Cursor
   user — or vice-versa — is a category error. When ``agent_kind`` is set
   to one of the known coding-agent ids, we filter every coding-agent peer
   out of the recommendation pool. The asking agent itself is also
   filtered (so Cursor never recommends Cursor).

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

from pipeline.shared.trending import effective_stars, is_trending

# Resolve REPO at import time so subprocess invocations from any CWD work.
REPO = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO / "data" / "tools"

# ---------------------------------------------------------------------------
# Filter layers
# ---------------------------------------------------------------------------

# Tools that ARE coding agents — never recommended *to* another coding agent.
# Stays narrow on purpose. Adding a tool here means "users of any other coding
# agent should not be told to additionally install this one." Frameworks /
# libraries / MCP servers / browser-RPA tools are NOT in this list — they
# compose alongside whatever coding agent the caller is using.
CODING_AGENT_IDS: frozenset[str] = frozenset({
    # IDE / desktop coding agents
    "cursor", "windsurf", "zed-agent",
    # Hosted coding agents
    "replit-agent", "v0", "devin",
    # IDE-extension coding agents
    "github-copilot", "continue-dev", "sourcegraph-cody",
    # CLI coding agents
    "claude-code", "aider", "openhands", "swe-agent",
    "codex-cli", "gemini-cli", "cline",
})

# Tools we never recommend, regardless of asker. Reserved for genuinely
# ambiguous cases — e.g. an image-generation GUI whose declared FM coverage
# doesn't translate to "stop bugs in coding agents." Keep this list as
# small as possible; prefer fixing the YAML facets to better reflect role
# over silently blocking.
RECOMMENDATION_BLOCKLIST: frozenset[str] = frozenset({
    "comfyui",  # diffusion-model GUI; declared scope_creep coverage is for image workflows, not code.
})

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
            t for t in tools.values()
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
# Mode 2: full-suite recommendation (greedy set cover over all 11 FMs)
# ---------------------------------------------------------------------------

def recommend_full_suite(
    *,
    agent_kind: str | None = None,
    pad_to: int = 11,
) -> dict[str, Any]:
    """Return a minimum-set of supervisors covering all 11 failure modes.

    Greedy set cover: at each step pick the eligible tool that covers the
    most still-uncovered FMs, tiebreak by stars then by breadth. Stops when
    every FM is covered. If the cover uses fewer than ``pad_to`` tools,
    pad with the highest-stars remaining eligible tools so the caller gets
    a recognizable "deep bench" rather than just the bare cover.

    Returns a payload with ``cover`` (the specialists), ``pad`` (the depth
    additions), and ``coverage_complete`` (True when all 11 FMs are covered).
    """
    tools = _load_tools()
    eligible_pool = [
        t for t in tools.values()
        if _eligible(t, agent_kind=agent_kind)
        and (t.get("addresses_failure_modes") or [])
    ]

    remaining: set[str] = set(ALL_FAILURE_MODES)
    cover_ids: list[str] = []
    cover_set: set[str] = set()

    while remaining:
        best_id: str | None = None
        best_key: tuple[int, float, int] | None = None
        for t in eligible_pool:
            tid = str(t["id"])
            if tid in cover_set:
                continue
            t_fms = set(t.get("addresses_failure_modes") or [])
            new = len(t_fms & remaining)
            if new == 0:
                continue
            breadth = len(t_fms)
            # tiebreak: most-new FMs > effective_stars (trending-boosted) > breadth
            key = (new, effective_stars(t), breadth)
            if best_key is None or key > best_key:
                best_id = tid
                best_key = key
        if best_id is None:
            # No eligible tool covers any remaining FM — coverage incomplete.
            break
        cover_ids.append(best_id)
        cover_set.add(best_id)
        chosen = next(t for t in eligible_pool if t["id"] == best_id)
        remaining -= set(chosen.get("addresses_failure_modes") or [])

    # Pad to pad_to with the highest-effective-stars remaining eligible tools.
    pad_ids: list[str] = []
    if len(cover_ids) < pad_to:
        leftover = [
            t for t in eligible_pool
            if t["id"] not in cover_set
        ]
        leftover.sort(
            key=lambda t: (
                effective_stars(t),
                len(t.get("addresses_failure_modes") or []),
            ),
            reverse=True,
        )
        for t in leftover:
            if len(cover_ids) + len(pad_ids) >= pad_to:
                break
            pad_ids.append(str(t["id"]))

    return {
        "mode": "full_suite",
        "agent_kind": agent_kind,
        "coverage_complete": not remaining,
        "uncovered_failure_modes": sorted(remaining),
        "cover": [_to_recommendation_dict(tools[tid]) for tid in cover_ids],
        "pad": [_to_recommendation_dict(tools[tid]) for tid in pad_ids],
        "summary": (
            f"{len(cover_ids)} specialist tools cover "
            f"{len(ALL_FAILURE_MODES) - len(remaining)} of "
            f"{len(ALL_FAILURE_MODES)} failure modes; "
            f"{len(pad_ids)} additional tools included for depth."
        ),
    }


# ---------------------------------------------------------------------------
# Public entrypoint used by the MCP tool
# ---------------------------------------------------------------------------

def recommend(
    failure_modes: list[str] | None,
    *,
    agent_kind: str | None,
) -> dict[str, Any]:
    """Two-mode dispatcher.

    * ``failure_modes=None`` or empty list → full suite.
    * Non-empty list → targeted mode for those FMs.
    """
    if failure_modes:
        return recommend_for_failure_modes(failure_modes, agent_kind=agent_kind)
    return recommend_full_suite(agent_kind=agent_kind)


__all__ = [
    "ALL_FAILURE_MODES",
    "CODING_AGENT_IDS",
    "RECOMMENDATION_BLOCKLIST",
    "recommend",
    "recommend_for_failure_modes",
    "recommend_full_suite",
]
