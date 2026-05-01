"""Smoke tests for the SAICA-KG MCP server.

These exercise the *pure-function* layer (no MCP transport spin-up). The
server module is also imported to confirm it has no import-time errors.
"""

from __future__ import annotations

import pytest

from pipeline.mcp._schemas_compat import ToolRecord
from pipeline.mcp.lookup import saica_lookup
from pipeline.mcp.recommender import (
    ALL_FAILURE_MODES,
    CODING_AGENT_IDS,
    DEFAULT_LEVEL,
    LEVELS,
    RECOMMENDATION_BLOCKLIST,
    recommend,
)


# ---------------------------------------------------------------------------
# saica_lookup
# ---------------------------------------------------------------------------


def test_lookup_semgrep_returns_full_tool_record() -> None:
    rec = saica_lookup("semgrep")
    assert isinstance(rec, ToolRecord)
    assert rec.id == "semgrep"
    assert rec.name  # non-empty
    assert rec.description  # non-empty
    assert rec.control_paradigm == "detection"
    # Surfaces should include at least one pipeline-friendly entry.
    assert rec.integration_surfaces, "integration_surfaces must not be empty"
    assert "cli" in rec.integration_surfaces or "ci_app" in rec.integration_surfaces
    assert rec.url == "/tools/semgrep"
    assert rec.addresses_failure_modes


def test_lookup_unknown_tool_raises_clear_error() -> None:
    with pytest.raises(ValueError) as ei:
        saica_lookup("nonexistent-tool-foo")
    msg = str(ei.value)
    assert "nonexistent-tool-foo" in msg


# ---------------------------------------------------------------------------
# saica_recommend — targeted mode
# ---------------------------------------------------------------------------


def test_recommend_targeted_returns_per_fm_lists() -> None:
    out = recommend(failure_modes=["scope_creep"], agent_kind=None)
    assert out["mode"] == "targeted"
    assert "scope_creep" in out["by_failure_mode"]
    recs = out["by_failure_mode"]["scope_creep"]
    assert recs, "should return non-empty recommendations for a populated FM"
    for r in recs:
        assert r["tool_id"]
        assert r["url"].startswith("/tools/")
        # Every recommendation must actually declare coverage for the FM.
        assert "scope_creep" in r["addresses_failure_modes"]


def test_recommend_targeted_unknown_fm_raises() -> None:
    with pytest.raises(ValueError) as ei:
        recommend(failure_modes=["bogus_fm"], agent_kind=None)
    assert "bogus_fm" in str(ei.value)


def test_recommend_targeted_filters_coding_agent_peers() -> None:
    """Asking as cursor must never return a coding-agent peer."""
    out = recommend(failure_modes=["scope_creep"], agent_kind="cursor")
    for r in out["by_failure_mode"]["scope_creep"]:
        assert (
            r["tool_id"] not in CODING_AGENT_IDS
        ), f"coding-agent peer {r['tool_id']} leaked into recs for cursor"
        assert r["tool_id"] != "cursor", "must not recommend the asker itself"


# ---------------------------------------------------------------------------
# saica_recommend — three-tier coverage modes
# ---------------------------------------------------------------------------


def test_recommend_minimum_returns_one_tool() -> None:
    out = recommend(level="minimum", agent_kind=None)
    assert out["mode"] == "minimum"
    assert out["level"] == "minimum"
    assert len(out["tools"]) == 1
    assert out["tools"][0][
        "addresses_failure_modes"
    ], "picked tool must address something"


def test_recommend_optimal_returns_at_most_three_tools() -> None:
    out = recommend(level="optimal", agent_kind=None)
    assert out["mode"] == "optimal"
    assert out["level"] == "optimal"
    assert 1 <= len(out["tools"]) <= 3


def test_recommend_full_covers_all_failure_modes() -> None:
    out = recommend(level="full", agent_kind=None)
    assert out["mode"] == "full"
    assert out[
        "coverage_complete"
    ], f"full did not cover everything; missing: {out['uncovered_failure_modes']}"
    assert out["uncovered_failure_modes"] == []


def test_recommend_full_no_pad() -> None:
    """Unlike the prior covering view, full no longer pads beyond cover."""
    out = recommend(level="full", agent_kind=None)
    n = len(out["tools"])
    # Realistic minimum cover for SAICA's KG is 4-6 tools today; we pin
    # only that it's strictly less than the old pad target of 11.
    assert n < 11, f"full should not pad to 11; got {n}"


def test_recommend_default_is_optimal() -> None:
    out = recommend(agent_kind=None)
    assert out["level"] == "optimal" == DEFAULT_LEVEL


def test_recommend_unknown_level_raises() -> None:
    with pytest.raises(ValueError) as ei:
        recommend(level="bogus", agent_kind=None)
    assert "bogus" in str(ei.value)


def test_recommend_both_args_raises() -> None:
    with pytest.raises(ValueError):
        recommend(level="optimal", failure_modes=["scope_creep"], agent_kind=None)


def test_levels_constant_is_complete() -> None:
    assert set(LEVELS) == {"minimum", "optimal", "full"}


def test_full_suite_filters_coding_agents_for_known_asker() -> None:
    out = recommend(level="full", agent_kind="claude-code")
    all_ids = {r["tool_id"] for r in out["tools"]}
    leaked = all_ids & CODING_AGENT_IDS
    assert not leaked, f"coding-agent peers leaked: {leaked}"
    assert "claude-code" not in all_ids


def test_recommend_blocks_blocklisted_tools_across_levels() -> None:
    for level in ("minimum", "optimal", "full"):
        out = recommend(level=level, agent_kind=None)
        all_ids = {r["tool_id"] for r in out["tools"]}
        leaked = all_ids & RECOMMENDATION_BLOCKLIST
        assert not leaked, f"blocklisted tool leaked at level={level}: {leaked}"


def test_summary_is_human_readable_per_level() -> None:
    for level in ("minimum", "optimal", "full"):
        out = recommend(level=level, agent_kind="claude-code")
        assert "failure modes" in out["summary"]
        assert str(len(out["tools"])) in out["summary"]


# ---------------------------------------------------------------------------
# Recommender invariants
# ---------------------------------------------------------------------------


def test_all_failure_modes_size() -> None:
    assert len(ALL_FAILURE_MODES) == 11


def test_coding_agent_filter_list_is_sane() -> None:
    """Spot-check that the filter list has the expected anchors and no obvious
    over-reach."""
    assert "cursor" in CODING_AGENT_IDS
    assert "claude-code" in CODING_AGENT_IDS
    assert "replit-agent" in CODING_AGENT_IDS
    # Things that are NOT coding-agent peers.
    assert "browser-use" not in CODING_AGENT_IDS
    assert "skyvern" not in CODING_AGENT_IDS
    assert "copilotkit" not in CODING_AGENT_IDS
    assert "playwright-mcp" not in CODING_AGENT_IDS
    assert "magic-mcp" not in CODING_AGENT_IDS
    assert "mcp-toolbox" not in CODING_AGENT_IDS
    assert "comfyui" not in CODING_AGENT_IDS  # blocklisted, not filter-listed


def test_blocklist_contains_comfyui() -> None:
    assert "comfyui" in RECOMMENDATION_BLOCKLIST


# ---------------------------------------------------------------------------
# Server module imports cleanly + tools are registered
# ---------------------------------------------------------------------------


def test_server_module_imports_and_registers_tools() -> None:
    from pipeline.mcp import server

    assert server.mcp is not None
    assert callable(server.saica_lookup)
    assert callable(server.saica_recommend)
    # Old tools must be gone from the module surface.
    assert not hasattr(server, "saica_preflight")
    assert not hasattr(server, "saica_audit_repo")


def test_server_lists_exactly_two_tools() -> None:
    """End-to-end: the FastMCP instance reports exactly the two tools we ship."""
    import asyncio

    from pipeline.mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "saica_lookup",
        "saica_recommend",
    }, f"expected exactly saica_lookup + saica_recommend, got {sorted(names)}"


def test_server_reads_agent_kind_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAICA_AGENT_KIND", "cursor")
    from pipeline.mcp.server import _agent_kind

    assert _agent_kind() == "cursor"
    monkeypatch.delenv("SAICA_AGENT_KIND", raising=False)
    assert _agent_kind() is None
