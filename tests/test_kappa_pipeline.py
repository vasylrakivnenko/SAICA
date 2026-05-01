"""Tests for the §5 κ (inter-rater agreement) pipeline.

Covers:

1. ``research.kappa.rater_b.classify_fault_rules`` on hand-coded fault
   descriptions with expected labels (surface-rule correctness).
2. ``pipeline.extract.kappa_rater.classify_fault_kimi`` with a mocked Kimi
   client (schema-compliance + unknown-enum coercion).
3. The κ math path with trivially identical labels (sanity check that we
   wired ``cohen_kappa_score`` correctly).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from research.kappa.rater_b import (
    CONTROL_PARADIGM_RULES,
    TEMPORAL_PHASE_RULES,
    classify_control_paradigm,
    classify_fault_rules,
    classify_temporal_phase,
)
from research.kappa.run_kappa import compute_kappas


# ---------------------------------------------------------------------------
# Rater B — surface-rule correctness on hand-coded examples
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "description,expected_phase,expected_paradigm,expected_modes_any",
    [
        (
            "Agent failed during installation because the deprecated numpy"
            " API was removed upstream; the build error prevents the Python"
            " package from being installed. Import Error on module resolution.",
            "pre_generation",
            "prevention",
            {"obsolescence"},
        ),
        (
            "The LLM streamed a malformed tool call during generation; "
            "token counter produced incorrect context window tracking leading"
            " to context overflow.",
            "in_generation",
            None,  # we don't require a specific regime
            {"context_pollution", "logic_error"},
        ),
        (
            "Execution crashed at runtime when the tool invocation wrote"
            " state to the database after the model response; downstream"
            " computations propagated NaN values causing cascading failures.",
            "post_generation",
            "recovery",
            {"logic_error", "cascading_failure"},
        ),
        (
            "Authentication bypass: missing credential validation allows"
            " unauthorized access to protected endpoints — a security "
            "vulnerability.",
            None,  # ambiguous phase; we accept any
            None,
            {"security_vulnerability"},
        ),
    ],
)
def test_rule_based_rater_classifies_known_examples(
    description, expected_phase, expected_paradigm, expected_modes_any
):
    cls = classify_fault_rules(description)
    if expected_phase is not None:
        assert (
            cls.temporal_phase == expected_phase
        ), f"phase mismatch: got {cls.temporal_phase!r}"
    if expected_paradigm is not None:
        assert (
            cls.control_paradigm == expected_paradigm
        ), f"paradigm mismatch: got {cls.control_paradigm!r}"
    emitted = set(cls.failure_modes)
    # Require at least one of the expected modes to be present (rule-based
    # raters are imprecise and may catch additional modes, which is fine).
    assert (
        emitted & expected_modes_any
    ), f"expected one of {expected_modes_any}, got {emitted}"


def test_rule_tables_are_non_empty():
    """Guardrail: rule tables must stay populated if someone trims them."""
    assert set(TEMPORAL_PHASE_RULES) == {
        "pre_generation",
        "in_generation",
        "post_generation",
    }
    assert set(CONTROL_PARADIGM_RULES) == {
        "prevention",
        "detection",
        "correction",
        "recovery",
    }
    for kws in TEMPORAL_PHASE_RULES.values():
        assert len(kws) >= 3
    for kws in CONTROL_PARADIGM_RULES.values():
        assert len(kws) >= 3


def test_empty_description_returns_nulls():
    cls = classify_fault_rules("")
    assert cls.temporal_phase is None
    assert cls.control_paradigm is None
    assert cls.failure_modes == []


def test_control_paradigm_confidence_is_higher_when_unambiguous():
    _, conf_high, _ = classify_control_paradigm(
        "prevent prevention validate schema check"
    )
    _, conf_low, _ = classify_control_paradigm(
        "prevent retry recover log trace"  # all four fire
    )
    assert conf_high > conf_low


def test_temporal_phase_confidence_is_higher_when_unambiguous():
    _, conf_high, _ = classify_temporal_phase(
        "installation dependency configuration setup import build"
    )
    _, conf_low, _ = classify_temporal_phase(
        "install stream execute"  # one keyword in each phase
    )
    assert conf_high > conf_low


# ---------------------------------------------------------------------------
# Rater A — Kimi client mocked; verify schema compliance + coercion
# ---------------------------------------------------------------------------


def _fake_tool_call_response(payload: dict) -> SimpleNamespace:
    """Build a fake OpenAI ``ChatCompletion`` shape that ``_call_kimi_function``
    will successfully parse."""
    tool_call = SimpleNamespace(
        function=SimpleNamespace(
            name="record_fault_classification",
            arguments=json.dumps(payload),
        )
    )
    message = SimpleNamespace(tool_calls=[tool_call], content="")
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(total_tokens=123)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_kimi_rater_returns_schema_compliant_output():
    from pipeline.extract.kappa_rater import classify_fault_kimi

    fake_payload = {
        "control_paradigm": "prevention",
        "control_paradigm_confidence": 0.85,
        "temporal_phase": "pre_generation",
        "temporal_phase_confidence": 0.9,
        "failure_modes": ["logic_error", "obsolescence"],
        "failure_modes_confidence": 0.7,
        "evidence": ["installation failed because the dependency was missing"],
    }
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_tool_call_response(fake_payload)

    result = classify_fault_kimi(
        "Installation failed because the dependency was missing.",
        client=client,
        fault_id="fake-1",
    )

    # Schema-compliance: exact enum values, typed confidences, list of
    # strings for evidence.
    assert result.control_paradigm == "prevention"
    assert 0.0 <= result.control_paradigm_confidence <= 1.0
    assert result.temporal_phase == "pre_generation"
    assert 0.0 <= result.temporal_phase_confidence <= 1.0
    assert set(result.failure_modes) == {"logic_error", "obsolescence"}
    assert 0.0 <= result.failure_modes_confidence <= 1.0
    assert isinstance(result.evidence, list)
    assert all(isinstance(x, str) for x in result.evidence)


def test_kimi_rater_coerces_unknown_enum_values_to_null():
    """Misbehaving model emits an out-of-vocab enum — we must coerce, not crash."""
    from pipeline.extract.kappa_rater import classify_fault_kimi

    fake_payload = {
        "control_paradigm": "banana",  # not a valid ControlParadigm
        "control_paradigm_confidence": 0.3,
        "temporal_phase": "during-thinking",  # not a valid TemporalPhase
        "temporal_phase_confidence": 0.2,
        "failure_modes": ["logic_error", "imaginary_mode"],  # 2nd is invalid
        "failure_modes_confidence": 0.5,
        "evidence": [],
    }
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_tool_call_response(fake_payload)

    result = classify_fault_kimi("noise", client=client, fault_id="fake-2")
    assert result.control_paradigm is None
    assert result.temporal_phase is None
    assert set(result.failure_modes) == {"logic_error"}


# ---------------------------------------------------------------------------
# Cohen's κ math — sanity checks
# ---------------------------------------------------------------------------


def _mk_rater_record(
    fid: str, cp: str | None, tp: str | None, modes: list[str]
) -> dict:
    return {
        "fault_id": fid,
        "classification": {
            "control_paradigm": cp,
            "control_paradigm_confidence": 0.9,
            "temporal_phase": tp,
            "temporal_phase_confidence": 0.9,
            "failure_modes": modes,
            "failure_modes_confidence": 0.9,
            "evidence": [],
        },
    }


def test_cohens_kappa_trivially_agrees_on_identical_labels():
    """κ must be 1.0 for identical label sequences on all three facets."""
    rater_a = [
        _mk_rater_record("f1", "prevention", "pre_generation", ["logic_error"]),
        _mk_rater_record("f2", "detection", "in_generation", ["context_pollution"]),
        _mk_rater_record("f3", "correction", "post_generation", ["obsolescence"]),
        _mk_rater_record("f4", "recovery", "post_generation", ["cascading_failure"]),
    ]
    rater_b = [dict(r) for r in rater_a]
    from pipeline.models import FailureModeId

    all_modes = [m.value for m in FailureModeId]
    metrics = compute_kappas(rater_a, rater_b, all_modes)

    assert metrics["control_paradigm"]["kappa"] == pytest.approx(1.0)
    assert metrics["temporal_phase"]["kappa"] == pytest.approx(1.0)
    # FailureMode: each mode present in both raters yields κ=1. Modes absent
    # from both get skipped.
    nonzero = [
        v["kappa"]
        for v in metrics["failure_mode"]["per_mode"].values()
        if v["kappa"] is not None
    ]
    assert nonzero, "expected at least one mode κ value"
    assert all(v == pytest.approx(1.0) for v in nonzero)
    assert metrics["failure_mode"]["jaccard_mean"] == pytest.approx(1.0)


def test_cohens_kappa_catches_total_disagreement():
    rater_a = [
        _mk_rater_record("f1", "prevention", "pre_generation", ["logic_error"]),
        _mk_rater_record("f2", "prevention", "pre_generation", ["logic_error"]),
        _mk_rater_record("f3", "detection", "in_generation", []),
        _mk_rater_record("f4", "detection", "in_generation", []),
    ]
    rater_b = [
        _mk_rater_record("f1", "detection", "in_generation", ["obsolescence"]),
        _mk_rater_record("f2", "detection", "in_generation", ["obsolescence"]),
        _mk_rater_record("f3", "prevention", "pre_generation", ["fabrication"]),
        _mk_rater_record("f4", "prevention", "pre_generation", ["fabrication"]),
    ]
    from pipeline.models import FailureModeId

    all_modes = [m.value for m in FailureModeId]
    metrics = compute_kappas(rater_a, rater_b, all_modes)
    # Perfectly swapped 2-class labels → κ = -1 (perfect disagreement).
    assert metrics["control_paradigm"]["kappa"] == pytest.approx(-1.0)
    assert metrics["temporal_phase"]["kappa"] == pytest.approx(-1.0)
