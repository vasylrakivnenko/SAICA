"""Standardized supervision-focused query passages for Cohere Rerank.

Each query targets a SAICA-KG supervision concern — either the big-picture
"does this tool supervise AI coding agents at all" question, or one specific
failure_mode / control_paradigm facet. Kept deliberately small (<=10) so
every candidate is scored in ~N_queries HTTP calls, capping cost + latency.

Exports:
    RerankQuery          -- pydantic model with id / text / facet / weight
    SUPERVISION_QUERIES  -- the canonical list, used as the CLI default
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class RerankQuery(BaseModel):
    """A single query passage against which candidates are re-ranked."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        pattern=r"^[a-z0-9][a-z0-9_]*[a-z0-9]$",
        description="Stable short slug for this query. Used in per_query keys.",
    )
    text: str = Field(min_length=1)
    facet: Optional[str] = Field(
        default=None,
        description=(
            "Optional hint for which SAICA facet this query biases toward, "
            "e.g. 'failure_mode=fabrication' or 'control_paradigm=detection'."
        ),
    )
    weight: float = Field(default=1.0, ge=0.0, le=10.0)


SUPERVISION_QUERIES: list[RerankQuery] = [
    RerankQuery(
        id="general",
        text=(
            "An open-source software tool that supervises or safeguards AI "
            "coding agents — including guardrails, validators, sandboxes, or "
            "policy enforcers that prevent, detect, or correct agent failures."
        ),
    ),
    RerankQuery(
        id="fabrication",
        text=(
            "A tool that detects or prevents hallucinated packages, "
            "non-existent APIs, or fabricated references emitted by LLM "
            "code agents."
        ),
        facet="failure_mode=fabrication",
    ),
    RerankQuery(
        id="obsolescence",
        text=(
            "A tool that detects or prevents the use of deprecated APIs or "
            "outdated library versions in LLM-generated code."
        ),
        facet="failure_mode=obsolescence",
    ),
    RerankQuery(
        id="supply_chain",
        text=(
            "A tool that defends against package typosquatting, "
            "slopsquatting, or compromised dependencies when an LLM agent "
            "installs code."
        ),
        facet="failure_mode=supply_chain_attack",
    ),
    RerankQuery(
        id="sandbox",
        text=(
            "A sandbox, secure runtime, or isolated execution environment "
            "for running code emitted by AI agents."
        ),
        facet="control_paradigm=recovery",
    ),
    RerankQuery(
        id="observability",
        text=(
            "A tracing, monitoring, or evaluation platform for observing "
            "LLM agent behaviors and failures in production."
        ),
        facet="control_paradigm=detection",
    ),
    RerankQuery(
        id="scope_gate",
        text=(
            "A tool that constrains an autonomous AI coding agent to its "
            "assigned scope with approval gates, allow-lists, or policy "
            "enforcement."
        ),
        facet="failure_mode=scope_creep",
    ),
    RerankQuery(
        id="structured_output",
        text=(
            "A library that enforces structured output, schema validation, "
            "or constrained decoding on LLM responses."
        ),
    ),
]


__all__ = ["RerankQuery", "SUPERVISION_QUERIES"]
