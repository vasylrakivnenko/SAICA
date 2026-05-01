"""Tests for the optional :class:`~pipeline.models.Provenance` sub-model
and its integration with :class:`~pipeline.models.Tool`.

Design intent:

* Existing YAMLs under ``data/tools/`` have no ``provenance:`` block; they
  MUST keep validating. The field is optional.
* New graduations produce a block with ``source`` + ``ingested_at`` at
  minimum. ``reviewer`` / ``review_date`` stay null until a post-merge
  hook fills them in.
* ``extra='forbid'`` catches typos in reviewer automation; confidence
  fields are range-checked.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from pipeline.models import Provenance, Tool


# ---------------------------------------------------------------------------
# Fixtures — a minimally-valid Tool payload we can reuse across cases.
# ---------------------------------------------------------------------------


def _base_tool_kwargs() -> dict:
    return {
        "id": "example-tool",
        "name": "Example",
        "description": "An example tool used in tests.",
        "first_released": dt.date(2024, 1, 1),
        "maturity_status": "experimental",
        "license": "MIT",
        "control_paradigm": "prevention",
        "temporal_phase": "pre_generation",
        "autonomy_level": "fully_autonomous",
        "addresses_failure_modes": ["fabrication"],
    }


# ---------------------------------------------------------------------------
# Tool-level integration
# ---------------------------------------------------------------------------


def test_tool_accepts_omitted_provenance() -> None:
    """Existing 38 YAMLs stay valid: Tool with no `provenance:` parses."""
    tool = Tool.model_validate(_base_tool_kwargs())
    assert tool.provenance is None


def test_tool_accepts_full_provenance() -> None:
    """A newly-graduated tool with all provenance fields populated validates."""
    kwargs = _base_tool_kwargs()
    kwargs["provenance"] = {
        "source": "pipeline-v0.1",
        "ingested_at": "2026-04-23",
        "extractor_model": "Kimi-K2.5",
        "extractor_confidence": 0.78,
        "rerank_score": 0.96,
        "candidate_id": 107,
        "reviewer": "octocat",
        "review_date": "2026-04-24",
    }
    tool = Tool.model_validate(kwargs)
    assert tool.provenance is not None
    assert tool.provenance.source == "pipeline-v0.1"
    assert tool.provenance.candidate_id == 107
    assert tool.provenance.extractor_confidence == 0.78
    assert tool.provenance.reviewer == "octocat"
    assert tool.provenance.ingested_at == dt.date(2026, 4, 23)


def test_tool_accepts_minimal_provenance_from_graduation() -> None:
    """At graduation time, only `source` + `ingested_at` are mandatory;
    reviewer/review_date stay null until the post-merge hook fires."""
    kwargs = _base_tool_kwargs()
    kwargs["provenance"] = {
        "source": "pipeline-v0.1",
        "ingested_at": "2026-04-23",
    }
    tool = Tool.model_validate(kwargs)
    assert tool.provenance is not None
    assert tool.provenance.reviewer is None
    assert tool.provenance.review_date is None


# ---------------------------------------------------------------------------
# Provenance-level invariants
# ---------------------------------------------------------------------------


def test_provenance_rejects_extra_fields() -> None:
    """extra='forbid' catches reviewer-automation typos like `revewer:`."""
    with pytest.raises(ValidationError) as excinfo:
        Provenance.model_validate(
            {
                "source": "pipeline-v0.1",
                "ingested_at": "2026-04-23",
                "revewer": "octocat",  # typo
            }
        )
    # Pydantic surfaces "Extra inputs are not permitted" for extra fields
    # under extra='forbid'.
    assert (
        "extra" in str(excinfo.value).lower()
        or "not permitted" in str(excinfo.value).lower()
    )


def test_provenance_requires_source_and_ingested_at() -> None:
    """`source` and `ingested_at` are mandatory."""
    with pytest.raises(ValidationError):
        Provenance.model_validate({"ingested_at": "2026-04-23"})  # no source
    with pytest.raises(ValidationError):
        Provenance.model_validate({"source": "manual"})  # no ingested_at


@pytest.mark.parametrize("field", ["extractor_confidence", "rerank_score"])
def test_provenance_confidence_range_0_to_1(field: str) -> None:
    """Both confidence fields are hard-clamped to [0.0, 1.0]."""
    base = {"source": "pipeline-v0.1", "ingested_at": "2026-04-23"}

    # Valid endpoints: 0, 1, and something in between.
    Provenance.model_validate({**base, field: 0.0})
    Provenance.model_validate({**base, field: 1.0})
    Provenance.model_validate({**base, field: 0.5})

    # Out of range -> ValidationError.
    with pytest.raises(ValidationError):
        Provenance.model_validate({**base, field: -0.01})
    with pytest.raises(ValidationError):
        Provenance.model_validate({**base, field: 1.01})


# ---------------------------------------------------------------------------
# Integration with the graduation CLI
# ---------------------------------------------------------------------------


def test_graduate_builds_valid_provenance_block() -> None:
    """The graduation CLI's helper emits a dict that parses into Provenance."""
    from pipeline.cli.graduate import _build_provenance_block

    row = {
        "id": 107,
        "source_url": "https://github.com/acme/widget",
        "nlp_tags": {"rerank_score": 0.96},
    }
    payload = {"overall_confidence": 0.78}
    block = _build_provenance_block(row, payload, today=dt.date(2026, 4, 23))

    # Round-trips through Pydantic without errors.
    prov = Provenance.model_validate(dict(block))
    assert prov.source == "pipeline-v0.1"
    assert prov.ingested_at == dt.date(2026, 4, 23)
    assert prov.extractor_model == "Kimi-K2.5"
    assert prov.extractor_confidence == 0.78
    assert prov.rerank_score == 0.96
    assert prov.candidate_id == 107
    assert prov.reviewer is None  # populated post-merge
    assert prov.review_date is None
