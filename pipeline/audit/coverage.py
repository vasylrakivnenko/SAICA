"""Coverage grid + gap analysis.

The coverage grid is one tier-0..3 cell per (failure_mode, paradigm).
The tier counts what the catalog says about the contributing tool, not how
well the tool works:

    1 — at least one detected tool is tagged for this mode **and** has this paradigm
    2 — + that tool's inclusion_rationale discusses the mode
    3 — + that tool has any cited_in/documented_in/evaluated_on

Gap analysis then walks the grid. It reports a gap only where the audit
could have seen coverage and the catalog has something to offer:

* A mode for which the audit has no detection rule for any catalog tool is
  **not assessable**. It is listed as such and is never a gap: the audit
  cannot tell whether the repository covers it.
* A mode that no detected tool covers is a ``high`` gap.
* A mode covered in one paradigm is a ``medium`` gap only if the catalog
  holds a tool of the complementary paradigm for that mode. If it holds
  none, there is nothing to add and no gap is raised.

Suggestions come from the catalog, never from measurements: tools tagged
for the mode, of the wanted paradigm when one is named, and not written
for a language the repository does not use.
"""

from __future__ import annotations

from typing import Iterable, get_args

from pipeline.audit.detectors import detectable_tool_ids
from pipeline.audit.kg import (
    cell_tier,
    load_failure_modes,
    load_tool_index,
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
from pipeline.mcp.recommender import CODING_AGENT_IDS, RECOMMENDATION_BLOCKLIST

PARADIGMS: tuple[Paradigm, ...] = get_args(Paradigm)  # ("prevention", "detection", ...)

# If you have detection, the useful addition is prevention, and the other
# way round; for correction / recovery it is detection.
COMPLEMENT: dict[str, Paradigm] = {
    "prevention": "detection",
    "detection": "prevention",
    "correction": "detection",
    "recovery": "detection",
}

# Values of a tool's ``supervises_targets`` that name a programming
# language (the others name package ecosystems and are not used here).
LANGUAGE_NAMES: frozenset[str] = frozenset(
    {
        "python",
        "javascript",
        "typescript",
        "go",
        "rust",
        "java",
        "ruby",
        "php",
        "csharp",
        "c",
        "cpp",
    }
)


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


def tagged_tools(fm: str, kg_index: dict[str, dict]) -> list[dict]:
    """Catalog tools tagged for ``fm``, in id order."""
    return [
        tool
        for _, tool in sorted(kg_index.items())
        if fm in (tool.get("addresses_failure_modes") or [])
    ]


def not_assessable_modes(kg_index: dict[str, dict], fm_ids: list[str]) -> list[str]:
    """Modes for which no catalog tool is detectable by the audit."""
    detectable = detectable_tool_ids(kg_index)
    return [
        fm
        for fm in fm_ids
        if not any(tool["id"] in detectable for tool in tagged_tools(fm, kg_index))
    ]


def build_coverage_grid(
    detected_tools: list[DetectedTool],
    kg_index: dict[str, dict] | None = None,
) -> CoverageGrid:
    """Build the (FM × paradigm) coverage grid for the user's detected stack."""
    kg = kg_index if kg_index is not None else load_tool_index()
    fm_ids = load_failure_modes()
    detected_ids = _detected_kg_ids(detected_tools)

    cells: list[CoverageCell] = []
    fms_covered: set[str] = set()
    paradigm_fms: dict[str, set[str]] = {p: set() for p in PARADIGMS}

    for fm in fm_ids:
        for paradigm in PARADIGMS:
            tier = 0
            contributing: list[str] = []
            for tid in detected_ids:
                tool = kg.get(tid)
                if not tool or tool.get("control_paradigm") != paradigm:
                    continue
                t = cell_tier(tool, fm)
                if t > 0:
                    contributing.append(tid)
                    tier = max(tier, t)
            cells.append(
                CoverageCell(
                    failure_mode=fm,
                    paradigm=paradigm,
                    tier=tier,  # type: ignore[arg-type]
                    contributing_tools=contributing,
                )
            )
            if tier > 0:
                fms_covered.add(fm)
                paradigm_fms[paradigm].add(fm)

    fms_missing = [fm for fm in fm_ids if fm not in fms_covered]
    blind = set(not_assessable_modes(kg, fm_ids))
    return CoverageGrid(
        cells=cells,
        failure_modes_covered=sorted(fms_covered),
        failure_modes_missing=fms_missing,
        paradigm_balance={p: len(fms) for p, fms in paradigm_fms.items()},
        failure_modes_not_assessable=[fm for fm in fms_missing if fm in blind],
    )


# ---------------------------------------------------------------------------
# Gap analysis + recommendations
# ---------------------------------------------------------------------------


def _stack_surfaces(stack: DetectedStack) -> set[str]:
    """Inferred surfaces the user's stack can integrate with."""
    surfaces: set[str] = set()
    if "github_actions" in stack.ci_providers:
        surfaces.add("ci_app")
    if any(
        p in stack.ci_providers
        for p in ("gitlab_ci", "circle_ci", "azure_pipelines", "jenkins")
    ):
        surfaces.add("ci_app")
    if "python" in stack.languages:
        surfaces.update({"library", "cli"})
    if "javascript" in stack.languages or "typescript" in stack.languages:
        surfaces.update({"library", "cli"})
    if any(
        a.id
        in {
            "claude-code",
            "cursor",
            "windsurf",
            "continue-dev",
            "github-copilot",
            "sourcegraph-cody",
            "aider",
        }
        for a in stack.agents
    ):
        # MCP-using agents (Claude Code first) can host mcp_server tools.
        surfaces.add("mcp_server")
    # Always plausible.
    surfaces.add("cli")
    return surfaces


def _surface_fit_score(tool: dict, stack_surfaces: set[str]) -> int:
    surfaces = set(tool.get("integration_surfaces") or [])
    return len(surfaces & stack_surfaces)


def fits_languages(tool: dict, languages: list[str]) -> bool:
    """False only when the tool is written for other languages.

    A tool with no language among its ``supervises_targets`` fits any
    repository; so does any tool when no language was detected.
    """
    targets = {
        str(t).lower() for t in (tool.get("supervises_targets") or [])
    } & LANGUAGE_NAMES
    if not targets or not languages:
        return True
    return bool(targets & set(languages))


def recommend_for_gap(
    fm: str,
    stack: DetectedStack,
    kg_index: dict[str, dict] | None = None,
    top_n: int = 3,
    *,
    detected_ids: set[str] | None = None,
    paradigm: Paradigm | None = None,
) -> list[Recommendation]:
    """Up to ``top_n`` catalog tools tagged for ``fm`` that are not installed.

    With ``paradigm``, only tools of that paradigm. Tools written for a
    language the repository does not use are left out. Order: surface fit
    with the stack, then catalog tier, then stars.
    """
    kg = kg_index if kg_index is not None else load_tool_index()
    detected_ids = detected_ids or set()
    stack_surfaces = _stack_surfaces(stack)

    detected_agent_ids = {d.id for d in stack.agents if d.id}
    asker_is_coding_agent = bool(detected_agent_ids & CODING_AGENT_IDS)
    candidates: list[dict] = []
    for tool in tagged_tools(fm, kg):
        tid = tool["id"]
        if tid in detected_ids or tid in RECOMMENDATION_BLOCKLIST:
            continue
        # Don't recommend a peer coding agent to a user who already has one.
        if asker_is_coding_agent and tid in CODING_AGENT_IDS:
            continue
        if paradigm is not None and tool.get("control_paradigm") != paradigm:
            continue
        if not fits_languages(tool, stack.languages):
            continue
        candidates.append(tool)

    def sort_key(tool: dict) -> tuple:
        return (
            _surface_fit_score(tool, stack_surfaces),
            cell_tier(tool, fm),
            float(tool.get("stars") or 0),
        )

    recs: list[Recommendation] = []
    for tool in sorted(candidates, key=sort_key, reverse=True)[:top_n]:
        tid = str(tool["id"])
        surfaces = list(tool.get("integration_surfaces") or [])
        recs.append(
            Recommendation(
                tool_id=tid,
                tool_name=str(tool.get("name") or tid),
                why=_explain_recommendation(tool, fm, stack_surfaces, surfaces),
                paradigm=tool["control_paradigm"],
                temporal_phase=str(tool["temporal_phase"]),
                autonomy_level=str(tool["autonomy_level"]),
                integration_surfaces=surfaces,
                addresses_failure_modes=list(tool.get("addresses_failure_modes") or []),
                stars=int(tool["stars"]) if tool.get("stars") is not None else None,
                url=tool_url(tid),
            )
        )
    return recs


def _explain_recommendation(
    tool: dict,
    fm: str,
    stack_surfaces: set[str],
    tool_surfaces: list[str],
) -> str:
    overlap = sorted(set(tool_surfaces) & stack_surfaces)
    if overlap:
        surface_phrase = f"integrates via {', '.join(overlap)} (matches your stack)"
    elif tool_surfaces:
        surface_phrase = f"integrates via {', '.join(tool_surfaces[:2])}"
    else:
        surface_phrase = "integration surface not recorded"
    return (
        f"Tagged in the catalog as {tool['control_paradigm']} for "
        f"{fm.replace('_', ' ')}; {surface_phrase}."
    )


def find_gaps(
    coverage: CoverageGrid,
    stack: DetectedStack,
    kg_index: dict[str, dict] | None = None,
) -> list[GapItem]:
    """Gaps the audit can stand behind, each with catalog suggestions."""
    kg = kg_index if kg_index is not None else load_tool_index()
    fm_ids = load_failure_modes()
    detected_ids = {d.id for d in stack.supervision_tools if d.in_kg and d.id}
    detectable = detectable_tool_ids(kg)
    blind = set(coverage.failure_modes_not_assessable)

    by_fm: dict[str, dict[str, CoverageCell]] = {}
    for cell in coverage.cells:
        by_fm.setdefault(cell.failure_mode, {})[cell.paradigm] = cell

    gaps: list[GapItem] = []
    for fm in fm_ids:
        if fm in blind:
            continue
        label = fm.replace("_", " ")
        covered_paradigms = [p for p, c in by_fm.get(fm, {}).items() if c.tier > 0]
        severity: Severity
        missing_paradigm: Paradigm | None

        if not covered_paradigms:
            tagged = tagged_tools(fm, kg)
            seen = sum(1 for t in tagged if t["id"] in detectable)
            unseen = len(tagged) - seen
            severity, missing_paradigm = "high", None
            rationale = (
                f"None of the {seen} catalog tool{'s' if seen != 1 else ''} that this "
                f"audit can detect for {label} was found."
            )
            if unseen:
                rationale += (
                    f" The catalog lists {unseen} more for this mode that the audit "
                    "cannot detect; if you use one of them, this is not a gap."
                )
        elif len(covered_paradigms) == 1:
            present = covered_paradigms[0]
            missing_paradigm = COMPLEMENT.get(present, "detection")
            on_offer = [
                t
                for t in tagged_tools(fm, kg)
                if t.get("control_paradigm") == missing_paradigm
            ]
            if not on_offer:
                continue  # the catalog has no tool of that paradigm to add
            severity = "medium"
            rationale = (
                f"The detected tools cover {label} in one way only ({present}). "
                f"The catalog lists {len(on_offer)} {missing_paradigm} "
                f"tool{'s' if len(on_offer) != 1 else ''} for this mode."
            )
        else:
            continue

        recs = recommend_for_gap(
            fm,
            stack,
            kg,
            top_n=3,
            detected_ids=detected_ids,
            paradigm=missing_paradigm,
        )
        if missing_paradigm is not None and not recs:
            continue  # nothing of that paradigm fits this repository
        gaps.append(
            GapItem(
                failure_mode=fm,
                paradigm=missing_paradigm,
                severity=severity,
                rationale=rationale,
                recommendations=recs,
            )
        )

    # Sort: high-severity first, then alphabetical FM for stable output.
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: (severity_rank.get(g.severity, 3), g.failure_mode))
    return gaps


__all__ = [
    "COMPLEMENT",
    "PARADIGMS",
    "build_coverage_grid",
    "find_gaps",
    "fits_languages",
    "not_assessable_modes",
    "recommend_for_gap",
    "tagged_tools",
]
