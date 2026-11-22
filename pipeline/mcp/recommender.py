"""Catalog recommender behind the MCP tool ``saica_recommend`` and the
generated ``RECOMMENDATIONS.md`` / ``SKILLS.md``.

What it is: a ranking of catalog tools by their tags. A tag
(``addresses_failure_modes``) is what a tool says it deals with. The
ranking multiplies an editorial weight per failure mode by the tool's
popularity (:mod:`pipeline.shared.priorities`). It is not a benchmark.

The one place measurements enter: a tool is never offered for a failure
mode on which SAICA-Bench measured it below the site's floor, and an
archived tool is offered for nothing
(:func:`pipeline.maturity.evidence.measured_view`, applied to every tool
the selection sees). Measured picks are on https://saica.ai/tool-coverage/.

Two modes:

* **Targeted** — the caller names failure modes; up to three tagged tools
  come back per mode.
* **Tiers** — ``minimum`` (one tool), ``optimal`` (three), ``full`` (greedy
  pick until no tagged tool adds a mode). After the measured floor some
  modes may have no tool left; ``full`` then reports them as uncovered.

Two filters are kept from the earlier catalog and match nothing in it
today: ``CODING_AGENT_IDS`` (never offer a coding agent to a coding agent)
and ``RECOMMENDATION_BLOCKLIST``.
"""

from __future__ import annotations

from typing import Any

from pipeline import kg
from pipeline.maturity.evidence import measured_view
from pipeline.shared.priorities import coverage_value, popularity

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


def all_failure_modes() -> tuple[str, ...]:
    """The failure-mode ids, from ``data/failure_modes/`` (never typed in)."""
    return kg.failure_mode_ids()


def __getattr__(name: str) -> Any:
    # ``ALL_FAILURE_MODES`` used to be a typed-in tuple. Old imports keep
    # working and now get the list derived from the data.
    if name == "ALL_FAILURE_MODES":
        return all_failure_modes()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# KG access
# ---------------------------------------------------------------------------

_TOOL_INDEX_CACHE: dict[str, dict[str, Any]] | None = None


def _load_tools() -> dict[str, dict[str, Any]]:
    """Every catalog tool with its tags untouched, keyed and sorted by id.

    Read through :mod:`pipeline.kg` (validated, one error policy) and cached
    for the process. The generators read this for the "tagged, not listed"
    table, so the tags here are the catalog's, not the measured view.
    """
    global _TOOL_INDEX_CACHE
    if _TOOL_INDEX_CACHE is None:
        _TOOL_INDEX_CACHE = kg.load_tools()
    return _TOOL_INDEX_CACHE


def _reset_index() -> None:
    global _TOOL_INDEX_CACHE
    _TOOL_INDEX_CACHE = None


kg.on_reset(_reset_index)


def _recommendable_tools() -> list[dict[str, Any]]:
    """The tools as the selection may use them, in id order.

    Each tool's ``addresses_failure_modes`` keeps only the modes it may be
    offered for: its tags minus the modes where SAICA-Bench measured it
    below the floor; none when its repository is archived.
    """
    return [measured_view(tool) for _, tool in sorted(_load_tools().items())]


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
    """Sort key of a tool for one failure mode. Higher is better.

    ``(paradigm_pref, mentioned, stars)``: 1 for prevention / detection, 0
    for correction / recovery; 1 when the tool's ``inclusion_rationale``
    names the mode; then the star count.
    """
    paradigm = str(tool.get("control_paradigm") or "")
    paradigm_pref = 1 if paradigm in ("prevention", "detection") else 0
    rationale = str(tool.get("inclusion_rationale") or "").lower()
    fm_keywords = (fm, fm.replace("_", " "), fm.replace("_", "-"))
    mentioned = 1 if any(k in rationale for k in fm_keywords) else 0
    return (paradigm_pref, mentioned, float(tool.get("stars") or 0))


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
    known = all_failure_modes()
    unknown = [fm for fm in failure_modes if fm not in known]
    if unknown:
        raise ValueError(f"unknown failure_mode(s): {unknown}. Valid: {list(known)}")

    tools = _recommendable_tools()
    by_fm: dict[str, list[dict[str, Any]]] = {}
    for fm in failure_modes:
        candidates = [
            t
            for t in tools
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
# Tiers
#
# All three pick greedily: the next tool is the one with the highest
#   Σ priority(mode) over the modes it would newly name  ×  (1 + popularity).
#
#   minimum: the first pick only.
#   optimal: the first three picks.
#   full:    picks until no tagged tool adds a mode.
# ---------------------------------------------------------------------------

LEVELS: tuple[str, ...] = ("minimum", "optimal", "full")
DEFAULT_LEVEL: str = "optimal"
OPTIMAL_K: int = 3


def _eligible_pool(agent_kind: str | None) -> list[dict[str, Any]]:
    """Tools that may be offered to this asker and are left with a mode."""
    return [
        t
        for t in _recommendable_tools()
        if _eligible(t, agent_kind=agent_kind)
        and (t.get("addresses_failure_modes") or [])
    ]


def _greedy_weighted_pick(
    pool: list[dict[str, Any]],
    *,
    target_fms: set[str],
    already_covered: set[str],
) -> tuple[dict[str, Any] | None, float]:
    """The tool with the highest ``coverage_value × (1 + popularity)`` over
    the modes of ``target_fms`` not yet in ``already_covered``.

    The pool is in id order and a later tool must score strictly higher to
    win, so a tie goes to the lower id whatever the file system's order.
    """
    remaining = target_fms - already_covered
    best: dict[str, Any] | None = None
    best_score: float = float("-inf")
    for t in pool:
        new_value = coverage_value(t, remaining)
        if new_value <= 0:
            continue
        score = new_value * (1.0 + popularity(t))
        if score > best_score:
            best, best_score = t, score
    return best, best_score


def _summary(selected: list[dict[str, Any]], covered: set[str], total: int) -> str:
    """One sentence that counts tags as tags."""
    if not selected:
        return "No eligible tool found."
    n = len(selected)
    whose = "its tags name" if n == 1 else "their tags name"
    return (
        f"{n} tool{'' if n == 1 else 's'}; {whose} {len(covered)} of {total} "
        "failure modes (a tag is the tool's claim, not a measurement)."
    )


def _pick(
    agent_kind: str | None, limit: int | None
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    """Greedy picks, at most ``limit`` (no limit: until nothing adds a mode)."""
    pool = _eligible_pool(agent_kind)
    target = set(all_failure_modes())
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    covered: set[str] = set()
    while covered != target and (limit is None or len(selected) < limit):
        candidates = [t for t in pool if t["id"] not in selected_ids]
        chosen, _ = _greedy_weighted_pick(
            candidates, target_fms=target, already_covered=covered
        )
        if chosen is None:
            break  # no tagged tool adds a mode
        selected.append(chosen)
        selected_ids.add(str(chosen["id"]))
        covered |= set(chosen.get("addresses_failure_modes") or []) & target
    return selected, covered, target


def _tier(level: str, agent_kind: str | None, limit: int | None) -> dict[str, Any]:
    selected, covered, target = _pick(agent_kind, limit)
    return {
        "mode": level,
        "level": level,
        "agent_kind": agent_kind,
        "tools": [_to_recommendation_dict(t) for t in selected],
        "covered_failure_modes": sorted(covered),
        "uncovered_failure_modes": sorted(target - covered),
        "coverage_complete": covered == target,
        "summary": _summary(selected, covered, len(target)),
    }


def recommend_minimum(*, agent_kind: str | None = None) -> dict[str, Any]:
    """The single first pick."""
    return _tier("minimum", agent_kind, 1)


def recommend_optimal(
    *,
    agent_kind: str | None = None,
    k: int = OPTIMAL_K,
) -> dict[str, Any]:
    """The first ``k`` picks (three by default)."""
    out = _tier("optimal", agent_kind, k)
    out["k"] = k
    return out


def recommend_full(*, agent_kind: str | None = None) -> dict[str, Any]:
    """Picks until no tagged tool adds a mode.

    ``coverage_complete`` is false when a mode has no tool left after the
    measured floor; that mode is then listed in ``uncovered_failure_modes``.
    """
    return _tier("full", agent_kind, None)


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
    "ALL_FAILURE_MODES",  # noqa: F822 - served by __getattr__
    "all_failure_modes",
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
