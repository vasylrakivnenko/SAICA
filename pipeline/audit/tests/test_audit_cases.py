"""Fixture cases for the audit bugs of review 2026-11-21 (H4).

Each test builds a small repository in a temp directory and audits it
against the fixture KG (:mod:`pipeline.shared.kg_fixture`). In that KG
``sentrux`` is the only tool tagged for ``cascading_failure`` and
``dependency_blindness`` and the audit has no rule for it, so those two
modes are "not assessable".
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from pipeline import kg
from pipeline.audit import cli
from pipeline.audit.analyzer import audit_repo_local, distinct_tool_count
from pipeline.audit.coverage import fits_languages
from pipeline.audit.detectors import (
    detect_supervision_tools,
    detectable_tool_ids,
    rule_target_ids,
)
from pipeline.shared.kg_fixture import default_tools, tool, write_kg


@pytest.fixture(autouse=True, scope="module")
def fixture_kg(tmp_path_factory):
    with kg.use_data_dir(write_kg(tmp_path_factory.mktemp("kg"))):
        yield


def _write(root: Path, rel: str, text: str | bytes) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        target.write_bytes(text)
    else:
        target.write_text(textwrap.dedent(text), encoding="utf-8")


def _found(root: Path) -> set[str]:
    return {d.id for d in detect_supervision_tools(root) if d.in_kg}


# ---------------------------------------------------------------------------
# Unusual manifests must not crash the audit
# ---------------------------------------------------------------------------

ODD_MANIFESTS = {
    "pyproject in Latin-1": (
        "pyproject.toml",
        "[project]\nname = 'caf\xe9'\n".encode("latin-1"),
    ),
    "pyproject in UTF-16": (
        "pyproject.toml",
        "[project]\nname = 'x'\n".encode("utf-16"),
    ),
    "pyproject not TOML": ("pyproject.toml", b"this is = = not toml ["),
    "project is a string": ("pyproject.toml", b"project = 'x'\n"),
    "dependencies is a table": (
        "pyproject.toml",
        b"[project]\nname='x'\n[project.dependencies]\nruff='1'\n",
    ),
    "optional deps is a list": (
        "pyproject.toml",
        b"[project]\noptional-dependencies = ['ruff']\n",
    ),
    "tool is a string": ("pyproject.toml", b"tool = 'x'\n"),
    "poetry is a list": ("pyproject.toml", b"[tool]\npoetry = [1, 2]\n"),
    "poetry group is a list": ("pyproject.toml", b"[tool.poetry]\ngroup = ['dev']\n"),
    "pdm dev-deps is a string": (
        "pyproject.toml",
        b"[tool.pdm]\ndev-dependencies = 'x'\n",
    ),
    "package.json is a list": ("package.json", b'["eslint"]'),
    "package.json deps is a list": ("package.json", b'{"dependencies": ["eslint"]}'),
    "package.json is not JSON": ("package.json", b"{not json"),
    "package.json in UTF-16": (
        "package.json",
        '{"devDependencies": {"eslint": "9"}}'.encode("utf-16"),
    ),
    "requirements in Latin-1": (
        "requirements.txt",
        "litellm  # v\xe9rifi\xe9\n".encode("latin-1"),
    ),
    "workflow is a list": (".github/workflows/ci.yml", b"- a\n- b\n"),
    "workflow jobs is a string": (".github/workflows/ci.yml", b"jobs: none\n"),
    "workflow steps is a string": (
        ".github/workflows/ci.yml",
        b"jobs:\n  a:\n    steps: none\n",
    ),
    "workflow is binary": (".github/workflows/ci.yml", bytes(range(256)) * 4),
    "pre-commit repos is a string": (".pre-commit-config.yaml", b"repos: semgrep\n"),
    "pre-commit hooks is a string": (
        ".pre-commit-config.yaml",
        b"repos:\n  - repo: local\n    hooks: semgrep\n",
    ),
    "pre-commit deeply nested": (".pre-commit-config.yaml", b"[" * 5000),
}


@pytest.mark.parametrize("case", sorted(ODD_MANIFESTS))
def test_odd_manifest_does_not_crash_the_audit(tmp_path: Path, case: str):
    rel, content = ODD_MANIFESTS[case]
    _write(tmp_path, rel, content)
    report = audit_repo_local(tmp_path, repo_url="https://github.com/o/r")
    assert report.markdown.startswith("# Audit:")
    # Nothing in these files is a clean declaration of a tool, except the
    # Latin-1 requirements line, whose package name is plain ASCII.
    expected = {"litellm"} if case == "requirements in Latin-1" else set()
    assert _found(tmp_path) == expected, case


# ---------------------------------------------------------------------------
# Commented-out lines are not detections
# ---------------------------------------------------------------------------


def test_commented_out_workflow_step_is_not_a_detection(tmp_path: Path):
    _write(
        tmp_path,
        ".github/workflows/sec.yml",
        """
        jobs:
          scan:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
              # - uses: snyk/actions/python@master   (disabled 2024)
              - run: |
                  echo "uses: semgrep/semgrep-action@v1"
        """,
    )
    assert _found(tmp_path) == set()


def test_real_workflow_steps_and_reusable_jobs_are_detected(tmp_path: Path):
    _write(
        tmp_path,
        ".github/workflows/sec.yml",
        """
        jobs:
          scan:
            steps:
              - uses: "snyk/actions/python@master"  # pinned later
          review:
            uses: qodo-ai/pr-agent/.github/workflows/review.yml@main
        """,
    )
    assert _found(tmp_path) == {"snyk", "pr-agent"}


def test_job_that_runs_in_the_tools_container_image_is_detected(tmp_path: Path):
    """The form Semgrep documents today has no ``uses:`` step for Semgrep."""
    _write(
        tmp_path,
        ".github/workflows/semgrep.yml",
        """
        jobs:
          semgrep:
            runs-on: ubuntu-latest
            container:
              image: semgrep/semgrep:1.96.0
            steps:
              - uses: actions/checkout@v4
              - run: semgrep ci
          other:
            container: node:22        # short form, not a catalog tool
            steps: []
          lookalike:
            container: {image: someone/semgrep/semgrep-clone}
            steps: []
        """,
    )
    detected = detect_supervision_tools(tmp_path)
    assert [(d.id, d.detection_source, d.detection_paths) for d in detected] == [
        ("semgrep", "ci_workflow", [".github/workflows/semgrep.yml"])
    ]
    _write(
        tmp_path,
        ".github/workflows/semgrep.yml",
        "jobs:\n  a:\n    container: returntocorp/semgrep\n",
    )
    assert _found(tmp_path) == {"semgrep"}
    _write(
        tmp_path,
        ".github/workflows/semgrep.yml",
        "jobs:\n  a:\n    # container: semgrep/semgrep\n    steps: []\n",
    )
    assert _found(tmp_path) == set()


def test_workflow_that_is_not_yaml_falls_back_to_a_line_scan(tmp_path: Path):
    _write(
        tmp_path,
        ".github/workflows/broken.yml",
        """
        jobs:
          scan:
            steps:
              - uses: semgrep/semgrep-action@v1
              # - uses: snyk/actions/python@master
            bad: [unclosed
        """,
    )
    assert _found(tmp_path) == {"semgrep"}


def test_word_in_a_pre_commit_comment_is_not_a_detection(tmp_path: Path):
    _write(
        tmp_path,
        ".pre-commit-config.yaml",
        """
        # TODO: maybe evaluate semgrep and ruff some day
        repos: []
        """,
    )
    detected = detect_supervision_tools(tmp_path)
    assert {d.id for d in detected if d.in_kg} == set()
    # The framework itself is recognised; it is not a catalog tool here.
    assert [d.name for d in detected] == ["pre-commit"]


def test_pre_commit_hooks_are_read_from_the_parsed_file(tmp_path: Path):
    _write(
        tmp_path,
        ".pre-commit-config.yaml",
        """
        repos:
          - repo: https://github.com/semgrep/semgrep
            rev: v1.96.0
            hooks:
              - id: semgrep
          - repo: https://github.com/astral-sh/ruff-pre-commit.git
            rev: v0.6.9
            hooks: [{id: ruff}]
          - repo: local
            hooks:
              - id: mypy
                entry: mypy
                language: system
              - id: not-bandit-at-all
          - repo: https://github.com/PyCQA/bandit
            rev: 1.7.0
            hooks: []        # declared, runs nothing
          - repo: https://github.com/someone/semgrep-rules-mirror
            rev: v1
            hooks: [{id: check}]
        """,
    )
    assert _found(tmp_path) == {"semgrep", "ruff", "mypy"}


def test_commented_requirements_and_near_miss_names_are_not_detections(tmp_path: Path):
    _write(
        tmp_path,
        "requirements.txt",
        """
        # litellm==1.0   (removed)
        requests>=2  # not guardrails-ai
        litellm-proxy-extras==0.1
        my-ruff-plugin
        -r other.txt
        Guardrails_AI>=0.5
        """,
    )
    _write(
        tmp_path,
        "setup.py",
        """
        setup(
            install_requires=[
                # "semgrep",
                "promptfoo>=0.1",
            ],
        )
        """,
    )
    assert _found(tmp_path) == {"guardrails-ai", "promptfoo"}


# ---------------------------------------------------------------------------
# One tool is counted once
# ---------------------------------------------------------------------------


def test_a_tool_seen_in_two_places_is_counted_once(tmp_path: Path):
    _write(
        tmp_path,
        ".github/workflows/sec.yml",
        "jobs:\n  a:\n    steps:\n      - uses: semgrep/semgrep-action@v1\n",
    )
    _write(
        tmp_path,
        ".pre-commit-config.yaml",
        "repos:\n  - repo: https://github.com/semgrep/semgrep\n    hooks: [{id: semgrep}]\n",
    )
    report = audit_repo_local(tmp_path, repo_url="https://github.com/o/r")
    # Two detections (two reasons), one tool.
    assert [t.id for t in report.stack.supervision_tools] == ["semgrep", "semgrep"]
    assert distinct_tool_count(report.stack) == 1
    assert "found 1 catalog tool in r." in report.summary
    assert "| Catalog tools found | Semgrep |" in report.markdown


def test_cli_tail_counts_distinct_tools(tmp_path: Path, capsys):
    _write(
        tmp_path,
        ".github/workflows/sec.yml",
        "jobs:\n  a:\n    steps:\n      - uses: semgrep/semgrep-action@v1\n",
    )
    _write(
        tmp_path,
        ".pre-commit-config.yaml",
        "repos:\n  - repo: https://github.com/semgrep/semgrep\n    hooks: [{id: semgrep}]\n",
    )
    assert cli.main([str(tmp_path), "--local"]) == 0
    out = capsys.readouterr().out
    tail = json.loads(out[out.rindex("```json") + 7 : out.rindex("```")])
    assert tail["n_supervision_tools"] == 1
    assert tail["failure_modes_not_assessable"] == [
        "cascading_failure",
        "dependency_blindness",
    ]


def test_cli_local_with_a_missing_path_prints_an_error_line(tmp_path: Path, capsys):
    assert cli.main([str(tmp_path / "nope"), "--local"]) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ") and "Traceback" not in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# Limits: what the audit cannot see is said, and is not a gap
# ---------------------------------------------------------------------------


def test_every_rule_points_at_an_id_and_the_limits_follow_the_kg():
    index = kg.load_tools()
    detectable = detectable_tool_ids(index)
    assert detectable == rule_target_ids() & set(index)
    assert "sentrux" in index and "sentrux" not in detectable
    assert "daytona" not in detectable  # no rule for the sandbox either


def test_modes_with_no_detectable_tool_are_marked_not_assessable(tmp_path: Path):
    report = audit_repo_local(tmp_path, repo_url="https://github.com/o/empty")
    blind = ["cascading_failure", "dependency_blindness"]
    assert report.coverage.failure_modes_not_assessable == blind
    assert report.limits.not_assessable_failure_modes == blind
    # They are missing coverage, but they are not gaps.
    assert set(blind) <= set(report.coverage.failure_modes_missing)
    assert not {g.failure_mode for g in report.gaps} & set(blind)
    # Every other mode is a high gap in an empty repository.
    assert {g.failure_mode for g in report.gaps} == set(kg.failure_mode_ids()) - set(
        blind
    )
    assert {g.severity for g in report.gaps} == {"high"}
    assert "2 failure modes cannot be assessed" in report.summary
    md = report.markdown
    assert "## Not assessable" in md
    assert "| Cascading failure | n/a | n/a | n/a | n/a |" in md
    assert "| Fabrication | · | · | · | · |" in md


def test_limits_list_what_the_audit_can_and_cannot_detect(tmp_path: Path):
    limits = audit_repo_local(tmp_path, repo_url="https://github.com/o/empty").limits
    assert limits.catalog_tools == len(default_tools())
    assert sorted(limits.detectable_tools + limits.undetectable_tools) == sorted(
        default_tools()
    )
    assert limits.undetectable_tools == ["daytona", "sentrux"]
    assert any("sub-folder" in note for note in limits.notes)
    md = audit_repo_local(tmp_path, repo_url="https://github.com/o/empty").markdown
    assert "The audit can detect 15 of the 17 catalog tools" in md
    assert "It cannot detect the other 2: daytona, sentrux." in md


def test_a_high_gap_says_how_many_tools_the_audit_could_have_seen(tmp_path: Path):
    """scope_creep: litellm is detectable, daytona is not."""
    report = audit_repo_local(tmp_path, repo_url="https://github.com/o/empty")
    gap = next(g for g in report.gaps if g.failure_mode == "scope_creep")
    assert "None of the 1 catalog tool that this audit can detect" in gap.rationale
    assert "lists 1 more for this mode that the audit cannot detect" in gap.rationale


def test_single_paradigm_gap_needs_a_catalog_tool_of_the_other_paradigm(tmp_path: Path):
    """ruff covers logic_error and fabrication by detection.

    The fixture KG has a prevention tool for fabrication (guardrails-ai)
    and none for logic_error. So fabrication is a medium gap that suggests
    only prevention tools, and logic_error is no gap at all.
    """
    _write(
        tmp_path,
        "pyproject.toml",
        "[project]\nname = 'x'\n[tool.ruff]\nline-length = 100\n",
    )
    report = audit_repo_local(tmp_path, repo_url="https://github.com/o/py")
    by_mode = {g.failure_mode: g for g in report.gaps}
    assert "logic_error" not in by_mode
    gap = by_mode["fabrication"]
    assert (gap.severity, gap.paradigm) == ("medium", "prevention")
    assert [r.tool_id for r in gap.recommendations] == ["guardrails-ai"]
    assert all(r.paradigm == "prevention" for r in gap.recommendations)
    assert "one way only (detection)" in gap.rationale


def test_python_repository_is_not_told_to_add_a_javascript_linter(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", "[project]\nname = 'x'\n")
    report = audit_repo_local(tmp_path, repo_url="https://github.com/o/py")
    assert report.stack.languages == ["python"]
    suggested = {r.tool_id for g in report.gaps for r in g.recommendations}
    assert "eslint" not in suggested
    assert {"ruff", "mypy"} <= suggested

    index = kg.load_tools()
    assert fits_languages(index["eslint"], ["python"]) is False
    assert fits_languages(index["eslint"], ["python", "typescript"]) is True
    assert fits_languages(index["eslint"], []) is True  # nothing detected: no filter
    assert fits_languages(index["litellm"], ["go"]) is True  # no language recorded


def test_repository_with_every_detectable_tool_has_no_false_gaps(tmp_path: Path):
    _write(
        tmp_path,
        "requirements.txt",
        "guardrails-ai\nlitellm\npromptfoo\n",
    )
    _write(
        tmp_path,
        "pyproject.toml",
        "[project]\nname='x'\n[tool.ruff]\n[tool.mypy]\n[tool.pyright]\n[tool.pytest.ini_options]\n[tool.bandit]\n",
    )
    _write(tmp_path, "package.json", '{"devDependencies": {"eslint": "9"}}')
    _write(tmp_path, ".github/dependabot.yml", "version: 2\n")
    _write(tmp_path, "renovate.json", "{}")
    _write(
        tmp_path,
        ".github/workflows/ci.yml",
        "jobs:\n  a:\n    steps:\n      - uses: semgrep/semgrep-action@v1\n      - uses: snyk/actions/python@master\n      - uses: SocketDev/socket-action@v1\n      - uses: qodo-ai/pr-agent@main\n",
    )
    report = audit_repo_local(tmp_path, repo_url="https://github.com/o/full")
    assert {t.id for t in report.stack.supervision_tools} == set(
        report.limits.detectable_tools
    )
    # Nothing detectable is missing, so no high gap; what remains are
    # single-paradigm modes for which the catalog has something to add.
    assert [g for g in report.gaps if g.severity == "high"] == []
    for gap in report.gaps:
        assert gap.recommendations, gap.failure_mode
        assert all(r.paradigm == gap.paradigm for r in gap.recommendations)
    assert report.coverage.failure_modes_not_assessable == [
        "cascading_failure",
        "dependency_blindness",
    ]


# ---------------------------------------------------------------------------
# The Markdown report
# ---------------------------------------------------------------------------


def test_report_links_are_absolute_and_name_the_real_site(tmp_path: Path):
    _write(tmp_path, "package.json", '{"devDependencies": {"prettier": "3"}}')
    md = audit_repo_local(tmp_path, repo_url="https://github.com/o/r").markdown
    assert "](/tools/" not in md
    assert "](https://saica.ai/tools/eslint/)" in md
    assert md.rstrip().endswith(
        "Generated by the SAICA audit — https://saica.ai/assess/"
    )
    assert "saica-kg.dev" not in md
    # A recognised tool that the catalog does not list is not an invitation
    # to add it, and it is not counted.
    assert "## Recognised, not in the catalog" in md
    assert "**Prettier**" in md
    assert "opening a PR" not in md
    assert "found no catalog tool" in md


def test_a_tool_the_kg_gained_changes_the_limits_not_the_code(tmp_path: Path):
    """Give ``cascading_failure`` a detectable tool: it becomes assessable."""
    tools = default_tools()
    tools["langgraph"] = tool(
        "langgraph", "prevention", ("cascading_failure",), ("library",)
    )
    with kg.use_data_dir(write_kg(tmp_path / "kg2", tools=tools)):
        (tmp_path / "repo").mkdir()
        report = audit_repo_local(tmp_path / "repo", repo_url="https://github.com/o/r")
        assert report.coverage.failure_modes_not_assessable == ["dependency_blindness"]
        assert "cascading_failure" in {g.failure_mode for g in report.gaps}
