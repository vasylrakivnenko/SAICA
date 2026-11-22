"""Pydantic schemas of the audit report and of the MCP lookup record.

This file is the contract between three consumers:
  - pipeline/audit/      (the analyzer and its CLI)
  - pipeline/ask/server  (``POST /assess`` returns an :class:`AuditReport`)
  - site/src/pages/assess.astro (reads the report's JSON keys directly)

Keep field names stable. New fields are added as optional with a default,
so a page built against the older shape keeps working.

Design notes:
  * Detection is conservative. Each DetectedTool carries a confidence score
    and the source paths that triggered it, so the UI can show "we detected
    semgrep because we saw .github/workflows/semgrep.yml" rather than a
    bare assertion.
  * Coverage cells use a 0–3 tier that counts what the catalog *says* about
    a tool (a tag, a rationale that mentions the mode, a citation). It is
    not a measurement of how well the tool works.
  * :class:`AuditLimits` travels with every report: which catalog tools the
    audit can detect at all, and which failure modes it therefore cannot
    assess. A mode the audit cannot assess is never reported as a gap.
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
    failure_modes_not_assessable: list[str] = Field(
        default_factory=list,
        description=(
            "Subset of failure_modes_missing: modes for which the audit has no"
            " detection rule for any catalog tool. It cannot tell whether the"
            " repository covers them, so they are not gaps."
        ),
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


class AuditLimits(BaseModel):
    """What this audit could and could not see. Part of every report."""

    catalog_tools: int = Field(description="Number of tools in the catalog")
    detectable_tools: list[str] = Field(
        description="Catalog tool ids the audit has a detection rule for"
    )
    undetectable_tools: list[str] = Field(
        description="Catalog tool ids the audit can never report as installed"
    )
    not_assessable_failure_modes: list[str] = Field(
        description="Modes with no detectable catalog tool (see CoverageGrid)"
    )
    files_listed: Optional[int] = Field(
        default=None,
        description="Remote audits: files in the repository listing",
    )
    files_read: Optional[int] = Field(
        default=None, description="Remote audits: files downloaded and read"
    )
    bytes_read: Optional[int] = Field(
        default=None, description="Remote audits: bytes downloaded"
    )
    truncated: list[str] = Field(
        default_factory=list,
        description="Plain sentences, one per cap that cut the fetch short",
    )
    notes: list[str] = Field(
        default_factory=list, description="Plain sentences on what was not read"
    )


class AuditReport(BaseModel):
    """What ``POST /assess`` and the audit CLI return."""

    repo_url: str
    audited_at: date
    stack: DetectedStack
    coverage: CoverageGrid
    gaps: list[GapItem]
    summary: str = Field(description="2–3 sentence executive summary")
    markdown: str = Field(description="Full report rendered as Markdown for download")
    limits: Optional[AuditLimits] = Field(
        default=None,
        description="What the audit can detect and what it could not assess",
    )


# ---------------------------------------------------------------------------
# MCP lookup record
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


__all__ = [
    "AuditLimits",
    "AuditReport",
    "CoverageCell",
    "CoverageGrid",
    "DetectedAgent",
    "DetectedStack",
    "DetectedTool",
    "DetectionSource",
    "GapItem",
    "Paradigm",
    "Recommendation",
    "Severity",
    "Tier",
    "ToolRecord",
]
