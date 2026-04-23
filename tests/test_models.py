"""Smoke tests: real YAML under ``data/`` parses cleanly into the canonical
Pydantic models.

One representative node per kind, plus one "parse everything" coverage test
to guarantee models stay in sync with on-disk data as it grows.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml

from pipeline.models import (
    NODE_MODELS,
    Crosswalk,
    FailureMode,
    Paper,
    Taxonomy,
    Tool,
)


REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"


def _coerce(v: Any) -> Any:
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _coerce(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_coerce(x) for x in v]
    return v


def _load(kind: str, filename: str) -> dict[str, Any]:
    with (DATA / kind / filename).open() as f:
        raw = yaml.safe_load(f)
    return _coerce(raw)


def test_parse_sample_tool() -> None:
    tool = Tool.model_validate(_load("tools", "claude-code.yml"))
    assert tool.id == "claude-code"
    assert tool.control_paradigm.value == "prevention"
    assert "scope_creep" in [fm.value for fm in tool.addresses_failure_modes]


def test_parse_sample_failure_mode() -> None:
    mode = FailureMode.model_validate(_load("failure_modes", "fabrication.yml"))
    assert mode.id == "fabrication"
    assert len(mode.prior_work) >= 1
    assert len(mode.detection_signals) >= 1


def test_parse_sample_paper() -> None:
    paper = Paper.model_validate(
        _load("papers", "cihon-stein-2025-autonomy-scoring.yml")
    )
    assert paper.year == 2025
    assert len(paper.authors) >= 1


def test_parse_sample_taxonomy() -> None:
    tax = Taxonomy.model_validate(_load("taxonomies", "mast.yml"))
    assert tax.id == "mast"
    assert len(tax.categories) >= 1


def test_parse_sample_crosswalk() -> None:
    cw = Crosswalk.model_validate(_load("crosswalks", "mast-to-saica.yml"))
    assert cw.saica_axis.value == "failure_mode"
    assert len(cw.mappings) >= 1


@pytest.mark.parametrize("kind,model", list(NODE_MODELS.items()))
def test_all_real_yamls_parse(kind: str, model: type) -> None:
    """Every YAML under ``data/<kind>/`` must parse cleanly. This catches
    drift between the canonical models and the living corpus.
    """
    subdir = DATA / kind
    if not subdir.exists():
        pytest.skip(f"data/{kind} does not exist")
    files = sorted(subdir.glob("*.yml"))
    assert files, f"expected at least one YAML under data/{kind}/"
    for path in files:
        with path.open() as f:
            raw = _coerce(yaml.safe_load(f))
        model.model_validate(raw)
