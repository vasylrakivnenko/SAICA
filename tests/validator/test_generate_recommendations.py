"""Tests for ``validator.generate_recommendations``.

These tests exercise the orchestrator in isolation: the underlying
recommender ranking is already covered by ``pipeline/mcp/tests``, so here
we just verify the payload shape, the asker-filter regression invariants,
the blocklist invariant, the JSON round-trip, and that the rendered MD
contains the expected anchor strings.
"""

from __future__ import annotations

import json

import pytest

from pipeline.mcp.recommender import (
    ALL_FAILURE_MODES,
    CODING_AGENT_IDS,
    LEVELS,
    RECOMMENDATION_BLOCKLIST,
)
from validator.generate_recommendations import (
    build_payload,
    render_markdown,
)


@pytest.fixture(scope="module")
def payload() -> dict:
    """Build the payload once per test module — it's a few hundred ms."""
    return build_payload(today="2026-04-30")


def test_payload_top_level_keys(payload: dict) -> None:
    expected = {
        "generated_at",
        "kg_version",
        "trending_count",
        "trending_boost",
        "blocklist",
        "priorities",
        "by_agent",
        "agnostic",
        "by_failure_mode",
    }
    assert expected.issubset(payload.keys())
    assert payload["generated_at"] == "2026-04-30"
    assert isinstance(payload["trending_boost"], float)
    assert payload["trending_count"] >= 0
    assert isinstance(payload["priorities"], dict)
    assert "scope_creep" in payload["priorities"]


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
    assert set(payload["by_failure_mode"].keys()) == set(ALL_FAILURE_MODES)
    for fm, recs in payload["by_failure_mode"].items():
        assert isinstance(recs, list)
        # Default per_fm is 3 in the recommender; allow 0 if no tools claim it.
        assert len(recs) <= 3
        for rec in recs:
            assert fm in (rec.get("addresses_failure_modes") or [])


def test_recommendations_json_round_trip(payload: dict) -> None:
    """The payload must serialize and re-parse without loss."""
    raw = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    reparsed = json.loads(raw)
    assert reparsed == payload


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


def test_blocklist_applied_to_failure_mode_view(payload: dict) -> None:
    for fm, recs in payload["by_failure_mode"].items():
        ids = {r["tool_id"] for r in recs}
        assert "comfyui" not in ids, f"comfyui leaked into FM view {fm!r}"


def test_render_markdown_anchors(payload: dict) -> None:
    md = render_markdown(payload)
    # Title and date.
    assert md.startswith("# SAICA-KG — Supervision recommendations")
    assert "2026-04-30" in md
    # At least two specific agent headers.
    assert "If you use **Cursor**" in md
    assert "If you use **Claude Code**" in md
    # All three tier labels for at least one agent.
    assert "**Minimum (1 tool — best starter)**" in md
    assert "**Optimal (3 tools — best responsible kit)**" in md
    assert "**Full / MECE" in md
    # At least one FM heading (capitalized form).
    assert "### Fabrication" in md
    assert "### Security vulnerability" in md
    # Methodology + a tool YAML link + priority table reference.
    assert "## Methodology" in md
    assert "data/tools/" in md
    assert "likelihood × impact" in md


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
