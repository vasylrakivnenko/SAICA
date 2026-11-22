"""File-consistency checks for ``recommendations.json`` (review H7).

These used to run through promptfoo's echo provider under the name
"behavioural gate". They test a generated file against the KG and the
benchmark results; no model is involved, so they are plain pytest.

Dropped on the way, because they could not fail: the blocklist check (its
only id is not in the KG), the peer-agent check (none of the 16 ids is in
the KG), "minimum has one tool" and "full is complete" (they restated how
the algorithm is built; the second is no longer true by design).

The first three tests check the checks on small payloads. The last three
read the repository's ``recommendations.json``. That file is generated
(``python -m validator.generate_recommendations``); if one of them fails,
regenerate the file before looking for a bug.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals import _assertions as checks
from pipeline import kg
from pipeline.maturity.evidence import load_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
REC_PATH = REPO_ROOT / "recommendations.json"

SAMPLE = {
    "agnostic": {
        "full": {
            "tools": [{"tool_id": "alpha", "addresses_failure_modes": ["fabrication"]}],
            "covered_failure_modes": ["fabrication"],
            "uncovered_failure_modes": ["logic_error"],
        }
    },
    "by_agent": {
        "cursor": {
            "minimum": {
                "tools": [
                    {"tool_id": "beta", "addresses_failure_modes": ["logic_error"]}
                ]
            }
        }
    },
    "by_failure_mode": {
        "logic_error": [
            {
                "tool_id": "beta",
                "addresses_failure_modes": ["logic_error", "fabrication"],
            }
        ],
        "fabrication": [{"tool_id": "alpha", "addresses_failure_modes": []}],
    },
    "priorities": {"fabrication": 1.0, "logic_error": 0.5},
    # Pairs the floor removed: reported, not listed, so never a violation.
    "not_listed": [{"tool_id": "gamma", "failure_mode": "fabrication", "j": 0.01}],
}
MODES = {"fabrication", "logic_error"}


def test_unknown_tool_ids_are_found_wherever_they_sit() -> None:
    assert checks.unknown_tool_ids(SAMPLE, {"alpha", "beta"}) == []
    missing = checks.unknown_tool_ids(SAMPLE, {"alpha"})
    assert missing == [
        "by_agent/cursor/minimum/tools: beta",
        "by_failure_mode/logic_error: beta",
    ]


def test_unknown_failure_modes_are_found_in_tags_keys_and_lists() -> None:
    assert checks.unknown_failure_modes(SAMPLE, MODES) == []
    bad = checks.unknown_failure_modes(SAMPLE, {"fabrication"})
    assert bad == [
        "/by_failure_mode: logic_error",
        "/priorities: logic_error",
        "agnostic/full/uncovered_failure_modes: logic_error",
        "by_agent/cursor/minimum/tools/addresses_failure_modes: logic_error",
        "by_failure_mode/logic_error/addresses_failure_modes: logic_error",
    ]


def test_below_floor_pairs_catch_tags_and_mode_sections_and_archived_tools() -> None:
    assert checks.below_floor_pairs(SAMPLE, {}) == []
    assert checks.below_floor_pairs(SAMPLE, {"beta": {"scope_creep": 0.0}}) == []
    # alpha sits in the fabrication section with an empty tag list: the
    # section alone makes it a listed pair.
    assert checks.below_floor_pairs(SAMPLE, {"alpha": {"fabrication": 0.01}}) == [
        "agnostic/full/tools: alpha for fabrication (J +0.01)",
        "by_failure_mode/fabrication: alpha for fabrication (J +0.01)",
    ]
    assert (
        checks.below_floor_pairs(
            SAMPLE, {"gamma": {"fabrication": 0.01}}, archived={"gamma"}
        )
        == []
    )
    assert checks.below_floor_pairs(SAMPLE, {}, archived={"beta"}) == [
        "by_agent/cursor/minimum/tools: beta is archived",
        "by_failure_mode/logic_error: beta is archived",
    ]


@pytest.fixture(scope="module")
def published() -> dict:
    return json.loads(REC_PATH.read_text(encoding="utf-8"))


def test_published_file_lists_only_tools_that_exist(published: dict) -> None:
    assert list(checks.iter_recommendations(published)), "the file lists no tool at all"
    assert checks.unknown_tool_ids(published, set(kg.load_tools())) == []


def test_published_file_uses_only_known_failure_modes(published: dict) -> None:
    assert checks.unknown_failure_modes(published, kg.failure_mode_ids()) == []


def test_published_file_lists_no_pair_measured_below_the_floor(published: dict) -> None:
    evidence = load_evidence()
    tools = kg.load_tools()
    below = {
        tool_id: evidence.below_floor(tool_id) for tool_id in evidence.measured_tools
    }
    archived = {
        tool_id for tool_id, tool in tools.items() if tool.get("archived") is True
    }
    assert checks.below_floor_pairs(published, below, archived) == [], (
        f"floor J {evidence.floor}: regenerate with "
        "`python -m validator.generate_recommendations`"
    )
