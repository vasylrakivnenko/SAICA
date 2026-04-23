"""Kimi-driven fault-classification rater for the κ empirical validation.

This is **Rater A** in the §5 inter-rater-agreement study. Given a
real-world agent fault description, Kimi emits one
``FaultClassification`` — ``(control_paradigm, temporal_phase,
failure_modes)`` — against SAICA-KG's controlled vocabularies.

Deliberately independent of :mod:`pipeline.extract.kimi`'s tool/paper prompts:

- Different unit-of-analysis (a fault, not a supervision tool).
- Different semantics for ``control_paradigm`` / ``temporal_phase``:
    * For faults, ``temporal_phase`` is the LIFE-CYCLE STAGE at which the
      fault manifests — ``pre_generation`` (setup / configuration /
      dependency resolution), ``in_generation`` (LLM reasoning or output
      production), ``post_generation`` (execution, tool invocation, state
      persistence after the model has produced tokens).
    * For faults, ``control_paradigm`` is the supervision regime that
      would most naturally catch/handle the fault —
      ``prevention`` (stop it before manifestation), ``detection`` (flag
      it once manifested), ``correction`` (repair in-flight), or
      ``recovery`` (graceful fall-back after the fact).

Rater B (the keyword rule engine in :mod:`research.kappa.rater_b`) is
purposefully different — it applies deterministic surface-pattern rules to
the same description. Both raters emit the same schema so
``cohen_kappa_score`` can be computed over identical label sets.

This module is new and contains no business logic beyond classification;
it does not touch any existing YAML, DB, or graduation path.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from pipeline.cost_caps import CallBudget
from pipeline.extract.kimi import (
    FAILURE_MODE_DEFINITIONS,
    _call_kimi_function,
    _json_schema_for,
    get_client,
)
from pipeline.models import ControlParadigm, FailureModeId, TemporalPhase

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class FaultClassification(BaseModel):
    """Kimi's classification of ONE fault description."""

    control_paradigm: Optional[str] = Field(
        default=None,
        description=(
            "Which supervision regime would most naturally address this fault? "
            "One of: prevention, detection, correction, recovery. Null when "
            "the description does not disambiguate."
        ),
    )
    control_paradigm_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    temporal_phase: Optional[str] = Field(
        default=None,
        description=(
            "At which life-cycle phase does the fault manifest? "
            "pre_generation (before the LLM produces output — setup/config/"
            "dependency/installation), in_generation (during LLM reasoning "
            "or streaming output), post_generation (execution / tool "
            "invocation / state persistence after the LLM has spoken). "
            "Null when the description is ambiguous."
        ),
    )
    temporal_phase_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    failure_modes: list[str] = Field(
        default_factory=list,
        description=(
            "Subset of the 11 canonical SAICA-KG FailureModeIds this fault "
            "exhibits. MAY be empty when no mode fits. Multi-label allowed."
        ),
    )
    failure_modes_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    evidence: list[str] = Field(
        default_factory=list,
        description="Short direct quotes from the fault description supporting these labels.",
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _render_failure_mode_reference() -> str:
    lines = [
        "## FailureMode reference (the 11 canonical ids, verbatim)",
        "",
    ]
    for fm_id, defn in FAILURE_MODE_DEFINITIONS.items():
        lines.append(f"- `{fm_id}`: {defn}")
    return "\n".join(lines)


SYSTEM_PROMPT = """\
You are a fault-classification assistant for SAICA-KG's §5 empirical
validation study. Given ONE real-world agentic-AI fault description
(usually drawn from a GitHub issue or PR in a published taxonomy), your
job is to emit a structured classification against THREE SAICA-KG facets:

1. **control_paradigm** — which supervision regime would most naturally
   address this fault?
   - `prevention`: block the fault before it manifests (e.g. schema
     validation before tool call, dependency pinning before install).
   - `detection`: flag the fault once manifested but not prevented
     (e.g. logging a silent exception, test that catches a bad output).
   - `correction`: repair the problem in-flight (e.g. auto-retry with
     backoff, reroute after a tool error, patch a malformed LLM output).
   - `recovery`: gracefully fall back / restart after a terminal failure
     (e.g. resume from checkpoint, release locks, apologise and stop).
   Use null + confidence <=0.4 when the description doesn't pin the
   regime unambiguously.

2. **temporal_phase** — at which life-cycle phase does the fault manifest?
   - `pre_generation`: before the LLM produces any output (environment
     setup, dependency resolution, install/build, module import,
     LLM-provider configuration, credential loading, context loading).
   - `in_generation`: during LLM reasoning / streaming / output
     production (token tracking, context-window handling, tool-call
     construction by the model, structured-output parsing, streaming
     coordination).
   - `post_generation`: after the model has emitted a response
     (tool-call execution, external API invocation, state persistence,
     resource teardown, result validation, downstream computation).
   Use null + confidence <=0.4 when the fault straddles phases.

3. **failure_modes** — multi-label subset of the 11 canonical SAICA-KG
   FailureModeIds. Include every id that the fault description
   SUPPORTS with direct language or canonical synonym. Empty list is
   correct when no mode fits cleanly.

{failure_mode_reference}

## Output discipline

- Use ONLY the 11 listed failure-mode ids verbatim. Do NOT invent new ones.
- control_paradigm ∈ {{prevention, detection, correction, recovery}} or null.
- temporal_phase ∈ {{pre_generation, in_generation, post_generation}} or null.
- Prefer null-with-low-confidence over guessing.
- Evidence is a list of short direct quotes from the description.
- You MUST call the provided function. No free-form text.
""".format(failure_mode_reference=_render_failure_mode_reference())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_fault_kimi(
    description: str,
    *,
    client=None,
    budget: Optional[CallBudget] = None,
    fault_id: str = "",
) -> FaultClassification:
    """Classify ONE fault description with Kimi.

    ``budget`` is threaded into :func:`_call_kimi_function` — one call per
    fault. Raises :class:`CostCapExceeded` when the ceiling is tripped.
    """
    client = client or get_client()
    schema = _json_schema_for(FaultClassification)
    user = (
        f"Fault id: {fault_id or '(unnamed)'}\n\n"
        f"Description:\n{description.strip()}"
    )
    args = _call_kimi_function(
        client=client,
        tool_name="record_fault_classification",
        tool_parameters=schema,
        system=SYSTEM_PROMPT,
        user=user,
        budget=budget,
    )
    # Sanitize unknown enum values to null; we do this post-hoc rather than
    # baking them into Literal[] so misbehaving models don't hard-fail the
    # whole batch — they just land as null with low confidence.
    cp = args.get("control_paradigm")
    if cp not in {m.value for m in ControlParadigm}:
        log.warning("kimi returned unknown control_paradigm=%r; coerced to null", cp)
        args["control_paradigm"] = None
    tp = args.get("temporal_phase")
    if tp not in {m.value for m in TemporalPhase}:
        log.warning("kimi returned unknown temporal_phase=%r; coerced to null", tp)
        args["temporal_phase"] = None
    modes_in = args.get("failure_modes") or []
    valid_modes = {m.value for m in FailureModeId}
    args["failure_modes"] = [m for m in modes_in if m in valid_modes]
    return FaultClassification.model_validate(args)


__all__ = [
    "FaultClassification",
    "SYSTEM_PROMPT",
    "classify_fault_kimi",
]
