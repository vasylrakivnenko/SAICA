"""Tests for the Incident and Recipe node types.

These lock in the Pydantic-model contract and the cross-node invariants
for the two kinds introduced alongside the first 18 incident YAMLs and
10 recipe YAMLs. Together they cover:

* Minimal / typical Incident and Recipe construction
* Field-validation failure modes (enum, min_length, extra='forbid',
  pattern, max_length tagline)
* Every real YAML under ``data/incidents/`` and ``data/recipes/``
  parses cleanly via the registered model in ``NODE_MODELS``
* Cross-node invariants: every FailureMode / paper / tool id an
  Incident or Recipe cites resolves to a node in the corpus
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from pipeline.models import (
    NODE_MODELS,
    EvidenceTier,
    FailureModeId,
    HarmClass,
    Incident,
    IncidentReproducibility,
    Recipe,
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
        return _coerce(yaml.safe_load(f))


def _minimal_incident(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "test-incident-1",
        "title": "Test incident",
        "description": "Test description.",
        "incident_date": "2025-01-01",
        "harm_class": "user_reported",
        "reproducibility": "anecdotal",
        "exhibited_failure_modes": ["fabrication"],
        "source_urls": ["https://example.com/incident"],
    }
    base.update(overrides)
    return base


def _minimal_recipe(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "test-recipe-1",
        "name": "Test recipe",
        "description": "Test description.",
        "targets_failure_modes": ["fabrication"],
        "stack": ["aider", "semgrep"],
        "evidence_tier": "anecdotal",
    }
    base.update(overrides)
    return base


# --- Model registration ---------------------------------------------------


def test_incident_and_recipe_registered_in_node_models() -> None:
    """NODE_MODELS must expose both new kinds so the validator, manifest
    generator, and schema generator all pick them up automatically.
    """
    assert NODE_MODELS["incidents"] is Incident
    assert NODE_MODELS["recipes"] is Recipe


# --- Minimal construction -------------------------------------------------


def test_minimal_incident_parses() -> None:
    inc = Incident.model_validate(_minimal_incident())
    assert inc.id == "test-incident-1"
    assert inc.harm_class is HarmClass.USER_REPORTED
    assert inc.reproducibility is IncidentReproducibility.ANECDOTAL
    assert inc.exhibited_failure_modes == [FailureModeId.FABRICATION]
    # defaults
    assert inc.documented_by == []
    assert inc.mitigated_by == []
    assert inc.affected_systems == []


def test_minimal_recipe_parses() -> None:
    rec = Recipe.model_validate(_minimal_recipe())
    assert rec.id == "test-recipe-1"
    assert rec.evidence_tier is EvidenceTier.ANECDOTAL
    assert rec.stack == ["aider", "semgrep"]
    assert rec.targets_failure_modes == [FailureModeId.FABRICATION]


# --- Field-level validation failures --------------------------------------


def test_incident_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc:
        Incident.model_validate(_minimal_incident(unexpected="nope"))
    assert "unexpected" in str(exc.value)


def test_incident_requires_at_least_one_failure_mode() -> None:
    with pytest.raises(ValidationError):
        Incident.model_validate(_minimal_incident(exhibited_failure_modes=[]))


def test_incident_requires_at_least_one_source_url() -> None:
    with pytest.raises(ValidationError):
        Incident.model_validate(_minimal_incident(source_urls=[]))


def test_incident_rejects_unknown_failure_mode() -> None:
    with pytest.raises(ValidationError):
        Incident.model_validate(
            _minimal_incident(exhibited_failure_modes=["not_a_real_mode"])
        )


def test_incident_rejects_unknown_harm_class() -> None:
    with pytest.raises(ValidationError):
        Incident.model_validate(_minimal_incident(harm_class="cosmic"))


def test_incident_enforces_tagline_max_length() -> None:
    too_long = "x" * 201
    with pytest.raises(ValidationError):
        Incident.model_validate(_minimal_incident(tagline=too_long))


def test_recipe_requires_at_least_two_tools_in_stack() -> None:
    with pytest.raises(ValidationError):
        Recipe.model_validate(_minimal_recipe(stack=["aider"]))


def test_recipe_rejects_unknown_evidence_tier() -> None:
    with pytest.raises(ValidationError):
        Recipe.model_validate(_minimal_recipe(evidence_tier="speculative"))


def test_recipe_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc:
        Recipe.model_validate(_minimal_recipe(magic="bean"))
    assert "magic" in str(exc.value)


# --- Real corpus parses cleanly -------------------------------------------


@pytest.mark.parametrize(
    "kind",
    ["incidents", "recipes"],
)
def test_all_real_yamls_parse(kind: str) -> None:
    subdir = DATA / kind
    assert subdir.exists(), f"expected data/{kind}/ to exist"
    files = sorted(subdir.glob("*.yml"))
    assert files, f"expected at least one YAML under data/{kind}/"
    model = NODE_MODELS[kind]
    for path in files:
        with path.open() as f:
            raw = _coerce(yaml.safe_load(f))
        model.model_validate(raw)


# --- Corpus-scale cross-node invariants -----------------------------------


def _corpus_ids(kind: str) -> set[str]:
    subdir = DATA / kind
    out: set[str] = set()
    for p in subdir.glob("*.yml"):
        with p.open() as f:
            data = yaml.safe_load(f)
        out.add(data["id"])
    return out


def test_every_incident_mitigated_by_tool_exists() -> None:
    tool_ids = _corpus_ids("tools")
    for p in sorted((DATA / "incidents").glob("*.yml")):
        data = yaml.safe_load(p.read_text())
        for tid in data.get("mitigated_by", []) or []:
            assert tid in tool_ids, (
                f"{p.name}: mitigated_by references missing tool '{tid}'"
            )


def test_every_incident_documented_by_paper_exists() -> None:
    paper_ids = _corpus_ids("papers")
    for p in sorted((DATA / "incidents").glob("*.yml")):
        data = yaml.safe_load(p.read_text())
        for pid in data.get("documented_by", []) or []:
            assert pid in paper_ids, (
                f"{p.name}: documented_by references missing paper '{pid}'"
            )


def test_every_recipe_stack_tool_exists() -> None:
    tool_ids = _corpus_ids("tools")
    for p in sorted((DATA / "recipes").glob("*.yml")):
        data = yaml.safe_load(p.read_text())
        stack = data.get("stack", []) or []
        assert len(stack) >= 2, f"{p.name}: stack must have >=2 tools"
        for tid in stack:
            assert tid in tool_ids, (
                f"{p.name}: stack references missing tool '{tid}'"
            )


def test_every_recipe_target_failure_mode_is_known() -> None:
    known = {m.value for m in FailureModeId}
    for p in sorted((DATA / "recipes").glob("*.yml")):
        data = yaml.safe_load(p.read_text())
        for fm in data.get("targets_failure_modes", []) or []:
            assert fm in known, (
                f"{p.name}: targets unknown FailureMode '{fm}'"
            )


def test_incident_corpus_has_harm_class_coverage() -> None:
    """Sanity check — the 18 incidents cover at least three harm classes so
    the distribution is informative rather than single-tone.
    """
    classes: set[str] = set()
    for p in (DATA / "incidents").glob("*.yml"):
        data = yaml.safe_load(p.read_text())
        classes.add(data["harm_class"])
    assert len(classes) >= 3, (
        f"incident corpus only uses {classes!r}; expected >=3 distinct harm_class values"
    )
