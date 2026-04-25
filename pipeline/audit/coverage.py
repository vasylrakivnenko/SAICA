"""Coverage grid + gap analysis.

The coverage grid is one tier-0..3 cell per (failure_mode, paradigm).
Tier rule (per the heatmap in research/plot_tool_fm_heatmap.py):

    1 — at least one detected tool declares this FM **and** has this paradigm
    2 — + the contributing tool's inclusion_rationale discusses the FM
    3 — + the contributing tool has any cited_in/documented_in/evaluated_on

Gap analysis then walks the grid and flags FMs the user's stack doesn't
cover at all (severity ``high``) or covers in only one paradigm
(severity ``medium``).  For each gap we surface 2-3 ranked
recommendations from the KG, prioritising tools whose integration
surfaces match what the user's stack already has.
"""
from __future__ import annotations

from typing import Iterable, get_args

from pipeline.audit.kg import (
    cell_tier,
    load_failure_modes,
    load_tool_index,
    tools_by_failure_mode,
    tool_url,
)
from pipeline.audit.schemas import (
    CoverageCell,
    CoverageGrid,
    DetectedStack,
    DetectedTool,
    GapItem,
    Paradigm,
    Recommendation,
    Severity,
)

PARADIGMS: tuple[Paradigm, ...] = get_args(Paradigm)  # ("prevention", "detection", ...)


# ---------------------------------------------------------------------------
# Coverage grid
# ---------------------------------------------------------------------------

def _detected_kg_ids(detected_tools: Iterable[DetectedTool]) -> list[str]:
    """De-duplicated ordered list of KG-resolved tool ids from the detection list."""
    seen: set[str] = set()
    out: list[str] = []
    for d in detected_tools:
        if d.in_kg and d.id and d.id not in seen:
            seen.add(d.id)
            out.append(d.id)
    return out


def build_coverage_grid(
    detected_tools: list[DetectedTool],
    kg_index: dict[str, dict] | None = None,
) -> CoverageGrid:
    """Build the (FM × paradigm) coverage grid for the user's detected stack."""
    kg = kg_index or load_tool_index()
    fm_ids = load_failure_modes()
    detected_ids = _detected_kg_ids(detected_tools)

    cells: list[CoverageCell] = []
    fms_covered: set[str] = set()
    paradigm_balance: dict[str, int] = {p: 0 for p in PARADIGMS}
    paradigm_fms: dict[str, set[str]] = {p: set() for p in PARADIGMS}

    for fm in fm_ids:
        for paradigm in PARADIGMS:
            tier = 0
            contributing: list[str] = []
            for tid in detected_ids:
                tool = kg.get(tid)
                if not tool:
                    continue
                if (tool.get("control_paradigm") or "") != paradigm:
                    continue
                t = cell_tier(tool, fm)
                if t > 0:
                    contributing.append(tid)
                    if t > tier:
                        tier = t
            cells.append(CoverageCell(
                failure_mode=fm,
                paradigm=paradigm,  # type: ignore[arg-type]
                tier=tier,  # type: ignore[arg-type]
                contributing_tools=contributing,
            ))
            if tier > 0:
                fms_covered.add(fm)
                paradigm_fms[paradigm].add(fm)

    for p, fms in paradigm_fms.items():
        paradigm_balance[p] = len(fms)

    fms_missing = [fm for fm in fm_ids if fm not in fms_covered]
    return CoverageGrid(
        cells=cells,
        failure_modes_covered=sorted(fms_covered),
        failure_modes_missing=fms_missing,
        paradigm_balance=paradigm_balance,
    )


# ---------------------------------------------------------------------------
# Gap analysis + recommendations
# ---------------------------------------------------------------------------

def _stack_surfaces(stack: DetectedStack) -> set[str]:
    """Inferred surfaces the user's stack can integrate with."""
    surfaces: set[str] = set()
    if "github_actions" in stack.ci_providers:
        surfaces.add("ci_app")
    if any(p in stack.ci_providers for p in ("gitlab_ci", "circle_ci", "azure_pipelines", "jenkins")):
        surfaces.add("ci_app")
    if "python" in stack.languages:
        surfaces.update({"library", "cli"})
    if "javascript" in stack.languages or "typescript" in stack.languages:
        surfaces.update({"library", "cli"})
    if any(a.id in {"claude-code", "cursor", "windsurf", "continue-dev",
                    "github-copilot", "sourcegraph-cody", "aider"}
           for a in stack.agents):
        # MCP-using agents (Claude Code first) can host mcp_server tools.
        surfaces.add("mcp_server")
    # Always plausible.
    surfaces.add("cli")
    return surfaces


def _surface_fit_score(tool: dict, stack_surfaces: set[str]) -> int:
    surfaces = set(tool.get("integration_surfaces") or [])
    return len(surfaces & stack_surfaces)


def recommend_for_gap(
    fm: str,
    stack: DetectedStack,
    kg_index: dict[str, dict] | None = None,
    top_n: int = 3,
    *,
    detected_ids: set[str] | None = None,
    preferred_paradigm: Paradigm | None = None,
) -> list[Recommendation]:
    """Return up to ``top_n`` ranked recommendations for a given gap FM."""
    kg = kg_index or load_tool_index()
    detected_ids = detected_ids or set()
    stack_surfaces = _stack_surfaces(stack)

    # Candidate pool: all KG tools that declare coverage for this FM.
    candidates: list[dict] = []
    for tool in tools_by_failure_mode(fm):
        tid = tool.get("id")
        if not tid or tid in detected_ids:
            continue
        # Skip tools that are themselves coding agents (recovery + fully_autonomous)
        # because they self-recover rather than supervise.
        if (tool.get("control_paradigm") == "recovery"
                and tool.get("autonomy_level") == "fully_autonomous"):
            continue
        candidates.append(tool)

    if not candidates:
        return []

    def sort_key(tool: dict) -> tuple:
        paradigm_bonus = 1 if (preferred_paradigm and tool.get("control_paradigm") == preferred_paradigm) else 0
        surface_fit = _surface_fit_score(tool, stack_surfaces)
        per_fm_tier = cell_tier(tool, fm)
        stars = int(tool.get("stars") or 0)
        # Larger tuples sort first when reversed; we want max on each.
        return (paradigm_bonus, surface_fit, per_fm_tier, stars)

    ranked = sorted(candidates, key=sort_key, reverse=True)[:top_n]

    recs: list[Recommendation] = []
    for tool in ranked:
        tid = str(tool.get("id"))
        surfaces = list(tool.get("integration_surfaces") or [])
        why = _explain_recommendation(tool, fm, stack_surfaces, surfaces)
        recs.append(Recommendation(
            tool_id=tid,
            tool_name=str(tool.get("name") or tid),
            why=why,
            paradigm=str(tool.get("control_paradigm") or "detection"),  # type: ignore[arg-type]
            temporal_phase=str(tool.get("temporal_phase") or "post_generation"),
            autonomy_level=str(tool.get("autonomy_level") or "fully_autonomous"),
            integration_surfaces=surfaces,
            addresses_failure_modes=list(tool.get("addresses_failure_modes") or []),
            stars=int(tool["stars"]) if tool.get("stars") else None,
            url=tool_url(tid),
        ))
    return recs


def _explain_recommendation(
    tool: dict,
    fm: str,
    stack_surfaces: set[str],
    tool_surfaces: list[str],
) -> str:
    overlap = sorted(set(tool_surfaces) & stack_surfaces)
    paradigm = tool.get("control_paradigm") or "detection"
    if overlap:
        surface_phrase = f"integrates via {', '.join(overlap)} (matches your stack)"
    elif tool_surfaces:
        surface_phrase = f"integrates via {', '.join(tool_surfaces[:2])}"
    else:
        surface_phrase = "general-purpose integration"
    return (
        f"Adds {paradigm} coverage for {fm.replace('_', ' ')}; "
        f"{surface_phrase}."
    )


def find_gaps(
    coverage: CoverageGrid,
    stack: DetectedStack,
    kg_index: dict[str, dict] | None = None,
) -> list[GapItem]:
    """Identify FM-level gaps in the user's coverage and attach recommendations."""
    kg = kg_index or load_tool_index()
    fm_ids = load_failure_modes()
    detected_ids = {d.id for d in stack.supervision_tools if d.in_kg and d.id}

    # Index cells by FM for fast lookup.
    by_fm: dict[str, dict[str, CoverageCell]] = {}
    for cell in coverage.cells:
        by_fm.setdefault(cell.failure_mode, {})[cell.paradigm] = cell

    gaps: list[GapItem] = []
    for fm in fm_ids:
        cells = by_fm.get(fm, {})
        covered_paradigms = [p for p, c in cells.items() if c.tier > 0]

        if not covered_paradigms:
            severity: Severity = "high"
            missing_paradigm = None
            rationale = (
                f"No detected tool declares coverage for {fm.replace('_', ' ')}."
            )
            preferred_paradigm = None
        elif len(covered_paradigms) == 1:
            # Only one paradigm; flag the most useful complementary one as missing.
            present = covered_paradigms[0]
            # Heuristic: if you have detection, recommend prevention; if prevention, recommend detection.
            complement_map = {
                "prevention": "detection",
                "detection": "prevention",
                "correction": "detection",
                "recovery": "detection",
            }
            missing_paradigm = complement_map.get(present, "detection")
            severity = "medium"
            rationale = (
                f"Coverage for {fm.replace('_', ' ')} is single-paradigm "
                f"({present} only); add {missing_paradigm} for defence in depth."
            )
            preferred_paradigm = missing_paradigm  # type: ignore[assignment]
        else:
            continue

        recs = recommend_for_gap(
            fm, stack, kg, top_n=3,
            detected_ids=detected_ids,
            preferred_paradigm=preferred_paradigm,  # type: ignore[arg-type]
        )
        gaps.append(GapItem(
            failure_mode=fm,
            paradigm=missing_paradigm,  # type: ignore[arg-type]
            severity=severity,
            rationale=rationale,
            recommendations=recs,
        ))

    # Sort: high-severity first, then alphabetical FM for stable output.
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: (severity_rank.get(g.severity, 3), g.failure_mode))
    return gaps


__all__ = [
    "PARADIGMS",
    "build_coverage_grid",
    "find_gaps",
    "recommend_for_gap",
]
