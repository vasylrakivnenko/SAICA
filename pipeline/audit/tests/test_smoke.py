"""Smoke tests for the audit analyzer.

Detector tests run on small temp directories and on a fixture KG
(:mod:`pipeline.shared.kg_fixture`), so they do not change when a curator
adds or removes a tool. Two end-to-end tests audit this repository's own
files, still against the fixture KG, and check structure only.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from pipeline import kg
from pipeline.audit.analyzer import audit_repo_local, parse_repo_url
from pipeline.audit.detectors import (
    detect_agents,
    detect_languages,
    detect_supervision_tools,
)
from pipeline.audit.kg import load_failure_modes, load_tool_index
from pipeline.audit.render import to_markdown
from pipeline.shared.kg_fixture import default_tools, tool, write_kg

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True, scope="module")
def fixture_kg(tmp_path_factory):
    """Every test in this file reads the fixture KG, not ``data/``."""
    with kg.use_data_dir(write_kg(tmp_path_factory.mktemp("kg"))):
        yield


def _resolved(detected) -> set[str]:
    return {d.id for d in detected if d.in_kg}


def _unresolved(detected) -> set[str]:
    return {d.name for d in detected if not d.in_kg}


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


def test_parse_repo_url_accepts_canonical():
    owner, repo = parse_repo_url("https://github.com/owner/repo")
    assert (owner, repo) == ("owner", "repo")


def test_parse_repo_url_accepts_dotgit_suffix():
    owner, repo = parse_repo_url("https://github.com/owner/repo.git")
    assert (owner, repo) == ("owner", "repo")


@pytest.mark.parametrize(
    "bad",
    [
        "https://github.com/owner/repo/tree/main",
        "https://github.com/owner/repo/blob/main/file.py",
        "github.com/owner/repo",  # no scheme
        "https://gitlab.com/owner/repo",  # not github
        "https://github.com/owner",  # no repo
        "https://github.com/owner/repo?x=1",
        "https://github.com/../..",  # dot segments are not names
        "https://github.com/owner/..",
        "https://github.com/owner/.",
        "https://github.com/./repo",
        "https://github.com/-owner/repo",
        "https://github.com/owner/repo/extra",
        "http://github.com/owner/repo",  # https only
        "https://github.com.evil.example/owner/repo",
        "https://evil.example/https://github.com/owner/repo",
        "https://github.com/owner/re po",
        "https://user@github.com/owner/repo",
        "",
    ],
)
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
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
        [project]
        name = "x"
        dependencies = [
            "guardrails-ai>=0.5",
            "litellm",
        ]
    """
        ).strip()
    )
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
    (wf / "sec.yml").write_text(
        textwrap.dedent(
            """
        jobs:
          scan:
            steps:
              - uses: semgrep/semgrep-action@v1
              - uses: snyk/actions/python@master
    """
        )
    )
    detected = detect_supervision_tools(tmp_path)
    ids = {d.id for d in detected if d.in_kg}
    assert "semgrep" in ids
    assert "snyk" in ids


def test_detect_supervision_tools_js_dep(tmp_path: Path):
    """A dependency resolves when the KG lists the tool, and only then."""
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {
                    "promptfoo": "^0.100",  # in the fixture KG
                    "langfuse": "^1",  # recognised, not in the KG
                    "@instructor-ai/instructor": "^0.0.1",  # same
                    "left-pad": "^1",  # no rule: ignored
                },
            }
        )
    )
    detected = detect_supervision_tools(tmp_path)
    assert _resolved(detected) == {"promptfoo"}
    assert _unresolved(detected) == {"Langfuse", "Instructor"}
    # A tool that is not in the KG carries no id and adds no coverage.
    assert all(d.id == "" for d in detected if not d.in_kg)


def test_a_detection_resolves_once_the_kg_lists_the_tool(tmp_path: Path):
    """Same repository, a KG that also holds langfuse: now it resolves."""
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "package.json").write_text(
        json.dumps({"dependencies": {"langfuse": "^1"}})
    )
    assert _unresolved(detect_supervision_tools(tmp_path / "repo")) == {"Langfuse"}

    tools = default_tools()
    tools["langfuse"] = tool("langfuse", modes=("cascading_failure",), name="Langfuse")
    with kg.use_data_dir(write_kg(tmp_path / "bigger", tools=tools)):
        detected = detect_supervision_tools(tmp_path / "repo")
        assert _resolved(detected) == {"langfuse"}
        assert _unresolved(detected) == set()
    # Leaving the block puts this module's fixture KG back.
    assert "langfuse" not in load_tool_index()


def test_detect_supervision_tools_pyproject_tool_sections(tmp_path: Path):
    """Repos in the wild (openai-python, anthropic-sdk-python, fastapi)
    declare ruff/mypy/pyright/pytest in [tool.<x>] sections. Detector
    must pick all of them up from one pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
        [project]
        name = "demo"

        [tool.ruff]
        line-length = 100

        [tool.ruff.lint]
        select = ["E", "F"]

        [tool.mypy]
        strict = true

        [tool.pyright]
        pythonVersion = "3.12"

        [tool.pytest.ini_options]
        addopts = "-q"

        [tool.coverage.run]
        branch = true

        [tool.black]
        line-length = 100

        [tool.isort]
        profile = "black"
        """
        ).strip()
    )
    detected = detect_supervision_tools(tmp_path)
    # In the fixture KG: resolved. One entry each, whatever the sub-tables.
    assert _resolved(detected) == {"ruff", "mypy", "pyright", "pytest"}
    assert len([d for d in detected if d.in_kg]) == 4
    # Recognised by a rule, but not catalog tools: reported apart.
    assert _unresolved(detected) == {"Coverage.py", "Black", "isort"}


def test_pyproject_build_only_sections_are_ignored(tmp_path: Path):
    """[tool.poetry], [tool.hatch], [tool.uv] etc. are build/packaging,
    not supervisors — must NOT be emitted as detected supervision."""
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
        [project]
        name = "demo"

        [tool.poetry]
        name = "demo"

        [tool.hatch.build]
        include = ["x/**"]

        [tool.uv]
        dev-dependencies = []

        [tool.pdm]
        version = "0.1"

        [tool.rye]
        managed = true
        """
        ).strip()
    )
    detected = detect_supervision_tools(tmp_path)
    ids = {d.id for d in detected if d.in_kg}
    assert ids == set(), f"build-only sections leaked into detection: {ids}"


def test_pyproject_eslint_in_package_json_devdeps(tmp_path: Path):
    """JS analogue: eslint/prettier in devDependencies should resolve."""
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "devDependencies": {
                    "eslint": "^9",
                    "prettier": "^3",
                },
            }
        )
    )
    detected = detect_supervision_tools(tmp_path)
    assert _resolved(detected) == {"eslint"}
    assert _unresolved(detected) == {"Prettier"}


# ---------------------------------------------------------------------------
# End-to-end on the saica-kg repo itself
# ---------------------------------------------------------------------------


def test_audit_self_repo_smoke():
    """Audit the saica-kg repo using audit_repo_local. Should not crash."""
    report = audit_repo_local(
        REPO_ROOT, repo_url="https://github.com/vasylrakivnenko/SAICA"
    )
    assert report.repo_url.endswith("SAICA")
    assert report.audited_at is not None
    assert isinstance(report.markdown, str) and len(report.markdown) > 200
    # Coverage grid has one cell per (FM × paradigm).
    fms = load_failure_modes()
    assert len(report.coverage.cells) == len(fms) * 4  # 4 paradigms
    # All recommendation tool ids exist in the KG.
    index = load_tool_index()
    for gap in report.gaps:
        for rec in gap.recommendations:
            assert (
                rec.tool_id in index
            ), f"gap rec points at unknown tool: {rec.tool_id}"
    # Detected supervision tools all resolve to KG.
    for t in report.stack.supervision_tools:
        assert t.in_kg
        assert t.id in index
    # Every report says what the audit can and cannot see.
    assert report.limits is not None
    assert set(report.limits.detectable_tools) | set(
        report.limits.undetectable_tools
    ) == set(index)


def test_to_markdown_renders_sections():
    report = audit_repo_local(
        REPO_ROOT, repo_url="https://github.com/vasylrakivnenko/SAICA"
    )
    md = to_markdown(report)
    assert md.startswith("# Audit:")
    for header in (
        "## Executive summary",
        "## Detected stack",
        "## Coverage",
        "## Gaps and recommendations",
        "## Limits of this audit",
    ):
        assert header in md
