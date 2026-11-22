"""Tests for ``pipeline.maturity.evidence`` (what SAICA-Bench measured).

The bench files are rebuilt by other jobs, so most tests feed odd or
missing input and expect "not measured", never an exception.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.maturity.evidence import (
    DEFAULT_FLOOR,
    Evidence,
    failure_mode_of,
    measured_view,
    read_evidence,
    recommendable_modes,
)

RESULTS = {
    "generated": "2026-11-20",
    "modes": [
        {
            "id": "fabrication",
            "rows": [
                {"key": "pyright", "tool": "pyright", "kg_id": "pyright", "j": 0.853},
                {"key": "mypy", "tool": "mypy", "kg_id": "mypy", "j": 0.725},
                {
                    "key": "mypy_untyped",
                    "tool": "mypy, untyped",
                    "kg_id": "mypy",
                    "j": 0.773,
                },
                {"key": "plain", "tool": "a model, asked directly", "j": 0.93},
            ],
        },
        {
            "id": "security",
            "rows": [{"kg_id": "semgrep", "j": 0.026}, {"kg_id": "bandit", "j": -0.07}],
        },
        {
            "id": "test-manipulation",
            "rows": [
                {"kg_id": "promptfoo", "tool": "promptfoo llm-rubric", "j": 0.862}
            ],
        },
        {"id": "logic_error", "rows": [{"kg_id": "pyright", "j": 0.003}]},
    ],
}
KIT = {
    "floor": 0.25,
    "modes": [
        {"id": "security", "fm": "security_vulnerability"},
        {"id": "test-manipulation", "fm": "test_manipulation"},
    ],
}


@pytest.fixture
def evidence(tmp_path: Path) -> Evidence:
    (tmp_path / "results.json").write_text(json.dumps(RESULTS))
    (tmp_path / "kit.json").write_text(json.dumps(KIT))
    return read_evidence(tmp_path / "results.json", tmp_path / "kit.json")


def test_best_j_per_tool_and_mode(evidence: Evidence) -> None:
    assert evidence.floor == 0.25
    assert evidence.generated == "2026-11-20"
    assert evidence.measured("pyright") == {"fabrication": 0.853, "logic_error": 0.003}
    assert evidence.measured("mypy") == {"fabrication": 0.773}  # best of two rows
    assert evidence.label("mypy", "fabrication") == "mypy, untyped"
    assert evidence.measured("semgrep") == {"security_vulnerability": 0.026}
    assert evidence.measured("promptfoo") == {"test_manipulation": 0.862}
    assert evidence.measured("never-run") == {}
    assert evidence.below_floor("pyright") == {"logic_error": 0.003}
    assert evidence.at_or_above_floor("pyright") == {"fabrication": 0.853}
    assert evidence.unmapped_modes == ()


def test_mode_ids_map_without_the_kit_file(tmp_path: Path) -> None:
    (tmp_path / "results.json").write_text(json.dumps(RESULTS))
    ev = read_evidence(tmp_path / "results.json", tmp_path / "no-kit.json")
    assert ev.floor == DEFAULT_FLOOR
    assert "security_vulnerability" in ev.measured("bandit")
    assert "test_manipulation" in ev.measured("promptfoo")
    assert failure_mode_of({"id": "supply_chain"}) == "supply_chain_attack"
    assert failure_mode_of({"id": "x", "fm": "obsolescence"}) == "obsolescence"
    assert failure_mode_of({"id": "brand-new-mode"}) is None
    assert failure_mode_of("not a dict") is None


def test_unknown_mode_with_catalogue_rows_is_reported_not_dropped(
    tmp_path: Path,
) -> None:
    doc = {"modes": [{"id": "brand-new-mode", "rows": [{"kg_id": "ruff", "j": 0.1}]}]}
    (tmp_path / "results.json").write_text(json.dumps(doc))
    ev = read_evidence(tmp_path / "results.json", tmp_path / "kit.json")
    assert ev.unmapped_modes == ("brand-new-mode",)
    assert ev.measured("ruff") == {}


@pytest.mark.parametrize(
    "content",
    [
        None,  # file missing
        "not json",
        "[]",
        "{}",
        '{"modes": null}',
        '{"modes": [null, 3, {"rows": null}, {"id": "fabrication"}]}',
        '{"modes": [{"id": "fabrication", "rows": [null, 1, {}, {"kg_id": 5, "j": 1},'
        ' {"kg_id": "a"}, {"kg_id": "a", "j": null}, {"kg_id": "a", "j": "0.9"},'
        ' {"kg_id": "a", "j": true}, {"kg_id": "", "j": 0.5}]}]}',
        '{"floor": "high", "modes": []}',
    ],
)
def test_odd_or_missing_input_means_not_measured(
    tmp_path: Path, content: str | None
) -> None:
    path = tmp_path / "results.json"
    if content is not None:
        path.write_text(content)
    ev = read_evidence(path, tmp_path / "kit.json")
    assert ev.measured("a") == {}
    assert ev.floor == DEFAULT_FLOOR
    assert recommendable_modes(
        {"id": "a", "addresses_failure_modes": ["fabrication"]}, ev
    ) == ["fabrication"]


def test_floor_can_come_from_either_file(tmp_path: Path) -> None:
    (tmp_path / "results.json").write_text(json.dumps({"floor": 0.4, "modes": []}))
    (tmp_path / "kit.json").write_text(json.dumps({"floor": 0.25}))
    assert read_evidence(tmp_path / "results.json", tmp_path / "kit.json").floor == 0.4
    (tmp_path / "results.json").write_text(json.dumps({"modes": []}))
    assert read_evidence(tmp_path / "results.json", tmp_path / "kit.json").floor == 0.25


def test_recommendable_modes_drop_what_measured_below_the_floor(
    evidence: Evidence,
) -> None:
    pyright = {
        "id": "pyright",
        "addresses_failure_modes": ["logic_error", "fabrication", "obsolescence"],
    }
    # logic_error measured J 0.003 → out; fabrication 0.853 → in; obsolescence not measured → in (a claim).
    assert recommendable_modes(pyright, evidence) == ["fabrication", "obsolescence"]
    bandit = {"id": "bandit", "addresses_failure_modes": ["security_vulnerability"]}
    assert recommendable_modes(bandit, evidence) == []
    untested = {"id": "never-run", "addresses_failure_modes": ["scope_creep"]}
    assert recommendable_modes(untested, evidence) == ["scope_creep"]
    assert recommendable_modes({"id": "x"}, evidence) == []
    assert (
        recommendable_modes({"id": "x", "addresses_failure_modes": None}, evidence)
        == []
    )


def test_archived_tool_is_recommended_for_nothing(evidence: Evidence) -> None:
    tool = {
        "id": "never-run",
        "addresses_failure_modes": ["scope_creep"],
        "archived": True,
    }
    assert recommendable_modes(tool, evidence) == []


def test_measured_view_is_a_copy_and_idempotent(evidence: Evidence) -> None:
    tool = {
        "id": "pyright",
        "name": "Pyright",
        "addresses_failure_modes": ["logic_error", "fabrication"],
    }
    view = measured_view(tool, evidence)
    assert view["addresses_failure_modes"] == ["fabrication"]
    assert tool["addresses_failure_modes"] == ["logic_error", "fabrication"]
    assert measured_view(view, evidence) == view
    assert view["name"] == "Pyright"


def test_repository_files_load_without_error() -> None:
    """Whatever state the live bench files are in, reading them works and
    every measured mode is a failure-mode id."""
    from pipeline.models import FAILURE_MODE_IDS

    ev = read_evidence()
    assert 0.0 < ev.floor < 1.0
    for tool_id in ev.measured_tools:
        assert set(ev.measured(tool_id)) <= set(FAILURE_MODE_IDS)
