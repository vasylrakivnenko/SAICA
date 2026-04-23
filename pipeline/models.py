"""Canonical Pydantic v2 models for SAICA-KG nodes.

This module is the SINGLE SOURCE OF TRUTH for the five node types
(Tool, FailureMode, Paper, Taxonomy, Crosswalk) and their shared
controlled vocabularies.

From here we derive:

* ``schema/*.json``          via :mod:`validator.generate_schemas`
* ``site/src/lib/types.generated.ts``
                              via ``site/scripts/gen-types.mjs`` at build time
* ``pipeline.extract.schemas`` imports the enums / literal lists below rather
                              than redefining them.

Keep ordering of fields on each model deliberate — it drives the generated
JSON Schema ``properties`` ordering, which drives human-friendly diffs
against the committed ``schema/*.json`` files.

Enum values here MUST match ``schema/enums.yml``. That YAML is kept for
humans (it's citation-annotated); this file is kept for machines.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# --- String enums (single-value) ------------------------------------------


class ControlParadigm(str, Enum):
    PREVENTION = "prevention"
    DETECTION = "detection"
    CORRECTION = "correction"
    RECOVERY = "recovery"


class TemporalPhase(str, Enum):
    PRE_GENERATION = "pre_generation"
    IN_GENERATION = "in_generation"
    POST_GENERATION = "post_generation"


class AutonomyLevel(str, Enum):
    FULLY_AUTONOMOUS = "fully_autonomous"
    GRADUATED_HITL = "graduated_hitl"
    FULL_HITL = "full_hitl"


class FailureModeId(str, Enum):
    FABRICATION = "fabrication"
    OBSOLESCENCE = "obsolescence"
    DEPENDENCY_BLINDNESS = "dependency_blindness"
    LOGIC_ERROR = "logic_error"
    SECURITY_VULNERABILITY = "security_vulnerability"
    SCOPE_CREEP = "scope_creep"
    CONTEXT_POLLUTION = "context_pollution"
    SUPPLY_CHAIN_ATTACK = "supply_chain_attack"


class LocusOfControl(str, Enum):
    MODEL = "model"
    PROMPT = "prompt"
    CONTEXT = "context"
    ENVIRONMENT = "environment"
    HUMAN = "human"


class MaturityStatus(str, Enum):
    EXPERIMENTAL = "experimental"
    STABLE = "stable"
    AT_RISK = "at_risk"
    DEPRECATED = "deprecated"
    ABANDONED = "abandoned"


class HarmClass(str, Enum):
    USER_REPORTED = "user_reported"
    DATA_LOSS = "data_loss"
    SECURITY_BREACH = "security_breach"
    FINANCIAL_LOSS = "financial_loss"
    REPUTATIONAL = "reputational"


class IncidentReproducibility(str, Enum):
    CONFIRMED = "confirmed"
    PLAUSIBLE = "plausible"
    ANECDOTAL = "anecdotal"


class EvidenceTier(str, Enum):
    ANECDOTAL = "anecdotal"
    CASE_STUDIED = "case_studied"
    BENCHMARK_VALIDATED = "benchmark_validated"


class CrosswalkConfidence(str, Enum):
    EXACT = "exact"
    PARTIAL = "partial"
    BROADER = "broader"
    NARROWER = "narrower"
    RELATED = "related"


class SaicaAxis(str, Enum):
    FAILURE_MODE = "failure_mode"
    CONTROL_PARADIGM = "control_paradigm"
    TEMPORAL_PHASE = "temporal_phase"
    AUTONOMY_LEVEL = "autonomy_level"
    LOCUS_OF_CONTROL = "locus_of_control"


# --- Shared field type aliases --------------------------------------------

KebabId = Annotated[
    str, Field(pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
]
SnakeId = Annotated[
    str, Field(pattern=r"^[a-z0-9][a-z0-9_]*[a-z0-9]$")
]


# --- Tool -----------------------------------------------------------------


class Tool(BaseModel):
    """A software artifact that supervises AI coding agents."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
        description="Stable kebab-case slug. Never changes.",
    )
    name: str = Field(min_length=1)
    tagline: Optional[str] = Field(default=None, max_length=140)
    description: str = Field(max_length=800)

    first_released: date
    last_updated: Optional[date] = None
    maturity_status: MaturityStatus

    published_by: Optional[str] = Field(
        default=None, description="Organization node id."
    )
    repository_url: Optional[str] = Field(default=None, json_schema_extra={"format": "uri"})
    documentation_url: Optional[str] = Field(default=None, json_schema_extra={"format": "uri"})
    license: str = Field(description="SPDX identifier or 'proprietary'.")

    control_paradigm: ControlParadigm
    temporal_phase: TemporalPhase
    autonomy_level: AutonomyLevel

    addresses_failure_modes: list[FailureModeId] = Field(min_length=1)
    locus_of_control: Optional[list[LocusOfControl]] = None

    implements_techniques: Optional[list[str]] = None
    composes_with: Optional[list[str]] = Field(
        default=None,
        description="Symmetric; both sides must declare.",
    )
    feeds_into: Optional[list[str]] = Field(
        default=None,
        description=(
            "Directed composition. A feeds_into B means A's output is"
            " consumed by B."
        ),
    )
    supersedes: Optional[list[str]] = None
    runtime_requires: Optional[list[str]] = Field(
        default=None,
        description="Libraries/runtimes the tool itself imports.",
    )
    supervises_targets: Optional[list[str]] = Field(
        default=None,
        description="Library / language / ecosystem the tool watches over.",
    )

    cited_in: Optional[list[str]] = None
    documented_in: Optional[list[str]] = None
    evaluated_on: Optional[list[str]] = None

    security_notes: Optional[str] = None
    signed_manifest: Optional[bool] = None
    openssf_scorecard_score: Optional[float] = Field(
        default=None,
        ge=0,
        le=10,
        # Preserve the ["number","null"] shape in generated JSON Schema so the
        # committed schema.json — which explicitly permits null — stays stable.
        json_schema_extra={"_keep_null": True},
    )

    stars: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "GitHub stargazer count, refreshed periodically by"
            " validator/fetch_github_stars.py."
        ),
    )
    stars_updated_at: Optional[date] = Field(
        default=None,
        description="Date the stars count was last fetched (YYYY-MM-DD).",
    )

    contributors: Optional[list[str]] = None
    editorial_notes: Optional[str] = None
    inclusion_rationale: Optional[str] = None


# --- FailureMode ----------------------------------------------------------


class FailureModeCrosswalk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taxonomy: str = Field(description="Taxonomy node id.")
    external_id: str = Field(
        description="Category id or label within that taxonomy."
    )
    confidence: CrosswalkConfidence
    note: Optional[str] = None


class FailureMode(BaseModel):
    """A supervision-addressable failure class."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*[a-z0-9]$")
    name: str
    tagline: Optional[str] = Field(default=None, max_length=140)
    description: str

    aliases: Optional[list[str]] = Field(
        default=None,
        description="Alternative names used in the field.",
    )
    related_modes: Optional[list[str]] = Field(
        default=None,
        description="Other FailureMode ids to disambiguate from.",
    )

    prior_work: list[str] = Field(
        min_length=1,
        description="Paper ids grounding this class in the literature.",
    )
    detection_signals: list[str] = Field(
        min_length=1,
        description="How to recognize an instance.",
    )

    canonical_definition_source: Optional[str] = Field(
        default=None,
        description="Paper id that formalizes this definition, if any.",
    )

    crosswalks: Optional[list[FailureModeCrosswalk]] = Field(
        default=None,
        description=(
            "Explicit mappings from this SAICA-KG class into external"
            " taxonomies."
        ),
    )


# --- Paper ----------------------------------------------------------------


class Paper(BaseModel):
    """An academic or gray-literature reference used to ground nodes in SAICA-KG."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    authors: list[str] = Field(min_length=1)
    year: int = Field(ge=1960, le=2100)
    title: str
    venue: Optional[str] = None
    url: Optional[str] = Field(default=None, json_schema_extra={"format": "uri"})
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    semantic_scholar_id: Optional[str] = None

    abstract: Optional[str] = None
    tldr: Optional[str] = None
    citation_count: Optional[int] = Field(default=None, ge=0)

    relevance_tags: Optional[list[str]] = Field(
        default=None,
        description=(
            "Free tags to help editorial grouping (e.g."
            " 'failure-mode-taxonomy', 'MCP-benchmark')."
        ),
    )

    notes: Optional[str] = None


# --- Taxonomy -------------------------------------------------------------


class TaxonomyCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(
        description=(
            "The taxonomy's own identifier for this category (e.g.,"
            " 'ASI04', 'MAS-FM-7')."
        )
    )
    label: str
    description: Optional[str] = None
    parent_id: Optional[str] = Field(
        default=None,
        description="If the taxonomy is hierarchical.",
    )


class Taxonomy(BaseModel):
    """An external failure-mode or risk taxonomy that SAICA-KG cross-walks into its own facets."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    name: str
    owner: str = Field(description="Owning organization or working group.")
    version: str = Field(
        description=(
            "Version or year identifier of the external taxonomy as of"
            " ingestion."
        )
    )
    first_published: Optional[date] = None
    last_updated: Optional[date] = None
    url: Optional[str] = Field(default=None, json_schema_extra={"format": "uri"})
    license: Optional[str] = None
    paper_id: Optional[str] = Field(
        default=None,
        description="Paper node id if the taxonomy is published academically.",
    )

    scope: Optional[str] = Field(
        default=None,
        description=(
            "What the taxonomy covers (e.g., 'failure modes for multi-agent"
            " systems')."
        ),
    )

    categories: list[TaxonomyCategory] = Field(min_length=1)

    notes: Optional[str] = None
    inclusion_rationale: Optional[str] = None


# --- Crosswalk ------------------------------------------------------------


class CrosswalkMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    saica_value: str = Field(
        description="Value on the SAICA axis (e.g., a FailureMode id)."
    )
    external_id: str = Field(
        description="Category id in the external taxonomy."
    )
    confidence: CrosswalkConfidence
    note: Optional[str] = None


class Crosswalk(BaseModel):
    """A bulk mapping between a SAICA-KG axis and an external taxonomy's categories."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    saica_axis: SaicaAxis
    taxonomy: str = Field(description="Taxonomy node id.")
    authored_by: Optional[list[str]] = None
    reviewed_by: Optional[list[str]] = None
    last_reviewed: Optional[date] = None

    mappings: list[CrosswalkMapping] = Field(min_length=1)


# --- Registry -------------------------------------------------------------


NODE_MODELS: dict[str, type[BaseModel]] = {
    "tools": Tool,
    "failure_modes": FailureMode,
    "papers": Paper,
    "taxonomies": Taxonomy,
    "crosswalks": Crosswalk,
}


__all__ = [
    "AutonomyLevel",
    "ControlParadigm",
    "Crosswalk",
    "CrosswalkConfidence",
    "CrosswalkMapping",
    "EvidenceTier",
    "FailureMode",
    "FailureModeCrosswalk",
    "FailureModeId",
    "HarmClass",
    "IncidentReproducibility",
    "LocusOfControl",
    "MaturityStatus",
    "NODE_MODELS",
    "Paper",
    "SaicaAxis",
    "TemporalPhase",
    "Taxonomy",
    "TaxonomyCategory",
    "Tool",
]
