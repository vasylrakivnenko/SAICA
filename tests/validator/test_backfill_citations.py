"""Tests for ``validator.backfill_citations``.

Coverage targets:

* the matcher accepts a literal repository URL ("url" rule, conf 1.0)
* the matcher accepts an ``owner/repo`` slug as a standalone token
* the matcher accepts a multi-word name with hyphen ↔ space tolerance
* borderline single-word names are SKIPPED unless a context signal is
  present in the surrounding window (the "rebuff" / "manifest" / "modal"
  family is the worst-offender set)
* tools whose name is a generic protocol token (``URL_ONLY_TOOL_IDS``)
  are SKIPPED entirely on name match
* ``apply_matches`` is idempotent: running it twice on the same data
  produces no second-pass diff
* the run on the actual repo data completes well under 60s

The integration tests use the live ``data/papers`` and ``data/tools``
corpora — they don't write to those YAMLs (we use a tmp working copy).
"""

from __future__ import annotations

import io
import shutil
import time
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from validator import backfill_citations as bc


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _tool(id_: str, name: str = "", repo: str = "") -> bc.ToolMeta:
    return bc.ToolMeta(
        id=id_,
        name=name,
        repo_url=repo,
        repo_slug=bc._slug_from_repo(repo),
    )


def _paper(**fields) -> dict:
    base = {"id": fields.get("id", "test-paper")}
    base.update(fields)
    return base


# --------------------------------------------------------------------------- #
# Unit tests — matcher rules
# --------------------------------------------------------------------------- #


def test_repo_url_match_is_high_confidence() -> None:
    paper = _paper(
        id="paper-x",
        notes="The agent runs the workflow defined at https://github.com/foo/bar.",
    )
    tool = _tool("foo-bar", name="FooBar", repo="https://github.com/foo/bar")
    m = bc.match_paper_to_tool("paper-x", paper, tool)
    assert m is not None
    assert m.confidence == 1.0
    assert m.rule == "url"
    assert m.field == "notes"


def test_owner_repo_slug_match() -> None:
    paper = _paper(
        id="paper-x",
        tldr="Evaluated against the microsoft/autogen multi-agent framework.",
    )
    tool = _tool("autogen", name="AutoGen", repo="https://github.com/microsoft/autogen")
    m = bc.match_paper_to_tool("paper-x", paper, tool)
    assert m is not None
    assert m.confidence == 1.0
    assert m.rule in {"slug", "url"}  # url won't match here; slug will
    assert "microsoft/autogen" in m.matched_text or m.matched_text == tool.repo_url


def test_name_match_with_hyphen_space_tolerance() -> None:
    """``Gemini CLI`` (with space) should match ``Gemini-CLI`` (with hyphen)."""
    paper = _paper(
        id="paper-x",
        tldr="…contrasted against Gemini-CLI's headless-incompatible auth model.",
    )
    tool = _tool(
        "gemini-cli",
        name="Gemini CLI",
        repo="https://github.com/google-gemini/gemini-cli",
    )
    m = bc.match_paper_to_tool("paper-x", paper, tool)
    assert m is not None
    assert m.rule == "name"
    assert m.confidence == 0.9


def test_borderline_single_word_name_requires_context() -> None:
    """``aider`` is in the BORDERLINE set; bare mention shouldn't match."""
    bare = _paper(id="p1", notes="The team should aider one another.")
    aider = _tool("aider", name="Aider", repo="https://github.com/paul-gauthier/aider")
    assert bc.match_paper_to_tool("p1", bare, aider) is None

    with_signal = _paper(
        id="p2",
        notes="The Aider coding agent commits each LLM edit as a separate git commit.",
    )
    m = bc.match_paper_to_tool("p2", with_signal, aider)
    assert m is not None
    assert m.rule == "name+context"
    assert m.confidence == 0.9


def test_url_only_tool_is_not_matched_by_name() -> None:
    """``browser-mcp``'s name is "mcp" — bare "MCP" mentions must NOT match."""
    paper = _paper(id="p1", notes="LLM agents query real-world MCP servers.")
    tool = _tool("browser-mcp", name="mcp", repo="https://github.com/BrowserMCP/mcp")
    m = bc.match_paper_to_tool("p1", paper, tool)
    # Should be skipped on name-rule (URL_ONLY_TOOL_IDS); URL not in text.
    assert m is None


def test_url_only_tool_still_matches_on_repo_url() -> None:
    paper = _paper(
        id="p1",
        notes="See https://github.com/BrowserMCP/mcp for the canonical MCP shim.",
    )
    tool = _tool("browser-mcp", name="mcp", repo="https://github.com/BrowserMCP/mcp")
    m = bc.match_paper_to_tool("p1", paper, tool)
    assert m is not None
    assert m.confidence == 1.0
    assert m.rule == "url"


def test_no_repo_tool_requires_context_signal() -> None:
    """``Cursor`` has no GitHub repo to disambiguate; needs context word
    AND, since "cursor" is a common English noun, the brand-name occurrence
    must be exact-case (``Cursor``)."""
    bare = _paper(id="p1", notes="They placed the cursor at the end of the line.")
    cursor = _tool("cursor", name="Cursor", repo="")
    # No context signal AND lowercase only → no match.
    assert bc.match_paper_to_tool("p1", bare, cursor) is None

    contextful = _paper(
        id="p2",
        notes="Cursor is a popular AI coding IDE that ships an agent mode.",
    )
    m = bc.match_paper_to_tool("p2", contextful, cursor)
    assert m is not None
    assert m.rule == "name+context"
    assert m.confidence == 0.9


def test_no_repo_tool_lowercase_brand_requires_exact_case() -> None:
    """Lowercase ``cursor`` (English noun) inside an otherwise-context-rich
    sentence must NOT match ``Cursor`` the brand."""
    cursor = _tool("cursor", name="Cursor", repo="")
    # Context words ("LLM", "agent", "code") nearby, but the literal token
    # is lowercase — should be skipped because of exact-case enforcement.
    paper = _paper(
        id="p1",
        notes="The LLM agent moved the cursor before generating the next code line.",
    )
    assert bc.match_paper_to_tool("p1", paper, cursor) is None


def test_multi_word_no_repo_brand_matches_without_case_check() -> None:
    """``Claude Code`` is multi-word and unambiguous — should match even in
    odd casing (the brand is the only plausible referent)."""
    cc = _tool("claude-code", name="Claude Code", repo="")
    paper = _paper(
        id="p1",
        notes="Agentic coding tools such as Claude Code ship a tool allow-list.",
    )
    m = bc.match_paper_to_tool("p1", paper, cc)
    assert m is not None
    assert m.rule == "name+context"
    assert m.confidence == 0.9


def test_short_name_below_min_length_is_skipped() -> None:
    paper = _paper(id="p1", notes="The v0 prototype was unstable.")
    tool = _tool("v0", name="v0", repo="")
    assert bc.match_paper_to_tool("p1", paper, tool) is None


def test_partial_word_does_not_match() -> None:
    """``garak`` must not match inside ``garak-eval`` if we required strict
    boundaries — and must still match a clean standalone occurrence."""
    paper = _paper(
        id="p1",
        notes="The garak LLM-vulnerability scanner ships dozens of probe modules.",
    )
    tool = _tool("garak", name="garak", repo="https://github.com/NVIDIA/garak")
    m = bc.match_paper_to_tool("p1", paper, tool)
    assert m is not None
    assert m.confidence == 0.9
    # And confirm the boundary-strict behavior: 'garak-eval' should NOT pull
    # garak-the-tool through the name rule (it's not a separate identifier).
    paper2 = _paper(id="p2", notes="The garak-eval suite ran against the model.")
    m2 = bc.match_paper_to_tool("p2", paper2, tool)
    assert m2 is None


# --------------------------------------------------------------------------- #
# Unit tests — slug extractor
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/foo/bar", "foo/bar"),
        ("https://github.com/foo/bar.git", "foo/bar"),
        ("https://github.com/foo/bar/", "foo/bar"),
        ("https://github.com/microsoft/autogen", "microsoft/autogen"),
        ("https://gitlab.com/foo/bar", ""),  # not GitHub
        ("", ""),
    ],
)
def test_slug_from_repo(url: str, expected: str) -> None:
    assert bc._slug_from_repo(url) == expected


# --------------------------------------------------------------------------- #
# Integration test — real corpus, tmp tool dir, idempotency
# --------------------------------------------------------------------------- #


@pytest.fixture
def tmp_tools_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy the live ``data/tools`` directory into a temp location and
    monkey-patch the module to write there. Lets us safely exercise
    apply_matches twice without polluting the real corpus.
    """
    tmp_tools = tmp_path / "tools"
    shutil.copytree(bc.TOOLS_DIR, tmp_tools)
    monkeypatch.setattr(bc, "TOOLS_DIR", tmp_tools)
    return tmp_tools


def test_apply_matches_is_idempotent(tmp_tools_dir: Path) -> None:
    yaml = bc._make_yaml()
    papers = bc.load_papers()
    tools = bc.load_tools()
    matches = bc.match_all(papers, tools)

    # First pass.
    added1 = bc.apply_matches(matches, threshold=0.9, yaml=yaml, dry=False)
    snapshot1 = {p.name: p.read_text() for p in tmp_tools_dir.glob("*.yml")}

    # Second pass on the now-updated corpus must add nothing new.
    tools2 = bc.load_tools()
    matches2 = bc.match_all(papers, tools2)
    added2 = bc.apply_matches(matches2, threshold=0.9, yaml=yaml, dry=False)
    snapshot2 = {p.name: p.read_text() for p in tmp_tools_dir.glob("*.yml")}

    assert added2 == {}, f"second-pass writes leaked: {added2!r}"
    assert snapshot1 == snapshot2, "tool YAML bytes drifted on a no-op re-run"


def test_apply_does_not_create_empty_cited_in(tmp_tools_dir: Path) -> None:
    """Per the user's hard constraint: do not write ``cited_in: []`` if
    nothing is being added."""
    yaml = bc._make_yaml()
    papers = bc.load_papers()
    tools = bc.load_tools()
    matches = bc.match_all(papers, tools)
    bc.apply_matches(matches, threshold=0.9, yaml=yaml, dry=False)

    # Spot-check a tool with no historical cited_in that we don't touch.
    # Pick one that we know is not in the matched set: e.g. ``manifest``,
    # ``v0``, ``rebuff``. Those are borderline and have no real match.
    untouched_ids = {"helm", "manifest", "rebuff", "v0", "nono"}
    yaml_ro = YAML(typ="safe")
    for tid in untouched_ids:
        path = tmp_tools_dir / f"{tid}.yml"
        if not path.exists():
            continue
        doc = yaml_ro.load(path.read_text(encoding="utf-8"))
        # ``cited_in`` may have been ``[]`` or absent before; we don't
        # require either, but we DO require it has not been *introduced*
        # as ``[]`` by the apply step. Check the raw text: if it was
        # absent, it must still be absent.
        live_text = (bc.TOOLS_DIR / f"{tid}.yml").read_text()
        if "cited_in:" not in live_text:
            assert "cited_in:" not in path.read_text(
                encoding="utf-8"
            ), f"backfill introduced an empty cited_in into {tid}"


def test_dry_mode_does_not_write(tmp_tools_dir: Path) -> None:
    yaml = bc._make_yaml()
    papers = bc.load_papers()
    tools = bc.load_tools()
    matches = bc.match_all(papers, tools)

    snapshot_before = {p.name: p.read_text() for p in tmp_tools_dir.glob("*.yml")}
    bc.apply_matches(matches, threshold=0.9, yaml=yaml, dry=True)
    snapshot_after = {p.name: p.read_text() for p in tmp_tools_dir.glob("*.yml")}
    assert snapshot_before == snapshot_after


def test_full_run_is_fast() -> None:
    """End-to-end on the real corpus must finish well under 60s."""
    t0 = time.monotonic()
    papers = bc.load_papers()
    tools = bc.load_tools()
    bc.match_all(papers, tools)
    assert time.monotonic() - t0 < 10.0  # generous; live runs are <1s


def test_render_report_is_pure() -> None:
    """Two report renders with the same inputs are byte-identical (modulo
    the date header, which we pass in)."""
    papers = bc.load_papers()
    tools = bc.load_tools()
    matches = bc.match_all(papers, tools)
    a = bc.render_report(
        today="2026-04-23",
        elapsed_s=0.0,
        papers=papers,
        tools=tools,
        matches=matches,
        threshold=0.9,
        added={},
        dry=True,
    )
    b = bc.render_report(
        today="2026-04-23",
        elapsed_s=0.0,
        papers=papers,
        tools=tools,
        matches=matches,
        threshold=0.9,
        added={},
        dry=True,
    )
    assert a == b


# --------------------------------------------------------------------------- #
# YAML round-trip — preserves comments, quote styles, blank lines
# --------------------------------------------------------------------------- #


def test_yaml_roundtrip_preserves_structure(tmp_path: Path) -> None:
    """Editing only ``cited_in`` with our ruamel config must NOT churn
    unrelated whitespace, comments, or quote styles."""
    src = """\
id: example
name: Example
# leading comment
description: >
  Multi-line description
  with two lines.

first_released: '2024-01-01'
maturity_status: stable
license: MIT
control_paradigm: detection
temporal_phase: post_generation
autonomy_level: full_hitl
addresses_failure_modes:
  - logic_error

cited_in: []
documented_in: []
"""
    p = tmp_path / "example.yml"
    p.write_text(src, encoding="utf-8")

    yaml = bc._make_yaml()
    doc = yaml.load(p.read_text(encoding="utf-8"))
    doc["cited_in"] = ["foo-2025"]
    buf = io.StringIO()
    yaml.dump(doc, buf)
    out = buf.getvalue()

    # Comment, blank lines, and the block-scalar marker must survive.
    assert "# leading comment" in out
    assert "description: >" in out
    assert "first_released: '2024-01-01'" in out
    # Only cited_in changed.
    assert "cited_in:\n  - foo-2025" in out
    # documented_in is still untouched.
    assert "documented_in: []" in out
