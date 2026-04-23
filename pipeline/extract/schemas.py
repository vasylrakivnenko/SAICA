"""Pydantic v2 schemas for Azure Kimi-K2.5 structured extraction.

Every field on a ``*Extraction`` model is a ``ConfidenceField`` — a tuple of
(value, confidence, evidence). This is deliberately verbose: the LLM cannot
silently "pick" a value for us; it has to own a confidence score, and it has
to quote supporting text. Anything below graduation threshold will be
re-surfaced to a human reviewer as ``# REVIEW REQUIRED``.

Enum literals are re-exported from the canonical :mod:`pipeline.models` so
they cannot drift from ``schema/enums.yml`` / ``schema/*.json``. If a new
value lands in the canonical models, it flows here automatically.
"""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

from pipeline import models as _canonical


def _literal_from_enum(enum_cls: type) -> object:
    """Build a ``Literal[...]`` from an Enum's member values.

    Pydantic's JSON-schema emitter renders ``Literal`` cleanly as an
    ``enum`` array of strings, which is what Kimi's function-calling path
    expects. We deliberately keep these as ``Literal`` rather than passing
    the Enum itself so the Kimi schema doesn't carry Python-side metadata
    the model can't reason about.
    """
    values = tuple(m.value for m in enum_cls)
    return Literal[values]  # type: ignore[valid-type]


# --- Controlled vocabularies (re-export from pipeline.models) -------------

FailureModeId = _literal_from_enum(_canonical.FailureModeId)
ControlParadigm = _literal_from_enum(_canonical.ControlParadigm)
TemporalPhase = _literal_from_enum(_canonical.TemporalPhase)
AutonomyLevel = _literal_from_enum(_canonical.AutonomyLevel)
LocusOfControl = _literal_from_enum(_canonical.LocusOfControl)


# --- ConfidenceField -------------------------------------------------------


class ConfidenceField(BaseModel):
    """(value, confidence, evidence) triple produced by the LLM.

    ``value`` is intentionally typed as ``Any``-ish (str | list[str] | None)
    because different call-sites carry different shapes — enum strings,
    lists of failure-mode ids, free text. The ``*Extraction`` model's
    docstring pins the expected shape per field.
    """

    value: Optional[Union[str, list[str]]] = Field(
        default=None,
        description=(
            "Extracted value. Null with low confidence is preferred over"
            " guessing a value."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="0–1 self-rated confidence in ``value``.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description=(
            "Direct quotes from the source material that support ``value``."
            " Empty list is acceptable when value is null."
        ),
    )


# --- ToolExtraction --------------------------------------------------------


class ToolExtraction(BaseModel):
    """Fields extracted from candidate_tools rows.

    Enum fields (``control_paradigm``, ``temporal_phase``, ``autonomy_level``)
    carry their value as a string matching the corresponding ``Literal``
    above; the LLM is instructed to return null + low confidence if unsure.

    ``addresses_failure_modes`` carries ``value: list[FailureModeId]``.
    ``locus_of_control`` carries ``value: list[LocusOfControl]``.
    """

    proposed_id: ConfidenceField = Field(
        description="Stable kebab-case slug. Never changes once graduated."
    )
    name: ConfidenceField = Field(description="Human-facing product name.")
    tagline: ConfidenceField = Field(
        description="<=140 char one-liner; first sentence of a good description."
    )
    description: ConfidenceField = Field(
        description="<=800 char paragraph describing what the tool does."
    )
    repository_url: ConfidenceField = Field(
        description="Canonical repo URL (prefer github.com/owner/repo)."
    )
    license_spdx: ConfidenceField = Field(
        description="SPDX license id (e.g. MIT, Apache-2.0) or 'proprietary'."
    )
    control_paradigm: ConfidenceField = Field(
        description="One of prevention|detection|correction|recovery, or null."
    )
    temporal_phase: ConfidenceField = Field(
        description="One of pre_generation|in_generation|post_generation, or null."
    )
    autonomy_level: ConfidenceField = Field(
        description="One of fully_autonomous|graduated_hitl|full_hitl, or null."
    )
    addresses_failure_modes: ConfidenceField = Field(
        description=(
            "list of FailureModeId values from the closed SAICA-KG set."
            " Multi-valued; may be empty if unclear."
        )
    )
    locus_of_control: ConfidenceField = Field(
        description=(
            "Subset of model|prompt|context|environment|human. Multi-valued;"
            " may be empty."
        )
    )
    inclusion_rationale: ConfidenceField = Field(
        description=(
            "Short justification: which MECE cell this tool occupies and"
            " why it merits inclusion."
        )
    )
    overall_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Aggregate confidence in the whole extraction. Low values (<0.6)"
            " force the human reviewer to go field-by-field."
        ),
    )


# --- PaperExtraction -------------------------------------------------------


class PaperExtraction(BaseModel):
    """Fields extracted from candidate_papers rows.

    ``authors`` carries ``value: list[str]``. ``relevance_tags`` carries
    ``value: list[str]`` of free-form tags — lowercased, hyphen-separated.
    """

    title: ConfidenceField
    authors: ConfidenceField = Field(
        description="list[str] of author full names, in source order."
    )
    year: ConfidenceField = Field(
        description="Publication year as a string (e.g. '2025')."
    )
    venue: ConfidenceField = Field(
        description="Venue or 'arXiv preprint' or 'workshop/...'."
    )
    doi: ConfidenceField = Field(description="DOI without URL prefix.")
    arxiv_id: ConfidenceField = Field(description="arXiv id (e.g. '2506.12345').")
    tldr: ConfidenceField = Field(
        description="1–2 sentence summary; aim for the paper's own abstract's first sentence."
    )
    relevance_tags: ConfidenceField = Field(
        description="list[str] of free-form SAICA-KG editorial tags."
    )
    overall_confidence: float = Field(ge=0.0, le=1.0)


__all__ = [
    "AutonomyLevel",
    "ConfidenceField",
    "ControlParadigm",
    "FailureModeId",
    "LocusOfControl",
    "PaperExtraction",
    "TemporalPhase",
    "ToolExtraction",
]
