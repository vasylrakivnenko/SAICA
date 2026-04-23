"""Standardized supervision-focused query passages for Cohere Rerank.

Each query targets a SAICA-KG supervision concern — either the big-picture
"does this tool supervise AI coding agents at all" question, or one specific
failure_mode / control_paradigm facet. Kept deliberately small (<=10) so
every candidate is scored in ~N_queries HTTP calls, capping cost + latency.

Exports:
    RerankQuery            -- pydantic model with id / text / facet / weight
    SUPERVISION_QUERIES    -- the canonical list, used as the CLI default
    QUERY_SET_VERSION      -- bump manually when the list is edited
    queries_content_hash() -- short SHA1 fingerprint of the live list

Stored rerank scores are only comparable across candidates when they were
produced against the *same* query set. ``rerank_candidates`` writes both
``QUERY_SET_VERSION`` and ``queries_content_hash()`` alongside each score;
a later reviewer/CLI uses the hash to detect stale scores and re-rerank.
"""

from __future__ import annotations

from hashlib import sha1
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


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------
#
# Re-bump ``QUERY_SET_VERSION`` *in the same commit* that edits
# ``SUPERVISION_QUERIES`` (text, ids, order, or list membership). The version
# string is opaque to consumers; it just needs to be monotonically unique.
#
# ``queries_content_hash()`` is derived from the live list; it detects edits
# that forgot to bump the version too. Readers typically treat a mismatch
# against the stored hash as "this score is stale".

QUERY_SET_VERSION = "2026-04-23.v1"


def queries_content_hash() -> str:
    """Short SHA1 fingerprint of (id, text) pairs for the live query set."""
    blob = "|".join(q.id + ":" + q.text for q in SUPERVISION_QUERIES).encode()
    return sha1(blob).hexdigest()[:12]


__all__ = [
    "QUERY_SET_VERSION",
    "RerankQuery",
    "SUPERVISION_QUERIES",
    "queries_content_hash",
]
