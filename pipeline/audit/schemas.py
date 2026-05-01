"""Shared Pydantic schemas for the audit analyzer + /assess + MCP server.

THIS FILE IS THE CONTRACT between three parallel implementations:
  - pipeline/audit/      (the analyzer)
  - pipeline/mcp/        (the MCP server, exposes saica_audit_repo)
  - site/src/pages/assess.astro (the web UI, fetches AuditReport JSON)

Edits here change what /assess renders and what the MCP tool returns. Keep
field names stable — the Astro page reads JSON keys directly.

Design notes:
  * Detection is conservative. Each DetectedTool carries a confidence score
    and the source paths that triggered it, so the UI can show "we detected
    semgrep because we saw .github/workflows/semgrep.yml" rather than a
    bare assertion.
  * Coverage cells use the same 0–3 evidence tier as the Tool×FM heatmap.
    This keeps the visual language consistent across the site.
  * Recommendations include the facets the analyzer used to pick them so a
    user can see "we recommended promptfoo because it has cli + library +
    ci_app surfaces and your stack already uses GitHub Actions."
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Stack detection
# ---------------------------------------------------------------------------

DetectionSource = Literal[
    "agent_config",  # .claude/, .cursorrules, CLAUDE.md, .windsurfrules, etc.
    "ci_workflow",  # .github/workflows/*.yml action references
    "dep_file",  # pyproject.toml / requirements*.txt / package.json etc.
    "pre_commit",  # .pre-commit-config.yaml
    "eval_config",  # promptfooconfig.yaml, deepeval.yaml, judgeval/
    "dependabot",  # .github/dependabot.yml
    "renovate",  # renovate.json or .github/renovate.json
    "other",  # anything else
]


class DetectedAgent(BaseModel):
    """Coding agent (Claude Code / Cursor / Windsurf / Replit Agent / etc.)."""

    id: str = Field(description="KG tool id, e.g. 'claude-code'")
    name: str
    detection_paths: list[str] = Field(description="Files that signaled the detection")
    confidence: float = Field(ge=0, le=1)


class DetectedTool(BaseModel):
    """One supervision tool detected in the user's repo."""

    id: str = Field(description="KG tool id, e.g. 'semgrep'. Empty if unknown.")
    name: str
    in_kg: bool = Field(
        description="True if the detected tool resolved to a SAICA-KG node."
    )
    detection_source: DetectionSource
    detection_paths: list[str]
    confidence: float = Field(ge=0, le=1)
    note: Optional[str] = None


class DetectedStack(BaseModel):
    """Inferred stack of the audited repo."""

    languages: list[str] = Field(
        description="Primary languages, e.g. ['python','typescript']"
    )
    runtime_hints: list[str] = Field(
        description="Marker files seen, e.g. ['pyproject.toml']"
    )
    ci_providers: list[str] = Field(description="e.g. ['github_actions']")
    package_managers: list[str] = Field(description="e.g. ['pip','npm']")
    agents: list[DetectedAgent] = Field(
        description="Coding agent(s) inferred from configs"
    )
    supervision_tools: list[DetectedTool] = Field(
        description="Supervision tools we found"
    )
    unresolved_tools: list[DetectedTool] = Field(
        default_factory=list,
        description="Detected but not in the KG — flagged for editorial review.",
    )


# ---------------------------------------------------------------------------
# Coverage grid
# ---------------------------------------------------------------------------

Tier = Literal[0, 1, 2, 3]
Paradigm = Literal["prevention", "detection", "correction", "recovery"]


class CoverageCell(BaseModel):
    """One (failure_mode × paradigm) cell of the user's coverage grid."""

    failure_mode: str = Field(description="e.g. 'scope_creep'")
    paradigm: Paradigm
    tier: Tier
    contributing_tools: list[str] = Field(
        description="KG tool ids in the user's stack covering this cell"
    )


class CoverageGrid(BaseModel):
    """User's current supervision coverage."""

    cells: list[CoverageCell]
    failure_modes_covered: list[str]
    failure_modes_missing: list[str]
    paradigm_balance: dict[str, int] = Field(
        description="paradigm → number of FMs the stack covers in that paradigm",
    )


# ---------------------------------------------------------------------------
# Gaps + recommendations
# ---------------------------------------------------------------------------

Severity = Literal["high", "medium", "low"]


class Recommendation(BaseModel):
    """One tool we recommend the user add, with the rationale."""

    tool_id: str = Field(description="KG tool id")
    tool_name: str
    why: str = Field(description="One-sentence rationale tied to the user's stack")
    paradigm: Paradigm
    temporal_phase: str
    autonomy_level: str
    integration_surfaces: list[str]
    addresses_failure_modes: list[str]
    stars: Optional[int] = None
    url: str = Field(description="Site URL, e.g. /tools/promptfoo")


class GapItem(BaseModel):
    """One gap in the user's supervision coverage."""

    failure_mode: str
    paradigm: Optional[Paradigm] = Field(
        default=None,
        description="If only one paradigm is missing for this FM, name it.",
    )
    severity: Severity
    rationale: str = Field(description="Why this gap matters for this stack")
    recommendations: list[Recommendation]


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------


class AuditReport(BaseModel):
    """The thing /assess and saica_audit_repo both return."""

    repo_url: str
    audited_at: date
    stack: DetectedStack
    coverage: CoverageGrid
    gaps: list[GapItem]
    summary: str = Field(description="2–3 sentence executive summary")
    markdown: str = Field(description="Full report rendered as Markdown for download")


# ---------------------------------------------------------------------------
# MCP-only schemas (saica_lookup, saica_preflight)
# ---------------------------------------------------------------------------


class ToolRecord(BaseModel):
    """Return type for saica_lookup."""

    id: str
    name: str
    tagline: Optional[str]
    description: str
    control_paradigm: str
    temporal_phase: str
    autonomy_level: str
    addresses_failure_modes: list[str]
    integration_surfaces: list[str]
    locus_of_control: list[str] = Field(default_factory=list)
    composes_with: list[str] = Field(default_factory=list)
    feeds_into: list[str] = Field(default_factory=list)
    stars: Optional[int] = None
    maturity_status: Optional[str] = None
    url: str = Field(description="Site URL, e.g. /tools/promptfoo")


class PreflightInput(BaseModel):
    """Input for saica_preflight."""

    action: str = Field(
        description="What the agent is about to do, e.g. 'edit src/auth.py'"
    )
    context: Optional[str] = Field(
        default=None,
        description="Optional surrounding context: file paths, prior diff, task description.",
    )
    agent_kind: Optional[str] = Field(
        default=None,
        description="Hint about which agent is asking, e.g. 'claude-code'. May change recommendations.",
    )


class PreflightResult(BaseModel):
    """Return type for saica_preflight."""

    risk_failure_modes: list[str] = Field(
        description="FM ids the action plausibly triggers"
    )
    overall_risk: Severity
    recommended_supervisors: list[Recommendation]
    rationale: str


__all__ = [
    "AuditReport",
    "CoverageCell",
    "CoverageGrid",
    "DetectedAgent",
    "DetectedStack",
    "DetectedTool",
    "DetectionSource",
    "GapItem",
    "Paradigm",
    "PreflightInput",
    "PreflightResult",
    "Recommendation",
    "Severity",
    "Tier",
    "ToolRecord",
]
