"""Tests for ``pipeline.extract.verify``.

We construct synthetic ``ToolExtraction`` objects and check the verifier
classifies each field's quotes correctly. Quote semantics intentionally
strict — we should fail to verify paraphrases.
"""

from __future__ import annotations

import pytest

from pipeline.extract.schemas import ConfidenceField, ToolExtraction
from pipeline.extract.verify import (
    review_required_fields,
    verify_extraction,
    verify_field,
    verify_quote,
)


SOURCE = """
LangSentry is a runtime guard for LLM applications. It detects
hallucinated package imports at code-generation time and refuses to
emit them. The library is published as a Python package.

Built by the LangSafety community in 2025. MIT licensed.
"""


def _f(value=None, *, conf=0.9, evidence=()) -> ConfidenceField:
    return ConfidenceField(value=value, confidence=conf, evidence=list(evidence))


def _extract_minimal(**overrides) -> ToolExtraction:
    """Build a ToolExtraction with all fields filled by `_f` defaults
    unless overridden. Saves boilerplate per test."""
    fields = {
        "proposed_id": _f("langsentry"),
        "name": _f("LangSentry"),
        "tagline": _f("Runtime guard for LLM apps"),
        "description": _f("Detects hallucinated package imports."),
        "repository_url": _f("https://github.com/langsafety/langsentry"),
        "license_spdx": _f("MIT"),
        "control_paradigm": _f("prevention"),
        "temporal_phase": _f("in_generation"),
        "autonomy_level": _f("fully_autonomous"),
        "addresses_failure_modes": _f(["fabrication"]),
        "locus_of_control": _f(["model"]),
        "inclusion_rationale": _f("Fills prevention × in_generation × fully_autonomous."),
        "overall_confidence": 0.9,
    }
    fields.update(overrides)
    return ToolExtraction(**fields)


# ---------------------------------------------------------------------------
# verify_quote — unit
# ---------------------------------------------------------------------------


def test_verify_quote_exact_match() -> None:
    src = "the quick brown fox"
    from pipeline.extract.verify import _normalise

    assert verify_quote("the quick brown fox", _normalise(src))


def test_verify_quote_case_insensitive() -> None:
    from pipeline.extract.verify import _normalise

    src = "Hallucinated package imports"
    assert verify_quote("HALLUCINATED package IMPORTS", _normalise(src))


def test_verify_quote_whitespace_collapse() -> None:
    from pipeline.extract.verify import _normalise

    src = "runtime  guard  for   LLM\tapplications"
    assert verify_quote("runtime guard for LLM applications", _normalise(src))


def test_verify_quote_unicode_nbsp() -> None:
    """NBSP / thin space / zero-width chars normalise to plain space."""
    from pipeline.extract.verify import _normalise

    src = "runtime guard"  # NBSP between words
    assert verify_quote("runtime guard", _normalise(src))


def test_verify_quote_strips_wrapping_quotes() -> None:
    """LLMs sometimes wrap copied quotes in stray double-quotes."""
    from pipeline.extract.verify import _normalise

    src = "It detects hallucinated package imports"
    assert verify_quote('"hallucinated package imports"', _normalise(src))


def test_verify_quote_rejects_paraphrase() -> None:
    """Strict substring match — paraphrase must NOT verify."""
    from pipeline.extract.verify import _normalise

    src = "It detects hallucinated package imports at code-generation time."
    assert not verify_quote(
        "Detects fabricated module names during generation",
        _normalise(src),
    )


def test_verify_quote_rejects_invented_quote() -> None:
    """Quote that doesn't appear in the source at all — must fail."""
    from pipeline.extract.verify import _normalise

    src = "LangSentry is a runtime guard."
    assert not verify_quote("Built on top of OpenAI's moderation API", _normalise(src))


def test_empty_quote_returns_false() -> None:
    from pipeline.extract.verify import _normalise

    assert not verify_quote("", _normalise("anything"))


# ---------------------------------------------------------------------------
# verify_field — single ConfidenceField
# ---------------------------------------------------------------------------


def test_verify_field_all_verified() -> None:
    from pipeline.extract.verify import _normalise

    cf = _f("LangSentry", evidence=["LangSentry is a runtime guard"])
    fv = verify_field("name", cf, source_normalised=_normalise(SOURCE))
    assert fv.all_verified
    assert fv.unverified_quotes == []


def test_verify_field_partial_match() -> None:
    """One verified, one fabricated — field is not all_verified, but
    quotes_verified reflects the partial credit."""
    from pipeline.extract.verify import _normalise

    cf = _f(
        ["fabrication"],
        evidence=[
            "hallucinated package imports",   # in source
            "OWASP LLM Top-10 entry",         # NOT in source
        ],
    )
    fv = verify_field(
        "addresses_failure_modes", cf, source_normalised=_normalise(SOURCE)
    )
    assert not fv.all_verified
    assert fv.quotes_verified == 1
    assert fv.quotes_total == 2
    assert "OWASP LLM Top-10 entry" in fv.unverified_quotes


def test_verify_field_no_evidence_is_not_verified() -> None:
    """A field with empty evidence is `has_evidence=False` and reports
    `all_verified=False` (cannot verify nothing)."""
    from pipeline.extract.verify import _normalise

    cf = _f("LangSentry", evidence=[])
    fv = verify_field("name", cf, source_normalised=_normalise(SOURCE))
    assert not fv.has_evidence
    assert not fv.all_verified
    assert fv.quotes_total == 0


# ---------------------------------------------------------------------------
# verify_extraction — whole-model
# ---------------------------------------------------------------------------


def test_verify_extraction_clean() -> None:
    extraction = _extract_minimal(
        name=_f("LangSentry", evidence=["LangSentry is a runtime guard"]),
        tagline=_f(
            "Runtime guard for LLM apps",
            evidence=["runtime guard for LLM applications"],
        ),
        addresses_failure_modes=_f(
            ["fabrication"],
            evidence=["hallucinated package imports"],
        ),
    )
    result = verify_extraction(extraction, SOURCE)
    # Only the three fields with evidence should be all_verified.
    for name in ("name", "tagline", "addresses_failure_modes"):
        assert result.fields[name].all_verified, name
    assert result.unverified_fields() == []


def test_verify_extraction_flags_invented_quote() -> None:
    extraction = _extract_minimal(
        addresses_failure_modes=_f(
            ["fabrication", "supply_chain_attack"],
            evidence=[
                "hallucinated package imports",   # legit
                "Detects malicious typosquatted packages",  # invented
            ],
        ),
    )
    result = verify_extraction(extraction, SOURCE)
    assert "addresses_failure_modes" in result.unverified_fields()
    assert not result.all_verified


def test_verify_extraction_skips_non_evidence_fields() -> None:
    """`overall_confidence` is a plain float — must NOT crash the verifier."""
    extraction = _extract_minimal()
    result = verify_extraction(extraction, SOURCE)
    assert "overall_confidence" not in result.fields


# ---------------------------------------------------------------------------
# review_required_fields — convenience layer
# ---------------------------------------------------------------------------


def test_review_required_unverified_quote() -> None:
    extraction = _extract_minimal(
        addresses_failure_modes=_f(
            ["fabrication"],
            evidence=["This is not in the source at all"],
        ),
    )
    needs = review_required_fields(extraction, SOURCE)
    assert "addresses_failure_modes" in needs


def test_review_required_evidence_required_but_empty() -> None:
    """A field listed in `require_evidence` with empty evidence must be
    flagged even though it has no failed quotes."""
    extraction = _extract_minimal(
        control_paradigm=_f("prevention", evidence=[]),  # no evidence
    )
    needs = review_required_fields(
        extraction,
        SOURCE,
        require_evidence={"control_paradigm"},
    )
    assert "control_paradigm" in needs


def test_review_required_clean_extraction_returns_empty() -> None:
    extraction = _extract_minimal(
        name=_f("LangSentry", evidence=["LangSentry is a runtime guard"]),
    )
    needs = review_required_fields(extraction, SOURCE)
    assert needs == set()


# ---------------------------------------------------------------------------
# Failure-mode regression: invented evidence is the worst class.
# ---------------------------------------------------------------------------


def test_pure_hallucination_is_caught() -> None:
    """Real-world failure mode: LLM emits a confident value with a
    plausible-looking but invented quote. Verifier MUST catch it."""
    extraction = _extract_minimal(
        license_spdx=_f(
            "Apache-2.0",
            conf=0.95,
            evidence=["Released under the Apache License, Version 2.0"],
        ),
    )
    # SOURCE says MIT, not Apache — and the quote is invented.
    result = verify_extraction(extraction, SOURCE)
    assert "license_spdx" in result.unverified_fields()
