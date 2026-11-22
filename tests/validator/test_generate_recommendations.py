"""Tests for ``validator.generate_recommendations``.

The ranking itself is covered by ``pipeline/mcp/tests``. Here we check what
the published files promise (review 2026-11-21, H5 / F1):

* a tool is never listed for a mode where SAICA-Bench measured it below
  the floor, and measured tools come first within a mode;
* no sentence says "N tools cover X of 11" and nothing is called
  "reliability" or "trending";
* the output does not depend on today's date;
* payload shape, asker filter, blocklist, JSON round-trip, ``--check``.
"""

from __future__ import annotations

import inspect
import json
import re

import pytest

from pipeline.maturity.evidence import Evidence, load_evidence
from pipeline.mcp.recommender import (
    CODING_AGENT_IDS,
    LEVELS,
    RECOMMENDATION_BLOCKLIST,
)
from pipeline.models import FAILURE_MODE_IDS
from validator import _recommend
from validator import generate_recommendations as gen
from validator.generate_recommendations import build_payload, render_markdown


@pytest.fixture(scope="module")
def payload() -> dict:
    """Build the payload once per test module — it's a few hundred ms."""
    return build_payload(as_of="2026-04-30")


def _all_recs(payload: dict):
    """Yield ``(where, failure_mode or None, rec)`` for every listed tool."""
    for level, block in payload["agnostic"].items():
        for rec in block["tools"]:
            yield f"agnostic/{level}", None, rec
    for agent_id, levels in payload["by_agent"].items():
        for level, block in levels.items():
            for rec in block["tools"]:
                yield f"{agent_id}/{level}", None, rec
    for fm, recs in payload["by_failure_mode"].items():
        for rec in recs:
            yield f"by_failure_mode/{fm}", fm, rec


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_payload_top_level_keys(payload: dict) -> None:
    assert set(payload) == {
        "as_of",
        "kg_version",
        "bench",
        "not_listed",
        "popularity",
        "blocklist",
        "priorities",
        "priorities_label",
        "by_agent",
        "agnostic",
        "by_failure_mode",
    }
    assert payload["as_of"] == "2026-04-30"
    assert isinstance(payload["priorities"], dict)
    assert "scope_creep" in payload["priorities"]
    assert 0 < payload["bench"]["floor"] < 1


def test_payload_has_every_coding_agent_at_three_levels(payload: dict) -> None:
    assert set(payload["by_agent"].keys()) == set(CODING_AGENT_IDS)
    for agent_id, levels in payload["by_agent"].items():
        assert set(levels.keys()) == set(LEVELS)
        for level, block in levels.items():
            assert block["agent_kind"] == agent_id
            assert block["level"] == level
            assert "tools" in block
            assert "covered_failure_modes" in block
            assert "uncovered_failure_modes" in block


def test_payload_has_agnostic_block_at_three_levels(payload: dict) -> None:
    agnostic = payload["agnostic"]
    assert set(agnostic.keys()) == set(LEVELS)
    for level, block in agnostic.items():
        assert block["agent_kind"] is None
        assert block["level"] == level
        assert "tools" in block


def test_payload_by_failure_mode_covers_all_eleven(payload: dict) -> None:
    assert set(payload["by_failure_mode"].keys()) == set(FAILURE_MODE_IDS)
    for fm, recs in payload["by_failure_mode"].items():
        assert isinstance(recs, list)
        assert len(recs) <= gen.PER_MODE
        for rec in recs:
            assert fm in (rec.get("addresses_failure_modes") or [])


def test_recommendations_json_round_trip(payload: dict) -> None:
    """The payload must serialize and re-parse without loss."""
    raw = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    reparsed = json.loads(raw)
    assert reparsed == payload


# ---------------------------------------------------------------------------
# H5 / F1: the measured floor
# ---------------------------------------------------------------------------


def test_no_tool_is_listed_for_a_mode_it_measured_below_the_floor(
    payload: dict,
) -> None:
    evidence = load_evidence()
    for where, fm, rec in _all_recs(payload):
        failed = evidence.below_floor(rec["tool_id"])
        listed = set(rec["addresses_failure_modes"]) | ({fm} if fm else set())
        assert not (listed & set(failed)), (
            f"{where}: {rec['tool_id']} is listed for {sorted(listed & set(failed))},"
            f" measured {failed}"
        )
        for mode, j in rec["measured_j"].items():
            assert j >= evidence.floor and mode in rec["addresses_failure_modes"]


def test_every_removed_pair_is_reported(payload: dict) -> None:
    evidence = load_evidence()
    tools = _recommend.catalogue_tools()
    expected = {
        (tool_id, fm)
        for tool_id, tool in tools.items()
        for fm in evidence.below_floor(tool_id)
        if fm in (tool.get("addresses_failure_modes") or [])
    }
    reported = {
        (row["tool_id"], row["failure_mode"])
        for row in payload["not_listed"]
        if row["reason"] == "measured below floor"
    }
    assert reported == expected


def _fake_evidence(best: dict) -> Evidence:
    return Evidence(
        floor=0.25,
        generated="2026-01-01",
        source="test",
        best={
            tool: {fm: {"j": j, "label": tool} for fm, j in modes.items()}
            for tool, modes in best.items()
        },
    )


def test_floor_and_order_follow_the_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Change what was "measured" and the lists follow: a tool measured
    below the floor leaves the mode, the best measured tool leads it."""
    tools = _recommend.catalogue_tools()
    mode = "security_vulnerability"
    tagged = sorted(
        t
        for t, d in tools.items()
        if mode in (d.get("addresses_failure_modes") or [])
        and d.get("archived") is not True
    )
    assert len(tagged) >= 4, "need a mode with several tagged tools"
    baseline = build_payload(as_of="2026-04-30")
    loser = baseline["by_failure_mode"][mode][0]["tool_id"]
    winner = next(t for t in reversed(tagged) if t != loser)

    monkeypatch.setattr(
        _recommend,
        "load_evidence",
        lambda: _fake_evidence({loser: {mode: 0.01}, winner: {mode: 0.9}}),
    )
    changed = build_payload(as_of="2026-04-30")
    ids = [r["tool_id"] for r in changed["by_failure_mode"][mode]]
    assert ids[0] == winner
    assert changed["by_failure_mode"][mode][0]["measured_j"] == {mode: 0.9}
    assert loser not in ids
    for _, fm, rec in _all_recs(changed):
        if rec["tool_id"] == loser:
            assert mode not in rec["addresses_failure_modes"] and fm != mode
    assert {
        "tool_id": loser,
        "failure_mode": mode,
        "reason": "measured below floor",
        "j": 0.01,
    } in changed["not_listed"]


def test_recommender_index_is_restored_after_the_build() -> None:
    from pipeline.mcp import recommender

    before = recommender._load_tools()
    build_payload(as_of="2026-04-30")
    assert recommender._load_tools() is before


def test_assert_floor_stops_a_payload_that_breaks_the_rule() -> None:
    evidence = _fake_evidence({"alpha": {"logic_error": 0.02}})
    good = {
        "by_failure_mode": {
            "fabrication": [
                {"tool_id": "alpha", "addresses_failure_modes": ["fabrication"]}
            ]
        }
    }
    _recommend.assert_floor(good, evidence, {"alpha": {}})
    for bad in (
        {
            "by_failure_mode": {
                "logic_error": [{"tool_id": "alpha", "addresses_failure_modes": []}]
            }
        },
        {
            "agnostic": {
                "full": {
                    "tools": [
                        {"tool_id": "alpha", "addresses_failure_modes": ["logic_error"]}
                    ]
                }
            }
        },
    ):
        with pytest.raises(RuntimeError, match="below the floor"):
            _recommend.assert_floor(bad, evidence, {"alpha": {}})
    with pytest.raises(RuntimeError, match="archived"):
        _recommend.assert_floor(good, evidence, {"alpha": {"archived": True}})


# ---------------------------------------------------------------------------
# H5 / F1: wording
# ---------------------------------------------------------------------------

_RETIRED = (
    r"\bcovers? \d+ of \d+",
    r"\bcover all 11\b",
    r"11-failure-mode coverage",
    r"\bMECE\b",
    # "reliability" may appear only as the name of the function in the
    # code, until pipeline/shared/priorities.py renames it.
    r"(?<!priorities\.)\breliab",
    r"\btrending\b(?! repository)",
    "\U0001f525",
    r"best starter",
    r"best responsible kit",
)


def test_markdown_has_none_of_the_retired_claims(payload: dict) -> None:
    md = render_markdown(payload)
    for pattern in _RETIRED:
        assert not re.search(pattern, md, re.IGNORECASE), f"found {pattern!r}"


def test_summaries_count_tags_as_tags(payload: dict) -> None:
    for level, block in payload["agnostic"].items():
        summary = block["summary"]
        assert "tags name" in summary and "claim" in summary, summary
        assert not re.search(r"\bcovers? \d+ of \d+", summary)
        assert block["measured_pairs"] <= block["tagged_pairs"]
    blob = json.dumps(payload)
    assert '"trending"' not in blob and "trending_count" not in blob


def test_popularity_is_described_from_the_code_not_asserted(payload: dict) -> None:
    pop = payload["popularity"]
    assert pop["name"] == "popularity"
    assert set(pop["status_adjustment"]) == set(_recommend.STATUSES)
    md = render_markdown(payload)
    assert "**popularity**" in md
    for tool_id in pop["tools_with_other_terms"]:
        assert f"`{tool_id}`" in md, "a term beyond stars and status must be named"


# ---------------------------------------------------------------------------
# E11: no clock
# ---------------------------------------------------------------------------


def test_output_does_not_depend_on_todays_date() -> None:
    for module in (gen, _recommend):
        source = inspect.getsource(module)
        assert ".today(" not in source and ".now(" not in source, module.__name__
    first, second = build_payload(), build_payload()
    assert first == second
    assert first["as_of"] == _recommend.kg_stamp()[1]


def test_kg_stamp_reads_the_manifest(tmp_path) -> None:
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(
        json.dumps({"kg_version": "2031.02", "generated_at": "2031-02-03T04:05:06Z"})
    )
    assert _recommend.kg_stamp(manifest) == ("2031.02", "2031-02-03")
    assert _recommend.kg_stamp(tmp_path / "missing.json") == ("unknown", "unknown")
    manifest.write_text("[]")
    assert _recommend.kg_stamp(manifest) == ("unknown", "unknown")


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_asker_filter_regression_across_levels(payload: dict) -> None:
    """A coding agent must never appear in its own recs at any level."""
    for agent_id, levels in payload["by_agent"].items():
        for level, block in levels.items():
            all_ids = {r["tool_id"] for r in block["tools"]}
            assert (
                agent_id not in all_ids
            ), f"{agent_id}/{level} recommended itself; ids: {sorted(all_ids)}"
            peers = (CODING_AGENT_IDS - {agent_id}) & all_ids
            assert (
                not peers
            ), f"{agent_id}/{level} got coding-agent peers: {sorted(peers)}"


def test_blocklist_applied_to_agnostic_across_levels(payload: dict) -> None:
    """Even with no asker, the blocklist must apply at every level."""
    for level, block in payload["agnostic"].items():
        ids = {r["tool_id"] for r in block["tools"]}
        assert not (ids & RECOMMENDATION_BLOCKLIST), (
            f"blocklisted tool leaked into agnostic/{level}: "
            f"{sorted(ids & RECOMMENDATION_BLOCKLIST)}"
        )
        assert "comfyui" not in ids


def test_printed_blocklist_names_only_live_nodes(payload: dict) -> None:
    """A block-list id that is no longer a node (comfyui has a tombstone) is
    still honoured by the recommender but is not printed."""
    live = set(_recommend.catalogue_tools())
    assert set(payload["blocklist"]) <= live
    md = render_markdown(payload)
    for removed in RECOMMENDATION_BLOCKLIST - live:
        assert f"`{removed}`" not in md
    if not payload["blocklist"]:
        assert "Never listed, whatever their tags" not in md


def test_blocklist_applied_to_failure_mode_view(payload: dict) -> None:
    for fm, recs in payload["by_failure_mode"].items():
        ids = {r["tool_id"] for r in recs}
        assert "comfyui" not in ids, f"comfyui leaked into FM view {fm!r}"


# ---------------------------------------------------------------------------
# Rendering and --check
# ---------------------------------------------------------------------------


def test_render_markdown_anchors(payload: dict) -> None:
    md = render_markdown(payload)
    assert md.startswith("# SAICA-KG — Tool suggestions from the catalogue")
    assert "A tag is a claim, not a measurement." in md
    assert "2026-04-30" in md
    assert "## Three stacks by tag coverage" in md
    assert "**One tool (`minimum`)**" in md
    assert "**Three tools (`optimal`)**" in md
    assert "(`full`)**" in md
    assert "## By coding agent" in md
    assert "### Fabrication" in md
    assert "### Security vulnerability" in md
    assert "## Tagged, measured, not listed" in md
    assert "## Method" in md
    assert "data/tools/" in md
    assert "likelihood × impact" in md
    assert "https://saica.ai/tool-coverage/" in md


def test_identical_per_agent_blocks_are_said_once(payload: dict) -> None:
    md = render_markdown(payload)
    same = all(
        gen._same_picks(levels[level], payload["agnostic"][level])
        for levels in payload["by_agent"].values()
        for level in LEVELS
    )
    if same:
        assert "If you use **" not in md
        assert "The picks are the same for all 16 coding agents" in md
    else:
        assert "If you use **" in md


def test_render_markdown_is_pure(payload: dict) -> None:
    """Two calls with the same payload must produce identical output."""
    a = render_markdown(payload)
    b = render_markdown(payload)
    assert a == b


def test_check_mode_round_trip(tmp_path, payload: dict) -> None:
    """Writing then --check-ing in the same out-dir must succeed."""
    from validator.generate_recommendations import _check_outputs, _write_outputs

    md_path, json_path = _write_outputs(payload, tmp_path)
    assert md_path.exists() and json_path.exists()
    assert _check_outputs(payload, tmp_path) == 0


def test_check_mode_detects_drift(tmp_path, payload: dict) -> None:
    """Modifying an output must make --check exit non-zero."""
    from validator.generate_recommendations import _check_outputs, _write_outputs

    md_path, _ = _write_outputs(payload, tmp_path)
    md_path.write_text("tampered\n", encoding="utf-8")
    assert _check_outputs(payload, tmp_path) == 1


def test_out_dir_run_leaves_the_repository_files_alone(tmp_path) -> None:
    before = (gen.DEFAULT_MD_PATH.read_bytes(), gen.DEFAULT_JSON_PATH.read_bytes())
    assert gen.main(["--out-dir", str(tmp_path / "nested" / "dir")]) == 0
    assert (tmp_path / "nested" / "dir" / "RECOMMENDATIONS.md").exists()
    assert (
        gen.DEFAULT_MD_PATH.read_bytes(),
        gen.DEFAULT_JSON_PATH.read_bytes(),
    ) == before
    assert gen.main(["--check", "--out-dir", str(tmp_path / "nested" / "dir")]) == 0
