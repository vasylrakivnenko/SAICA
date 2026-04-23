"""Unit tests for the Kimi extraction prompt + license pre-seed.

These tests are pure-Python and never touch the Azure endpoint or the
Postgres DB — they exercise the prompt-building path and the SPDX
extractor helper. The live API smoke lives in
``pipeline/extract/tests/test_kimi_smoke.py``.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pipeline.extract import kimi
from pipeline.extract.schemas import ToolExtraction


# ---------------------------------------------------------------------------
# License pre-seed: prompt composition
# ---------------------------------------------------------------------------


def test_license_preseed_uses_github_api_spdx() -> None:
    """An inline raw_json with a real SPDX id must be surfaced in the prompt."""
    row = {
        "source_url": "https://github.com/acme/supervisor",
        "raw_json": {"license": {"spdx_id": "Apache-2.0", "name": "Apache License 2.0"}},
    }
    prompt = kimi._build_system_prompt(row)
    assert "Apache-2.0" in prompt
    assert "GitHub API license field" in prompt
    # Authoritative framing — reviewer will be suspicious if the language is
    # weak; assert the "0.95" confidence anchor is present so the LLM has
    # a concrete number to target.
    assert "0.95" in prompt


def test_license_preseed_absent_when_spdx_missing() -> None:
    """No SPDX id -> prompt contains no license-authority block."""
    # case 1: raw_json has license=None
    row1 = {"source_url": "https://github.com/acme/x", "raw_json": {"license": None}}
    # case 2: empty spdx_id
    row2 = {
        "source_url": "https://github.com/acme/y",
        "raw_json": {"license": {"spdx_id": ""}},
    }
    # case 3: GitHub's NOASSERTION sentinel — treat as no-signal
    row3 = {
        "source_url": "https://github.com/acme/z",
        "raw_json": {"license": {"spdx_id": "NOASSERTION"}},
    }
    # case 4: no raw_json at all, no source_url -> no DB lookup attempted
    row4 = {"proposed_id": "no-url"}

    for row in (row1, row2, row3, row4):
        prompt = kimi._build_system_prompt(row)
        assert "GitHub API license field" not in prompt, (
            f"expected no license authority block for {row!r}"
        )
        assert "License pre-seed (authoritative)" not in prompt


def test_license_preseed_none_when_candidate_row_is_none() -> None:
    """Passing no candidate row should just return the base prompt."""
    prompt = kimi._build_system_prompt(None)
    assert prompt == kimi.SYSTEM_PROMPT


def test_spdx_extractor_handles_non_dict_input() -> None:
    """Defensive: strings, lists, and None must return None cleanly."""
    for bad in (None, "MIT", [], 42, {"license": "MIT"}, {"license": []}):
        assert kimi._spdx_from_raw_json(bad) is None


def test_spdx_extractor_strips_whitespace_and_case_sentinels() -> None:
    assert kimi._spdx_from_raw_json({"license": {"spdx_id": "  MIT  "}}) == "MIT"
    assert kimi._spdx_from_raw_json({"license": {"spdx_id": "noassertion"}}) is None
    assert kimi._spdx_from_raw_json({"license": {"spdx_id": "Other"}}) is None


# ---------------------------------------------------------------------------
# Failure-mode prompt content
# ---------------------------------------------------------------------------


def test_failure_mode_definitions_included_in_prompt() -> None:
    """Known aliases (hallucinat/slopsquat) must appear somewhere in the prompt."""
    prompt = kimi.SYSTEM_PROMPT
    lower = prompt.lower()
    # Alias stems from data/failure_modes/*.yml
    assert "hallucinat" in lower, "expected 'hallucinat' stem (fabrication alias) in prompt"
    assert "slopsquat" in lower, "expected 'slopsquat' stem (supply_chain_attack alias) in prompt"
    # All 11 canonical ids appear verbatim
    for fm_id in (
        "fabrication",
        "obsolescence",
        "dependency_blindness",
        "logic_error",
        "security_vulnerability",
        "scope_creep",
        "context_pollution",
        "supply_chain_attack",
        "cascading_failure",
        "incomplete_execution",
        "test_manipulation",
    ):
        assert fm_id in prompt, f"expected canonical id {fm_id!r} in prompt"


def test_failure_modes_explicit_empty_encouragement() -> None:
    """Prompt must tell the LLM that [] is preferred over guessing."""
    prompt = kimi.SYSTEM_PROMPT.lower()
    # "empty list" phrasing with a preference/strong-preferred cue
    assert "empty list" in prompt or "return an empty list" in prompt
    assert "guess" in prompt, "expected guidance about guessing (should NOT guess)"
    # The specific carve-out for general-purpose agents
    assert "general-purpose" in prompt


def test_failure_mode_reference_enumerates_all_eleven_ids() -> None:
    """The hardcoded FAILURE_MODE_DEFINITIONS must cover the canonical enum exactly."""
    from pipeline.models import FailureModeId

    enum_ids = {m.value for m in FailureModeId}
    assert len(enum_ids) == 11, f"expected 11 canonical FailureModeIds, got {len(enum_ids)}"
    assert set(kimi.FAILURE_MODE_DEFINITIONS) == enum_ids, (
        "FAILURE_MODE_DEFINITIONS drifted from pipeline.models.FailureModeId"
    )


# ---------------------------------------------------------------------------
# License pre-seed: end-to-end via extract_tool (with mocked client)
# ---------------------------------------------------------------------------


def _fake_tool_args(license_spdx: str = "Apache-2.0") -> dict[str, Any]:
    """Build a minimal JSON payload conforming to ToolExtraction."""
    def cf(value: Any, confidence: float = 0.9) -> dict[str, Any]:
        return {"value": value, "confidence": confidence, "evidence": []}

    return {
        "proposed_id": cf("acme-supervisor"),
        "name": cf("ACME Supervisor"),
        "tagline": cf("Supervises ACME agents."),
        "description": cf("A tool for supervising AI coding agents."),
        "repository_url": cf("https://github.com/acme/supervisor"),
        "license_spdx": cf(license_spdx),
        "control_paradigm": cf("detection", 0.6),
        "temporal_phase": cf("post_generation", 0.6),
        "autonomy_level": cf(None, 0.2),
        "addresses_failure_modes": cf([], 0.5),
        "locus_of_control": cf([], 0.5),
        "inclusion_rationale": cf("Supervision-adjacent."),
        "overall_confidence": 0.7,
    }


def _mock_client_returning(args: dict[str, Any]) -> MagicMock:
    """Build a MagicMock OpenAI client whose tool-call response yields ``args``."""
    import json as _json

    client = MagicMock()
    choice = MagicMock()
    tool_call = MagicMock()
    tool_call.function = MagicMock()
    tool_call.function.name = "record_tool"
    tool_call.function.arguments = _json.dumps(args)
    choice.message = MagicMock()
    choice.message.tool_calls = [tool_call]
    choice.message.content = ""
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create.return_value = response
    return client


def test_extract_tool_passes_preseed_prompt_to_kimi() -> None:
    """When raw_json carries a license, the system message must contain it."""
    client = _mock_client_returning(_fake_tool_args("Apache-2.0"))
    row = {
        "source_url": "https://github.com/acme/supervisor",
        "raw_json": {"license": {"spdx_id": "Apache-2.0"}},
        "readme": "A minimal README.",
    }
    result = kimi.extract_tool(row, client=client)
    assert isinstance(result, ToolExtraction)
    # Inspect the messages that were forwarded to Kimi.
    kwargs = client.chat.completions.create.call_args.kwargs
    messages = kwargs["messages"]
    system_msg = next(m for m in messages if m["role"] == "system")
    assert "Apache-2.0" in system_msg["content"]
    assert "GitHub API license field" in system_msg["content"]


def test_extract_tool_logs_discrepancy_when_kimi_disagrees(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If Kimi returns a different SPDX than the pre-seed, keep Kimi's value + warn."""
    client = _mock_client_returning(_fake_tool_args("MIT"))  # Kimi says MIT
    row = {
        "source_url": "https://github.com/acme/supervisor",
        "raw_json": {"license": {"spdx_id": "Apache-2.0"}},  # GitHub says Apache-2.0
        "readme": "...",
    }
    with caplog.at_level(logging.WARNING, logger="pipeline.extract.kimi"):
        result = kimi.extract_tool(row, client=client)
    assert result.license_spdx.value == "MIT", "Kimi's value must be preserved"
    assert any(
        "license discrepancy" in rec.message.lower() for rec in caplog.records
    ), "expected discrepancy warning in logs"


def test_extract_tool_no_preseed_when_raw_json_absent() -> None:
    """Candidate without raw_json + unreachable DB -> plain SYSTEM_PROMPT."""
    client = _mock_client_returning(_fake_tool_args("MIT"))
    row = {
        "source_url": "https://github.com/acme/other",
        "readme": "plain README",
    }
    # Make the DB fallback return nothing (simulating an unreachable DB or
    # a missing raw_search_results row) by patching _github_license_spdx_from_row's
    # DB branch via a None-returning helper. Here we just patch the inner
    # function to short-circuit cleanly.
    with patch.object(kimi, "_github_license_spdx_from_row", return_value=None):
        kimi.extract_tool(row, client=client)
    kwargs = client.chat.completions.create.call_args.kwargs
    system_msg = next(m for m in kwargs["messages"] if m["role"] == "system")
    assert system_msg["content"] == kimi.SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Regression guards
# ---------------------------------------------------------------------------


def test_system_prompt_still_lists_core_vocabularies() -> None:
    """Don't accidentally delete the vocabulary block while editing the prompt."""
    for vocab in (
        "ControlParadigm",
        "TemporalPhase",
        "AutonomyLevel",
        "FailureModeId",
        "LocusOfControl",
    ):
        assert vocab in kimi.SYSTEM_PROMPT, f"{vocab} missing from SYSTEM_PROMPT"


def test_schema_description_mentions_empty_preferred() -> None:
    """The Pydantic field description must itself guide the LLM."""
    from pipeline.extract.schemas import ToolExtraction

    fields = ToolExtraction.model_fields
    afm_desc = fields["addresses_failure_modes"].description or ""
    assert "empty" in afm_desc.lower()
    assert "preferred" in afm_desc.lower() or "strictly" in afm_desc.lower()
    # Synonym anchor words
    assert "hallucination" in afm_desc.lower()
    assert "slopsquatting" in afm_desc.lower()


def test_schema_license_description_mentions_preseed() -> None:
    from pipeline.extract.schemas import ToolExtraction

    fields = ToolExtraction.model_fields
    lic_desc = fields["license_spdx"].description or ""
    assert "pre-seed" in lic_desc.lower() or "preseed" in lic_desc.lower()
    assert "0.95" in lic_desc or "github" in lic_desc.lower()
