"""Tests for ``validator.generate_skills``.

These exercise the orchestrator's payload shape, the per-FM ordering /
incident-selection invariants, the rendered MD anchor strings, the
no-dangling-reference invariants (every cited incident_id resolves to
a YAML, every cited tool_id resolves to a YAML), and the ``--check``
mode round-trip.

The actual recommender ranking is covered in ``pipeline/mcp/tests`` and
priority logic in ``pipeline/shared/tests``; we only assert orchestrator
behaviour here.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import pytest
import yaml

from pipeline.mcp.recommender import ALL_FAILURE_MODES
from pipeline.shared.priorities import all_priorities
from validator.generate_skills import (
    REPO_ROOT,
    _check_outputs,
    _write_outputs,
    build_payload,
    render_markdown,
)

INCIDENT_DIR = REPO_ROOT / "data" / "incidents"
TOOLS_DIR = REPO_ROOT / "data" / "tools"


@pytest.fixture(scope="module")
def payload() -> dict:
    """Build payload once per test module."""
    return build_payload(today="2026-04-23")


def test_payload_covers_all_eleven_failure_modes_in_priority_desc(
    payload: dict,
) -> None:
    """All 11 FMs present, ordered by priority descending."""
    fm_ids = [fm["id"] for fm in payload["failure_modes"]]
    assert set(fm_ids) == set(ALL_FAILURE_MODES)
    assert len(fm_ids) == 11

    # Priority-descending: each FM's priority must be >= the next.
    priorities = [fm["priority"] for fm in payload["failure_modes"]]
    for a, b in zip(priorities, priorities[1:]):
        assert a >= b, f"FMs not in priority-desc order: {fm_ids} → {priorities}"

    # And the leading FM is the highest in all_priorities() (sanity).
    expected_first = next(iter(all_priorities()))
    assert fm_ids[0] == expected_first


def test_each_failure_mode_has_at_least_one_supervisor(payload: dict) -> None:
    """KG isn't empty: every FM gets at least one recommended supervisor."""
    for fm in payload["failure_modes"]:
        assert (
            len(fm["supervisors"]) >= 1
        ), f"{fm['id']} has no recommended supervisor — KG drift?"
        # ... and at most _TOP_SUPERVISORS_PER_FM (= 2).
        assert len(fm["supervisors"]) <= 2


def test_render_markdown_is_idempotent(payload: dict) -> None:
    """Two calls with identical payload yield byte-identical strings."""
    a = render_markdown(payload)
    b = render_markdown(payload)
    assert a == b


def test_render_markdown_anchors(payload: dict) -> None:
    """Required headings and section markers all present."""
    md = render_markdown(payload)

    # Title.
    assert md.startswith("# SAICA-KG — Agent skills file")

    # Top-level section markers.
    assert "## How this file is meant to be used" in md
    assert "## Failure modes — what to watch for and what to do" in md
    assert "## Cross-cutting working agreement" in md
    assert "## Where to learn more" in md
    assert "## Provenance" in md

    # At least 5 specific FM headers (snake_case ids in backticks).
    for fm_id in (
        "scope_creep",
        "fabrication",
        "security_vulnerability",
        "supply_chain_attack",
        "logic_error",
    ):
        assert f"### `{fm_id}` —" in md, f"missing FM header for {fm_id}"

    # Generated metadata.
    assert "2026-04-23" in md
    assert payload["kg_version"] in md


def test_every_cited_incident_resolves_to_a_yaml(payload: dict) -> None:
    """No SKILLS.md cites an incident_id that isn't on disk."""
    md = render_markdown(payload)
    # Incident citations look like ``[`some-incident-id`]`` (NOT followed
    # by ``(`` — that pattern is the markdown link to a tool YAML).
    cited_ids = set(re.findall(r"\[`([a-z0-9-]+)`\](?!\()", md))
    assert cited_ids, "no incidents cited at all — generator broken?"

    on_disk: set[str] = set()
    for path in glob.glob(str(INCIDENT_DIR / "*.yml")):
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        if isinstance(doc, dict) and doc.get("id"):
            on_disk.add(str(doc["id"]))

    missing = cited_ids - on_disk
    assert not missing, f"cited but not on disk: {sorted(missing)}"


def test_every_cited_tool_id_resolves_to_a_yaml(payload: dict) -> None:
    """Every supervisor referenced by tool_id has a tool YAML."""
    md = render_markdown(payload)
    # Supervisor lines render `[tool_id](data/tools/tool_id.yml)`.
    cited_tool_ids = set(re.findall(r"\[`([a-z0-9-]+)`\]\(data/tools/", md))
    assert cited_tool_ids, "no tools cited — generator broken?"

    on_disk: set[str] = set()
    for path in glob.glob(str(TOOLS_DIR / "*.yml")):
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        if isinstance(doc, dict) and doc.get("id"):
            on_disk.add(str(doc["id"]))

    missing = cited_tool_ids - on_disk
    assert not missing, f"cited but not on disk: {sorted(missing)}"


def test_check_mode_round_trip(tmp_path: Path, payload: dict) -> None:
    """Writing then --check-ing in the same out-dir returns 0."""
    md_path = _write_outputs(payload, tmp_path)
    assert md_path.exists()
    assert _check_outputs(payload, tmp_path) == 0


def test_check_mode_detects_drift(tmp_path: Path, payload: dict) -> None:
    """Tampering with the file makes --check return 1."""
    md_path = _write_outputs(payload, tmp_path)
    md_path.write_text("tampered\n", encoding="utf-8")
    assert _check_outputs(payload, tmp_path) == 1


def test_pre_action_heuristics_render_for_every_fm(payload: dict) -> None:
    """Every FM block must have a pre-action heuristic rendered.

    Heuristics are the most important content in SKILLS.md — guard
    against silently dropping one when an FM is added.
    """
    md = render_markdown(payload)
    blocks = md.split("### `")
    # First chunk is preamble; the rest each begin with `<fm_id>` ...
    fm_blocks = blocks[1:]
    assert len(fm_blocks) == 11
    for block in fm_blocks:
        assert "**Pre-action heuristic for an agent:**" in block
        # And the blockquote line directly follows.
        assert "\n> " in block, f"FM block missing heuristic blockquote:\n{block[:200]}"
