"""Tests for the 3 FailureModes added when extending the canonical enum
from 8 to 11 (``cascading_failure``, ``incomplete_execution``,
``test_manipulation``).

These tests lock in the extension so future edits can't silently regress
the enum size, rename an id, or let a new YAML drift out of sync with
``pipeline.models.FailureModeId``.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml

from pipeline.extract import kimi
from pipeline.models import FailureMode, FailureModeId


REPO = Path(__file__).resolve().parent.parent
FM_DIR = REPO / "data" / "failure_modes"

NEW_MODE_IDS = (
    "cascading_failure",
    "incomplete_execution",
    "test_manipulation",
)

# Expected full set post-extension (alphabetical for determinism).
EXPECTED_ENUM_VALUES = {
    "cascading_failure",
    "context_pollution",
    "dependency_blindness",
    "fabrication",
    "incomplete_execution",
    "logic_error",
    "obsolescence",
    "scope_creep",
    "security_vulnerability",
    "supply_chain_attack",
    "test_manipulation",
}


def _coerce(v: Any) -> Any:
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _coerce(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_coerce(x) for x in v]
    return v


def test_enum_has_eleven_modes() -> None:
    """FailureModeId must carry exactly 11 members, matching the expected set."""
    values = {m.value for m in FailureModeId}
    assert len(FailureModeId) == 11, f"expected 11 FailureModeId members, got {len(FailureModeId)}"
    assert values == EXPECTED_ENUM_VALUES, (
        f"FailureModeId drifted from expected set. "
        f"missing={EXPECTED_ENUM_VALUES - values}, "
        f"extra={values - EXPECTED_ENUM_VALUES}"
    )


@pytest.mark.parametrize("mode_id", NEW_MODE_IDS)
def test_yamls_load_into_pydantic_model(mode_id: str) -> None:
    """Each new YAML parses cleanly as a FailureMode node and round-trips its id."""
    path = FM_DIR / f"{mode_id}.yml"
    assert path.exists(), f"expected {path} to exist"
    with path.open() as fh:
        raw = _coerce(yaml.safe_load(fh))
    mode = FailureMode.model_validate(raw)
    assert mode.id == mode_id
    # Sanity: prior_work and detection_signals are non-empty (enforced by the
    # model, but assert explicitly so a future loosening of those constraints
    # still leaves this test failing loudly for the new modes).
    assert len(mode.prior_work) >= 1
    assert len(mode.detection_signals) >= 1


def test_prompt_reference_enumerates_all_eleven() -> None:
    """The Kimi FAILURE_MODE_DEFINITIONS block and rendered system prompt must
    include every new id alongside the original 8.
    """
    defs = kimi.FAILURE_MODE_DEFINITIONS
    assert set(defs) == EXPECTED_ENUM_VALUES, (
        f"FAILURE_MODE_DEFINITIONS keys drifted from canonical 11. "
        f"missing={EXPECTED_ENUM_VALUES - set(defs)}, "
        f"extra={set(defs) - EXPECTED_ENUM_VALUES}"
    )
    # The rendered system prompt must cite each id verbatim so the extractor
    # LLM can use it without guessing.
    prompt = kimi.SYSTEM_PROMPT
    for fm_id in EXPECTED_ENUM_VALUES:
        assert fm_id in prompt, f"expected canonical id {fm_id!r} in rendered system prompt"
