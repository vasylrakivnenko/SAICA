"""Tests for the MCP server's two tools (pure-function layer) and its module.

Everything runs on the fixture KG (:mod:`pipeline.shared.kg_fixture`) and
on a fixed set of "measured" results, so nothing here depends on the
catalog's current tools or on the benchmark's current numbers.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import kg
from pipeline.audit.schemas import ToolRecord
from pipeline.maturity import evidence as evidence_mod
from pipeline.maturity.evidence import Evidence
from pipeline.mcp import recommender
from pipeline.mcp.lookup import saica_lookup
from pipeline.mcp.recommender import (
    CODING_AGENT_IDS,
    DEFAULT_LEVEL,
    LEVELS,
    RECOMMENDATION_BLOCKLIST,
    all_failure_modes,
    recommend,
)
from pipeline.models import FAILURE_MODE_IDS
from pipeline.shared import priorities
from pipeline.shared.kg_fixture import default_tools, tool, write_kg

REPO_ROOT = Path(__file__).resolve().parents[3]


def _evidence(best: dict[str, dict[str, float]]) -> Evidence:
    return Evidence(
        floor=0.25,
        generated="2026-01-01",
        source="test",
        best={
            tool_id: {fm: {"j": j, "label": tool_id} for fm, j in modes.items()}
            for tool_id, modes in best.items()
        },
    )


# promptfoo passed on test_manipulation and failed on security; semgrep
# failed on security; nothing else was "measured".
MEASURED = {
    "promptfoo": {"test_manipulation": 0.86, "security_vulnerability": 0.02},
    "semgrep": {"security_vulnerability": 0.03},
}


@pytest.fixture(autouse=True)
def fixture_kg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(evidence_mod, "load_evidence", lambda: _evidence(MEASURED))
    with kg.use_data_dir(write_kg(tmp_path)):
        yield


# ---------------------------------------------------------------------------
# saica_lookup
# ---------------------------------------------------------------------------


def test_lookup_returns_the_validated_tool_record() -> None:
    rec = saica_lookup("semgrep")
    assert isinstance(rec, ToolRecord)
    assert (rec.id, rec.name, rec.url) == ("semgrep", "Semgrep", "/tools/semgrep")
    assert rec.control_paradigm == "detection"
    assert rec.integration_surfaces == ["cli", "ci_app", "library"]
    # The record shows the catalog's tags, untouched by the measured floor.
    assert rec.addresses_failure_modes == [
        "security_vulnerability",
        "supply_chain_attack",
    ]
    assert rec.stars == 12000 and rec.maturity_status == "stable"


def test_lookup_unknown_tool_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="nonexistent-tool-foo"):
        saica_lookup("nonexistent-tool-foo")


@pytest.mark.parametrize(
    "bad",
    [
        "../failure_modes/scope_creep",
        "../../docker-compose",
        "../../.github/workflows/tests",
        "/etc/passwd",
        "semgrep.yml",
        "semgrep/",
        "Semgrep",
        "sem grep",
        "semgrep\n",
        "-semgrep",
        "scope_creep",  # a failure mode, not a tool; underscore is not allowed
        "fabrication",  # well-formed, exists in the KG, but is not a tool
        "fixture-paper-2025",  # a paper node
        "",
        "a" * 101,
        None,
        7,
    ],
)
def test_lookup_accepts_only_well_formed_ids_of_existing_tools(bad) -> None:
    with pytest.raises(ValueError):
        saica_lookup(bad)


def test_lookup_never_touches_the_file_system_for_a_bad_id(tmp_path: Path) -> None:
    """A YAML file outside data/tools must not be readable through the tool."""
    secret = kg.default_data_dir().parent / "docker-compose.yml"
    secret.write_text("id: docker-compose\nname: leaked\n", encoding="utf-8")
    for attempt in ("../../docker-compose", "docker-compose"):
        with pytest.raises(ValueError) as excinfo:
            saica_lookup(attempt)
        assert "leaked" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# One list of failure modes
# ---------------------------------------------------------------------------


def test_mode_list_is_derived_from_the_data(tmp_path: Path) -> None:
    assert set(all_failure_modes()) == set(FAILURE_MODE_IDS)
    assert recommender.ALL_FAILURE_MODES == all_failure_modes()  # old name still works
    with kg.use_data_dir(
        write_kg(tmp_path / "two", failure_modes=("fabrication", "scope_creep"))
    ):
        assert all_failure_modes() == ("fabrication", "scope_creep")
        with pytest.raises(ValueError, match="logic_error"):
            recommend(failure_modes=["logic_error"])
        full = recommend(level="full")
        assert full["covered_failure_modes"] == ["fabrication", "scope_creep"]
        assert "2 of 2 failure modes" in full["summary"]


# ---------------------------------------------------------------------------
# saica_recommend — targeted mode
# ---------------------------------------------------------------------------


def test_recommend_targeted_returns_tagged_tools_per_mode() -> None:
    out = recommend(failure_modes=["scope_creep", "fabrication"], agent_kind=None)
    assert out["mode"] == "targeted"
    assert set(out["by_failure_mode"]) == {"scope_creep", "fabrication"}
    for fm, recs in out["by_failure_mode"].items():
        assert 1 <= len(recs) <= 3
        for r in recs:
            assert fm in r["addresses_failure_modes"]
            assert r["url"] == f"/tools/{r['tool_id']}"
            assert "trending" not in r
    # prevention / detection before recovery, then stars.
    assert [r["tool_id"] for r in out["by_failure_mode"]["scope_creep"]] == [
        "litellm",
        "daytona",
    ]


def test_recommend_targeted_unknown_fm_raises() -> None:
    with pytest.raises(ValueError, match="bogus_fm"):
        recommend(failure_modes=["bogus_fm"], agent_kind=None)


# ---------------------------------------------------------------------------
# The measured floor (kg_gate request 1; review H5)
# ---------------------------------------------------------------------------


def _pairs(payload: dict) -> set[tuple[str, str]]:
    """Every (tool, mode) pair a payload offers."""
    out: set[tuple[str, str]] = set()
    for rec in payload.get("tools", []):
        out |= {(rec["tool_id"], fm) for fm in rec["addresses_failure_modes"]}
    for fm, recs in payload.get("by_failure_mode", {}).items():
        for rec in recs:
            out.add((rec["tool_id"], fm))
            out |= {(rec["tool_id"], m) for m in rec["addresses_failure_modes"]}
    return out


def test_no_tool_is_offered_for_a_mode_it_measured_below_the_floor() -> None:
    failed = {
        ("promptfoo", "security_vulnerability"),
        ("semgrep", "security_vulnerability"),
    }
    payloads = [recommend(level=level) for level in LEVELS]
    payloads.append(recommend(failure_modes=list(all_failure_modes())))
    for payload in payloads:
        assert not _pairs(payload) & failed
    targeted = payloads[-1]["by_failure_mode"]
    assert "semgrep" not in {r["tool_id"] for r in targeted["security_vulnerability"]}
    # The same tools are still offered for the modes where they did not fail.
    assert "semgrep" in {r["tool_id"] for r in targeted["supply_chain_attack"]}
    assert [r["tool_id"] for r in targeted["test_manipulation"]] == ["promptfoo"]


def test_floor_follows_the_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Change what was measured and the answer changes with it."""
    before = {
        r["tool_id"]
        for r in recommend(failure_modes=["test_manipulation"])["by_failure_mode"][
            "test_manipulation"
        ]
    }
    assert before == {"promptfoo"}
    monkeypatch.setattr(
        evidence_mod,
        "load_evidence",
        lambda: _evidence({"promptfoo": {"test_manipulation": 0.1}}),
    )
    after = recommend(failure_modes=["test_manipulation"])["by_failure_mode"][
        "test_manipulation"
    ]
    assert after == []
    full = recommend(level="full")
    # The only tool tagged for the mode failed on it: the honest answer is
    # that the mode stays uncovered.
    assert "test_manipulation" in full["uncovered_failure_modes"]
    assert full["coverage_complete"] is False


def test_archived_tool_is_offered_for_nothing(tmp_path: Path) -> None:
    tools = default_tools()
    tools["litellm"]["archived"] = True
    with kg.use_data_dir(write_kg(tmp_path / "archived", tools=tools)):
        for payload in [recommend(level=level) for level in LEVELS] + [
            recommend(failure_modes=["scope_creep"])
        ]:
            assert "litellm" not in {tool_id for tool_id, _ in _pairs(payload)}


def test_catalogue_index_keeps_untouched_tags_and_is_cached() -> None:
    """The generators read ``_load_tools`` for the "tagged, not listed"
    table and swap ``_TOOL_INDEX_CACHE``; both names and the raw tags stay."""
    index = recommender._load_tools()
    assert recommender._load_tools() is index
    assert recommender._TOOL_INDEX_CACHE is index
    assert list(index) == sorted(index)
    assert "security_vulnerability" in index["semgrep"]["addresses_failure_modes"]
    # A swapped index is what the selection uses, and the floor still applies.
    recommender._TOOL_INDEX_CACHE = {"semgrep": index["semgrep"]}
    try:
        full = recommend(level="full")
        assert [t["tool_id"] for t in full["tools"]] == ["semgrep"]
        assert full["covered_failure_modes"] == ["supply_chain_attack"]
    finally:
        recommender._TOOL_INDEX_CACHE = index


# ---------------------------------------------------------------------------
# saica_recommend — tiers
# ---------------------------------------------------------------------------


def test_tiers_have_the_documented_sizes() -> None:
    minimum, optimal, full = (recommend(level=level) for level in LEVELS)
    assert [minimum["level"], optimal["level"], full["level"]] == list(LEVELS)
    assert len(minimum["tools"]) == 1
    assert len(optimal["tools"]) == 3 and optimal["k"] == 3
    # The greedy order is one sequence: each tier is a prefix of the next.
    ids = [t["tool_id"] for t in full["tools"]]
    assert [t["tool_id"] for t in optimal["tools"]] == ids[:3]
    assert [t["tool_id"] for t in minimum["tools"]] == ids[:1]
    assert len(ids) == len(set(ids)) < len(all_failure_modes())


def test_full_stops_when_nothing_adds_a_mode_and_reports_what_is_left() -> None:
    full = recommend(level="full")
    tagged = {fm for t in full["tools"] for fm in t["addresses_failure_modes"]}
    assert set(full["covered_failure_modes"]) == tagged
    assert set(full["covered_failure_modes"]) | set(
        full["uncovered_failure_modes"]
    ) == set(all_failure_modes())
    assert full["coverage_complete"] is (full["uncovered_failure_modes"] == [])
    # Every pick added at least one mode that the picks before it lacked.
    seen: set[str] = set()
    for t in full["tools"]:
        assert set(t["addresses_failure_modes"]) - seen
        seen |= set(t["addresses_failure_modes"])


def test_summary_counts_tags_as_tags() -> None:
    for level in LEVELS:
        out = recommend(level=level)
        n, covered = len(out["tools"]), len(out["covered_failure_modes"])
        noun = "tool" if n == 1 else "tools"
        assert out["summary"].startswith(f"{n} {noun}; ")
        assert f"name {covered} of 11 failure modes" in out["summary"]
        assert "claim, not a measurement" in out["summary"]
        assert "cover" not in out["summary"]


def test_recommend_default_is_optimal() -> None:
    assert recommend()["level"] == "optimal" == DEFAULT_LEVEL


def test_recommend_argument_errors() -> None:
    with pytest.raises(ValueError, match="bogus"):
        recommend(level="bogus")
    with pytest.raises(ValueError):
        recommend(level="optimal", failure_modes=["scope_creep"])


def test_ties_do_not_depend_on_file_order(tmp_path: Path) -> None:
    """Two tools with the same tags, stars and status: the lower id wins."""
    tools = {
        name: tool(name, modes=("fabrication",), stars=500)
        for name in ("zeta", "alpha", "mid")
    }
    with kg.use_data_dir(write_kg(tmp_path / "ties", tools=tools)):
        assert recommend(level="minimum")["tools"][0]["tool_id"] == "alpha"
        targeted = recommend(failure_modes=["fabrication"])["by_failure_mode"][
            "fabrication"
        ]
        assert len(targeted) == 3


# ---------------------------------------------------------------------------
# Popularity (was "reliability")
# ---------------------------------------------------------------------------


def test_popularity_is_log_stars_plus_status_and_nothing_else() -> None:
    base = {"stars": 999, "maturity_status": "stable"}
    assert priorities.popularity(base) == pytest.approx(3.0 + 0.5)
    assert priorities.popularity({"stars": 0}) == 0.0
    assert priorities.popularity(
        {"stars": 999, "maturity_status": "deprecated"}
    ) == pytest.approx(2.0)
    # Citations and a trending repository no longer move the score.
    extras = dict(
        base, cited_in=["a", "b", "c"], repository_url="https://github.com/x/y"
    )
    assert priorities.popularity(extras) == priorities.popularity(base)
    assert priorities.reliability is priorities.popularity  # old name


def test_priorities_come_from_the_one_loader() -> None:
    weights = priorities.all_priorities()
    assert weights == dict(sorted(kg.load_priorities().items(), key=lambda kv: -kv[1]))
    assert list(weights.values()) == sorted(weights.values(), reverse=True)
    assert priorities.priority("not_a_mode") == 0.0
    assert priorities.coverage_value(
        {"addresses_failure_modes": ["fabrication", "scope_creep"]}, {"fabrication"}
    ) == pytest.approx(priorities.priority("fabrication"))


# ---------------------------------------------------------------------------
# Filters kept from the earlier catalog
# ---------------------------------------------------------------------------


def test_coding_agent_and_blocklist_filters_still_apply(tmp_path: Path) -> None:
    tools = default_tools()
    tools["cursor"] = tool("cursor", "prevention", ("scope_creep",), stars=900000)
    tools["comfyui"] = tool("comfyui", "prevention", ("scope_creep",), stars=900000)
    assert "cursor" in CODING_AGENT_IDS and "comfyui" in RECOMMENDATION_BLOCKLIST
    with kg.use_data_dir(write_kg(tmp_path / "agents", tools=tools)):
        asked_by_agent = recommend(
            failure_modes=["scope_creep"], agent_kind="claude-code"
        )
        assert {
            r["tool_id"] for r in asked_by_agent["by_failure_mode"]["scope_creep"]
        } == {
            "litellm",
            "daytona",
        }
        anonymous = recommend(failure_modes=["scope_creep"])
        ids = {r["tool_id"] for r in anonymous["by_failure_mode"]["scope_creep"]}
        assert "cursor" in ids and "comfyui" not in ids


# ---------------------------------------------------------------------------
# Server module
# ---------------------------------------------------------------------------


def test_server_lists_exactly_two_tools() -> None:
    import asyncio

    from pipeline.mcp import server

    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {"saica_lookup", "saica_recommend"}
    assert not hasattr(server, "saica_preflight")
    assert not hasattr(server, "saica_audit_repo")
    doc = server.saica_recommend.__doc__
    assert "popularity" in doc and "reliab" not in doc and "trending" not in doc
    assert "MECE" not in doc and "ALL 11" not in doc


def test_server_reads_agent_kind_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.mcp.server import _agent_kind

    monkeypatch.setenv("SAICA_AGENT_KIND", "cursor")
    assert _agent_kind() == "cursor"
    monkeypatch.delenv("SAICA_AGENT_KIND", raising=False)
    assert _agent_kind() is None


def test_help_prints_and_exits_without_serving() -> None:
    """``--help`` used to start the server and wait on stdin (K11)."""
    done = subprocess.run(
        [sys.executable, "-m", "pipeline.mcp.server", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert done.returncode == 0
    assert done.stdout.startswith("usage: python -m pipeline.mcp.server")
