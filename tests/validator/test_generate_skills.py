"""Tests for ``validator.generate_skills``.

These exercise the orchestrator's payload shape, the per-FM ordering /
incident-selection invariants, the rendered MD anchor strings, the
no-dangling-reference invariants (every cited incident_id resolves to
a YAML, every cited tool_id resolves to a YAML), the ``--check`` mode
round-trip, and what the review of 2026-11-21 asked for: no tool listed
for a mode it measured below the floor (H5 / F1), "Real incident" only for
a dated event (E3), no retracted node cited (E1), no date from the clock
(E11).
"""

from __future__ import annotations

import glob
import inspect
import re
from pathlib import Path

import pytest
import yaml

from pipeline.maturity.evidence import load_evidence
from pipeline.models import FAILURE_MODE_IDS
from pipeline.shared.priorities import all_priorities
from validator import _recommend
from validator import generate_skills as gen
from validator.generate_skills import (
    REPO_ROOT,
    _check_outputs,
    _render_plugin_skill,
    _write_outputs,
    build_payload,
    render_markdown,
)

INCIDENT_DIR = REPO_ROOT / "data" / "incidents"
TOOLS_DIR = REPO_ROOT / "data" / "tools"


def _ids_on_disk(directory: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in glob.glob(str(directory / "*.yml")):
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        if isinstance(doc, dict) and doc.get("id"):
            out[str(doc["id"])] = doc
    return out


@pytest.fixture(scope="module")
def payload() -> dict:
    """Build payload once per test module."""
    return build_payload(as_of="2026-04-23")


def test_payload_covers_all_eleven_failure_modes_in_priority_desc(
    payload: dict,
) -> None:
    """All 11 FMs present, ordered by priority descending."""
    fm_ids = [fm["id"] for fm in payload["failure_modes"]]
    assert set(fm_ids) == set(FAILURE_MODE_IDS)
    assert len(fm_ids) == 11

    # Priority-descending: each FM's priority must be >= the next.
    priorities = [fm["priority"] for fm in payload["failure_modes"]]
    for a, b in zip(priorities, priorities[1:]):
        assert a >= b, f"FMs not in priority-desc order: {fm_ids} → {priorities}"

    # And the leading FM is the highest in all_priorities() (sanity).
    expected_first = next(iter(all_priorities()))
    assert fm_ids[0] == expected_first


def test_at_most_two_tools_per_failure_mode(payload: dict) -> None:
    """Up to 2 tools per mode. A mode may have none: when its only tagged
    tools measured below the floor, listing nothing is the right answer."""
    for fm in payload["failure_modes"]:
        assert len(fm["supervisors"]) <= 2
        for rec in fm["supervisors"]:
            assert fm["id"] in rec["addresses_failure_modes"]
    assert any(fm["supervisors"] for fm in payload["failure_modes"])


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
    assert "## Tool stacks from the catalogue — three sizes" in md
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


# ---------------------------------------------------------------------------
# H5 / F1: the measured floor and the wording
# ---------------------------------------------------------------------------


def test_no_tool_is_listed_for_a_mode_it_measured_below_the_floor(
    payload: dict,
) -> None:
    evidence = load_evidence()
    for fm in payload["failure_modes"]:
        for rec in fm["supervisors"]:
            assert fm["id"] not in evidence.below_floor(
                rec["tool_id"]
            ), f"{rec['tool_id']} is listed for {fm['id']}"
    for level, block in payload["tiers"].items():
        for rec in block["tools"]:
            failed = set(evidence.below_floor(rec["tool_id"]))
            assert not (failed & set(rec["addresses_failure_modes"])), (
                level,
                rec["tool_id"],
            )


def test_measured_tools_lead_their_mode(payload: dict) -> None:
    evidence = load_evidence()
    for fm in payload["failure_modes"]:
        flags = [
            fm["id"] in evidence.at_or_above_floor(r["tool_id"])
            for r in fm["supervisors"]
        ]
        assert flags == sorted(
            flags, reverse=True
        ), f"{fm['id']}: tag-only before measured"


@pytest.mark.parametrize("render", [render_markdown, _render_plugin_skill])
def test_skill_has_none_of_the_retired_claims(payload: dict, render) -> None:
    text = render(payload)
    for pattern in (
        r"\bcovers? \d+ of \d+",
        r"covers all 11",
        r"\bMECE\b",
        r"single best tool",
        r"responsible default",
        r"\breliab",
        r"Same picks the MCP server",
    ):
        assert not re.search(pattern, text, re.IGNORECASE), f"found {pattern!r}"
    assert "A tag is a claim, not a measurement." in text
    assert "https://saica.ai/tool-coverage/" in text


def test_heuristics_do_not_name_a_tool_that_failed_on_that_mode() -> None:
    evidence = load_evidence()
    tools = _recommend.catalogue_tools()
    for fm_id, text in gen._PRE_ACTION_HEURISTICS.items():
        lowered = text.lower()
        for tool_id, tool in tools.items():
            if fm_id not in evidence.below_floor(tool_id):
                continue
            for name in {tool_id, str(tool.get("name") or tool_id).lower()}:
                assert not re.search(
                    rf"\b{re.escape(name.lower())}\b", lowered
                ), f"heuristic for {fm_id} names {name}, measured below the floor on it"


# ---------------------------------------------------------------------------
# E3 / E1: what may be called a real incident
# ---------------------------------------------------------------------------


def test_real_incident_label_only_for_dated_events(payload: dict) -> None:
    incidents = _ids_on_disk(INCIDENT_DIR)
    md = render_markdown(payload)
    labelled = re.findall(
        r"\*\*(Real incident|Measured in a study|Documented case):\*\* .*\[`([a-z0-9-]+)`\]",
        md,
    )
    assert labelled, "no example cited at all — generator broken?"
    for label, incident_id in labelled:
        kind = str(incidents[incident_id].get("kind") or "")
        assert (
            label == gen._KIND_LABEL[kind]
        ), f"{incident_id} is kind {kind!r}, shown as {label!r}"
        assert kind in ("event", "study", "")


def test_hypotheticals_and_patterns_are_never_the_example(payload: dict) -> None:
    incidents = _ids_on_disk(INCIDENT_DIR)
    for fm in payload["failure_modes"]:
        if fm["incident"]:
            assert incidents[fm["incident"]["id"]].get("kind") not in (
                "hypothetical",
                "pattern",
            )


def test_pick_prefers_event_over_study_over_unlabelled() -> None:
    base = {"exhibited_failure_modes": ["fabrication"], "reproducibility": "confirmed"}
    nodes = [
        {**base, "id": "a-study", "kind": "study", "incident_date": "2026-01-01"},
        {
            **base,
            "id": "an-event",
            "kind": "event",
            "incident_date": "2024-01-01",
            "reproducibility": "plausible",
        },
        {**base, "id": "unlabelled", "incident_date": "2026-06-01"},
        {
            **base,
            "id": "a-hypothetical",
            "kind": "hypothetical",
            "incident_date": "2026-09-01",
        },
        {**base, "id": "a-pattern", "kind": "pattern", "incident_date": "2026-09-01"},
    ]
    assert gen._pick_headline_incident("fabrication", nodes)["id"] == "an-event"
    assert (
        gen._pick_headline_incident("fabrication", nodes[:1] + nodes[2:])["id"]
        == "a-study"
    )
    assert gen._pick_headline_incident("fabrication", nodes[2:])["id"] == "unlabelled"
    assert gen._pick_headline_incident("fabrication", nodes[3:]) is None
    assert gen._pick_headline_incident("logic_error", nodes) is None


def test_every_cited_incident_resolves_to_a_yaml(payload: dict) -> None:
    """No SKILLS.md cites an incident_id that isn't on disk."""
    md = render_markdown(payload)
    # Incident citations look like ``[`some-incident-id`]`` (NOT followed
    # by ``(`` — that pattern is the markdown link to a tool YAML).
    cited_ids = set(re.findall(r"\[`([a-z0-9-]+)`\](?!\()", md))
    assert cited_ids, "no incidents cited at all — generator broken?"

    missing = cited_ids - set(_ids_on_disk(INCIDENT_DIR))
    assert not missing, f"cited but not on disk: {sorted(missing)}"


def test_no_retracted_node_is_cited(payload: dict) -> None:
    """Review E1: the skill quoted retracted incidents as "Real incident"."""
    tombstones = REPO_ROOT / "data" / "TOMBSTONES.yml"
    if not tombstones.exists():
        pytest.skip("no TOMBSTONES.yml")
    removed = {
        str(e.get("id"))
        for e in (yaml.safe_load(tombstones.read_text()) or {}).get("tombstones") or []
        if isinstance(e, dict)
    }
    text = render_markdown(payload) + _render_plugin_skill(payload)
    cited = set(re.findall(r"\[`([a-z0-9-]+)`\]", text))
    assert not (cited & removed), f"retracted nodes cited: {sorted(cited & removed)}"


def test_every_cited_tool_id_resolves_to_a_yaml(payload: dict) -> None:
    """Every supervisor referenced by tool_id has a tool YAML."""
    md = render_markdown(payload)
    # Supervisor lines render `[tool_id](data/tools/tool_id.yml)`.
    cited_tool_ids = set(re.findall(r"\[`([a-z0-9-]+)`\]\(data/tools/", md))
    assert cited_tool_ids, "no tools cited — generator broken?"

    missing = cited_tool_ids - set(_ids_on_disk(TOOLS_DIR))
    assert not missing, f"cited but not on disk: {sorted(missing)}"


def test_installed_skill_links_to_the_site_not_to_repo_paths(payload: dict) -> None:
    """A SKILL.md lives in ``.claude/skills/`` or a plugin cache, where
    ``data/tools/<id>.yml`` leads nowhere."""
    skill = _render_plugin_skill(payload)
    assert "](data/tools/" not in skill
    linked = set(re.findall(r"\]\(https://saica\.ai/tools/([a-z0-9-]+)/\)", skill))
    assert linked, "no tool links in the skill"
    assert not (linked - set(_ids_on_disk(TOOLS_DIR)))
    assert skill.startswith("---\nname: saica-supervise\n")


# ---------------------------------------------------------------------------
# E11: no clock; --check
# ---------------------------------------------------------------------------


def test_output_does_not_depend_on_todays_date() -> None:
    source = inspect.getsource(gen)
    assert ".today(" not in source and ".now(" not in source
    first, second = build_payload(), build_payload()
    assert first == second
    assert first["as_of"] == _recommend.kg_stamp()[1]
    assert f"(manifest of {first['as_of']})" in render_markdown(first)


def test_check_mode_round_trip(tmp_path: Path, payload: dict) -> None:
    """Writing then --check-ing in the same out-dir returns 0."""
    md_path = _write_outputs(payload, tmp_path)
    assert md_path.exists()
    assert (tmp_path / "SKILL.md").read_text() == _render_plugin_skill(payload)
    assert _check_outputs(payload, tmp_path) == 0


def test_check_mode_detects_drift(tmp_path: Path, payload: dict) -> None:
    """Tampering with either file makes --check return 1."""
    md_path = _write_outputs(payload, tmp_path)
    md_path.write_text("tampered\n", encoding="utf-8")
    assert _check_outputs(payload, tmp_path) == 1
    _write_outputs(payload, tmp_path)
    (tmp_path / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    assert _check_outputs(payload, tmp_path) == 1


def test_out_dir_run_leaves_the_repository_files_alone(tmp_path: Path) -> None:
    tracked = [gen.DEFAULT_MD_PATH, gen._PLUGIN_SKILL_PATH, gen._PUBLIC_SKILL_PATH]
    before = [p.read_bytes() for p in tracked]
    assert gen.main(["--out-dir", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "SKILLS.md").exists()
    assert (tmp_path / "out" / "SKILL.md").exists()
    assert [p.read_bytes() for p in tracked] == before
    assert gen.main(["--check", "--out-dir", str(tmp_path / "out")]) == 0


def test_pre_action_heuristics_render_for_every_fm(payload: dict) -> None:
    """Every FM block must have a pre-action heuristic rendered.

    Heuristics are the most important content in SKILLS.md — guard
    against silently dropping one when an FM is added.

    Slices the doc to the per-FM section before splitting so the stack
    sub-headings (also ``### `` + backtick) don't get mistaken for FM blocks.
    """
    md = render_markdown(payload)
    fm_section_marker = "## Failure modes — what to watch for and what to do"
    fm_section_start = md.find(fm_section_marker)
    assert fm_section_start >= 0, "skill is missing the per-FM section header"
    fm_section = md[fm_section_start:]
    # Stop at the next H2 so we don't bleed into the working-agreement section.
    next_h2 = fm_section.find("\n## ", 1)
    if next_h2 >= 0:
        fm_section = fm_section[:next_h2]

    blocks = fm_section.split("### `")
    # First chunk is the section header; the rest each begin with `<fm_id>`.
    fm_blocks = blocks[1:]
    assert len(fm_blocks) == 11
    for block in fm_blocks:
        assert "**Pre-action heuristic for an agent:**" in block
        # And the blockquote line directly follows.
        assert "\n> " in block, f"FM block missing heuristic blockquote:\n{block[:200]}"
