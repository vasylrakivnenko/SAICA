"""Smoke tests for the audit analyzer.

These run against the saica-kg repo itself (we have it on disk anyway) and
against synthetic temp dirs for the per-detector unit tests.
"""
from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest

from pipeline.audit.analyzer import audit_repo_local, parse_repo_url
from pipeline.audit.detectors import (
    detect_agents,
    detect_languages,
    detect_supervision_tools,
)
from pipeline.audit.kg import load_failure_modes, load_tool_index
from pipeline.audit.render import to_markdown

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def test_parse_repo_url_accepts_canonical():
    owner, repo = parse_repo_url("https://github.com/owner/repo")
    assert (owner, repo) == ("owner", "repo")


def test_parse_repo_url_accepts_dotgit_suffix():
    owner, repo = parse_repo_url("https://github.com/owner/repo.git")
    assert (owner, repo) == ("owner", "repo")


@pytest.mark.parametrize("bad", [
    "https://github.com/owner/repo/tree/main",
    "https://github.com/owner/repo/blob/main/file.py",
    "github.com/owner/repo",          # no scheme
    "https://gitlab.com/owner/repo",  # not github
    "https://github.com/owner",       # no repo
    "https://github.com/owner/repo?x=1",
])
def test_parse_repo_url_rejects_bad(bad):
    with pytest.raises(ValueError):
        parse_repo_url(bad)


# ---------------------------------------------------------------------------
# Detectors — synthetic temp dirs
# ---------------------------------------------------------------------------

def test_detect_languages_python_node(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "tsconfig.json").write_text("{}")
    langs = detect_languages(tmp_path)
    assert "python" in langs
    assert "javascript" in langs
    assert "typescript" in langs


def test_detect_agents_claude_code(tmp_path: Path):
    (tmp_path / "CLAUDE.md").write_text("hi")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    agents = detect_agents(tmp_path)
    ids = {a.id for a in agents}
    assert "claude-code" in ids


def test_detect_agents_cursor(tmp_path: Path):
    (tmp_path / ".cursorrules").write_text("rules")
    agents = detect_agents(tmp_path)
    ids = {a.id for a in agents}
    assert "cursor" in ids


def test_detect_supervision_tools_python_dep(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(textwrap.dedent("""
        [project]
        name = "x"
        dependencies = [
            "guardrails-ai>=0.5",
            "litellm",
        ]
    """).strip())
    detected = detect_supervision_tools(tmp_path)
    ids = {d.id for d in detected if d.in_kg}
    assert "guardrails-ai" in ids
    assert "litellm" in ids


def test_detect_supervision_tools_dependabot_renovate(tmp_path: Path):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "dependabot.yml").write_text("version: 2\nupdates: []\n")
    (tmp_path / "renovate.json").write_text("{}")
    detected = detect_supervision_tools(tmp_path)
    ids = {d.id for d in detected if d.in_kg}
    assert "dependabot" in ids
    assert "renovate" in ids


def test_detect_supervision_tools_ci_action(tmp_path: Path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "sec.yml").write_text(textwrap.dedent("""
        jobs:
          scan:
            steps:
              - uses: semgrep/semgrep-action@v1
              - uses: snyk/actions/python@master
    """))
    detected = detect_supervision_tools(tmp_path)
    ids = {d.id for d in detected if d.in_kg}
    assert "semgrep" in ids
    assert "snyk" in ids


def test_detect_supervision_tools_js_dep(tmp_path: Path):
    (tmp_path / "package.json").write_text(json.dumps({
        "dependencies": {
            "langfuse": "^1",
            "@instructor-ai/instructor": "^0.0.1",
        },
    }))
    detected = detect_supervision_tools(tmp_path)
    ids = {d.id for d in detected if d.in_kg}
    assert "langfuse" in ids
    assert "instructor" in ids


# ---------------------------------------------------------------------------
# End-to-end on the saica-kg repo itself
# ---------------------------------------------------------------------------

def test_audit_self_repo_smoke():
    """Audit the saica-kg repo using audit_repo_local. Should not crash."""
    report = audit_repo_local(REPO_ROOT, repo_url="https://github.com/saica-kg/saica-kg")
    assert report.repo_url.endswith("saica-kg")
    assert report.audited_at is not None
    assert isinstance(report.markdown, str) and len(report.markdown) > 200
    # Coverage grid has one cell per (FM × paradigm).
    fms = load_failure_modes()
    assert len(report.coverage.cells) == len(fms) * 4  # 4 paradigms
    # All recommendation tool ids exist in the KG.
    kg = load_tool_index()
    for gap in report.gaps:
        for rec in gap.recommendations:
            assert rec.tool_id in kg, f"gap rec points at unknown tool: {rec.tool_id}"
    # Detected supervision tools all resolve to KG.
    for t in report.stack.supervision_tools:
        assert t.in_kg
        assert t.id in kg


def test_to_markdown_renders_sections():
    report = audit_repo_local(REPO_ROOT, repo_url="https://github.com/saica-kg/saica-kg")
    md = to_markdown(report)
    assert md.startswith("# Audit:")
    for header in ("## Executive summary", "## Detected stack", "## Coverage", "## Gaps and recommendations"):
        assert header in md
