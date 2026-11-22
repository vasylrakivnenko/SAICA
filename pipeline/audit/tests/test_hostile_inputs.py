"""Hostile repository content (independent review of 2026-11-21).

The detectors parse files that anyone can put in a public repository. Two
inputs took seconds to minutes and one of them gigabytes; both are fixed at
the cause, and the whole detection step of a remote audit now runs in a
child process with a wall-clock and a memory limit, so the next such input
costs a bounded amount and never the server.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from pipeline import kg
from pipeline.audit import analyzer
from pipeline.audit.analyzer import (
    DetectionAborted,
    DetectionLimits,
    audit_repo,
    audit_repo_local,
    detect_stack_isolated,
)
from pipeline.audit.detectors import detect_supervision_tools, fetch_plan
from pipeline.audit.tests.test_fetch import FakeGitHub
from pipeline.shared.kg_fixture import write_kg

WF = ".github/workflows/"


@pytest.fixture(autouse=True, scope="module")
def fixture_kg(tmp_path_factory):
    with kg.use_data_dir(write_kg(tmp_path_factory.mktemp("kg"))):
        yield


def _write(root: Path, rel: str, data: bytes | str) -> Path:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data if isinstance(data, bytes) else data.encode())
    return root


def merge_bomb(levels: int) -> str:
    """The reviewer's input: each level merges the one before nine times."""
    text = "a: &a {x: 1}\n"
    for i in range(levels):
        name, prev = chr(98 + i), chr(97 + i)
        text += f"{name}: &{name}\n  <<: [{','.join(['*' + prev] * 9)}]\n  k{i}: 1\n"
    return text + f"jobs: *{chr(97 + levels)}\n"


def _timed(fn, *args):
    started = time.perf_counter()
    result = fn(*args)
    return result, time.perf_counter() - started


# ---------------------------------------------------------------------------
# The two causes
# ---------------------------------------------------------------------------


def test_yaml_merge_key_bomb_is_refused_not_expanded(tmp_path: Path):
    """356 bytes took 3.2 s, and nine times longer for each 49 more bytes."""
    _write(tmp_path, WF + "a.yml", merge_bomb(7))
    _, seconds = _timed(detect_supervision_tools, tmp_path)
    assert seconds < 0.5
    # Twelve levels would be 9**5 times the work of seven: still instant.
    _write(tmp_path, WF + "a.yml", merge_bomb(12))
    _write(tmp_path, ".pre-commit-config.yaml", merge_bomb(12) + "repos: *m\n")
    found, seconds = _timed(detect_supervision_tools, tmp_path)
    assert seconds < 0.5
    assert [d.name for d in found] == ["pre-commit"]


def test_a_workflow_with_a_merge_key_is_still_scanned_line_by_line(tmp_path: Path):
    _write(
        tmp_path,
        WF + "a.yml",
        "defaults: &d {runs-on: ubuntu-latest}\n"
        "jobs:\n  scan:\n    <<: *d\n    steps:\n"
        "      - uses: snyk/actions/python@master\n"
        "      # - uses: semgrep/semgrep-action@v1\n",
    )
    assert {d.id for d in detect_supervision_tools(tmp_path)} == {"snyk"}


def test_plain_alias_bombs_cost_nothing(tmp_path: Path):
    """Aliases without merge keys are shared objects, not copies."""
    text = "a: &a [x,x,x,x,x,x,x,x,x]\n" + "".join(
        f"{chr(98 + i)}: &{chr(98 + i)} [{','.join(['*' + chr(97 + i)] * 9)}]\n"
        for i in range(12)
    )
    _write(
        tmp_path, WF + "a.yml", text + "jobs:\n  j:\n    steps: *m\n    container: *m\n"
    )
    _write(tmp_path, ".pre-commit-config.yaml", text + "repos: *m\n")
    found, seconds = _timed(detect_supervision_tools, tmp_path)
    assert seconds < 0.5 and [d.name for d in found] == ["pre-commit"]


@pytest.mark.parametrize("size", [128_000, 512_000])
def test_setup_py_scan_is_linear(tmp_path: Path, size: int):
    """`install_requires=[` repeated: 256 kB took 11 s, 512 kB took 39 s."""
    unit = b"install_requires=["
    _write(tmp_path, "setup.py", unit * (size // len(unit)))
    found, seconds = _timed(detect_supervision_tools, tmp_path)
    assert seconds < 1.0, f"{size} bytes took {seconds:.2f} s"
    assert found == []


def test_setup_py_is_read_as_python_so_comments_and_docstrings_do_not_count(
    tmp_path: Path,
):
    cases = {
        '# install_requires=["litellm"],\nfrom setuptools import setup\nsetup(name="x")\n': set(),
        '"""example: install_requires=["litellm"]"""\nsetup(name="x")\n': set(),
        'setup(install_requires=[\n  "requests",  # "litellm",\n  # "promptfoo",\n])\n': set(),
        'setup(name="x", install_requires=["litellm>=1", "guardrails-ai"])\n': {
            "litellm",
            "guardrails-ai",
        },
        'REQS = ["promptfoo"]\ninstall_requires = ["litellm"]\nsetup(install_requires=install_requires)\n': {
            "litellm"
        },
        # Not valid Python 3: the line scan is the fallback, comments skipped.
        'print "py2"\n# install_requires=["promptfoo"]\nsetup(install_requires=["litellm",\n  # "guardrails-ai",\n])\n': {
            "litellm"
        },
    }
    for i, (text, expected) in enumerate(cases.items()):
        root = _write(tmp_path / f"case{i}", "setup.py", text)
        assert {
            d.id for d in detect_supervision_tools(root) if d.in_kg
        } == expected, text


def test_fetch_plan_is_linear_in_the_number_of_files():
    """32,000 files named like manifests took 3.1 s (a list was searched per file)."""
    blobs = [f"requirements{i:06d}.txt" for i in range(64_000)]
    trees = [f"dir{i}" for i in range(20_000)]
    (content, files, folders), seconds = _timed(fetch_plan, blobs, trees)
    assert seconds < 1.0, f"{seconds:.2f} s"
    assert len(content) == 64_000 and files == [] and folders == []


# ---------------------------------------------------------------------------
# The detection step is killable and bounded, whatever the input
# ---------------------------------------------------------------------------


def test_isolated_detection_gives_the_same_stack_as_in_process(tmp_path: Path):
    _write(
        tmp_path,
        "pyproject.toml",
        "[project]\nname='x'\ndependencies=['litellm']\n[tool.ruff]\n",
    )
    _write(
        tmp_path,
        WF + "ci.yml",
        "jobs:\n  a:\n    steps:\n      - uses: semgrep/semgrep-action@v1\n",
    )
    _write(tmp_path, "CLAUDE.md", "x")
    assert detect_stack_isolated(tmp_path) == analyzer._build_stack(tmp_path)


def test_detection_that_runs_too_long_is_killed(tmp_path: Path, monkeypatch):
    """Not one of the known inputs: a detector that simply never returns."""
    slow = tmp_path / "slowmod"
    slow.mkdir()
    (slow / "sitecustomize.py").write_text(
        "import pipeline.audit.analyzer as d, time\n"
        "d.detect_languages = lambda root: time.sleep(600)\n"
    )
    monkeypatch.setenv(
        "PYTHONPATH", f"{slow}:{Path(analyzer.__file__).resolve().parents[2]}"
    )
    repo = _write(tmp_path / "repo", "pyproject.toml", "[project]\nname='x'\n")
    started = time.perf_counter()
    with pytest.raises(DetectionAborted) as excinfo:
        detect_stack_isolated(repo, limits=DetectionLimits(seconds=1.0))
    assert time.perf_counter() - started < 5.0
    assert "time" in str(excinfo.value)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="address-space limits are enforced on Linux",
)
def test_detection_that_takes_too_much_memory_is_stopped(
    tmp_path: Path, monkeypatch
):  # pragma: no cover
    hog = tmp_path / "hogmod"
    hog.mkdir()
    (hog / "sitecustomize.py").write_text(
        "import pipeline.audit.analyzer as d\n"
        "d.detect_languages = lambda root: [bytearray(64_000_000) for _ in range(100)] and []\n"
    )
    monkeypatch.setenv(
        "PYTHONPATH", f"{hog}:{Path(analyzer.__file__).resolve().parents[2]}"
    )
    repo = _write(tmp_path / "repo", "pyproject.toml", "[project]\nname='x'\n")
    with pytest.raises(DetectionAborted):
        detect_stack_isolated(
            repo, limits=DetectionLimits(seconds=20.0, memory_bytes=1_000_000_000)
        )


def test_memory_watchdog_stops_a_child_that_grows(tmp_path: Path, monkeypatch):
    """Where the kernel does not enforce an address-space limit (macOS),
    a watchdog thread in the child ends it once it has grown too much."""
    hog = tmp_path / "hogmod"
    hog.mkdir()
    (hog / "sitecustomize.py").write_text(
        "import pipeline.audit.analyzer as d, time\n"
        "def grow(root):\n"
        "    keep = []\n"
        "    for _ in range(400):\n"
        "        keep.append(b'x' * 8_000_000); time.sleep(0.01)\n"
        "    return []\n"
        "d.detect_languages = grow\n"
    )
    monkeypatch.setenv(
        "PYTHONPATH", f"{hog}:{Path(analyzer.__file__).resolve().parents[2]}"
    )
    repo = _write(tmp_path / "repo", "pyproject.toml", "[project]\nname='x'\n")
    started = time.perf_counter()
    with pytest.raises(DetectionAborted):
        detect_stack_isolated(
            repo, limits=DetectionLimits(seconds=30.0, memory_bytes=600_000_000)
        )
    assert time.perf_counter() - started < 15.0


def test_remote_audit_runs_detection_in_the_child_and_reports_an_abort(monkeypatch):
    calls: list[str] = []
    real = analyzer.detect_stack_isolated

    def spy(root, **kwargs):
        calls.append("isolated")
        return real(root, **kwargs)

    monkeypatch.setattr(analyzer, "detect_stack_isolated", spy)
    files = {"pyproject.toml": b"[project]\nname='x'\ndependencies=['litellm']\n"}
    report = audit_repo("https://github.com/o/r", client=FakeGitHub(files))
    assert calls == ["isolated"]
    assert {t.id for t in report.stack.supervision_tools} == {"litellm"}

    def aborted(root, **kwargs):
        raise DetectionAborted(
            "The repository's files could not be analysed within the time limit."
        )

    monkeypatch.setattr(analyzer, "detect_stack_isolated", aborted)
    with pytest.raises(DetectionAborted):
        audit_repo("https://github.com/o/r", client=FakeGitHub(files))


def test_the_two_review_inputs_through_a_remote_audit_are_fast_and_harmless():
    files = {
        "setup.py": b"install_requires=[" * 28_400,  # 512 kB
        WF + "a.yml": merge_bomb(7).encode(),
        "requirements.txt": b"litellm\n",
    }
    report, seconds = _timed(
        lambda: audit_repo("https://github.com/o/r", client=FakeGitHub(files))
    )
    assert seconds < 5.0
    assert {t.id for t in report.stack.supervision_tools} == {"litellm"}


def test_local_audit_in_process_is_unchanged(tmp_path: Path):
    _write(tmp_path, "requirements.txt", "litellm\n")
    report = audit_repo_local(tmp_path, repo_url="https://github.com/o/r")
    assert {t.id for t in report.stack.supervision_tools} == {"litellm"}
