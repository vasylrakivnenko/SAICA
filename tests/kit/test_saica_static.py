"""Tests for the static-check wrapper of the kit (site/public/kit/saica_static.py).

The wrapper runs a checker on the changed files and applies the flag rule the
benchmark used for programs: a finding counts only when it has a counted code
and sits on a line the change added (review issue I1 / KT-01).

No network and no real checker is needed: the tools are small fake executables
that print canned output in each tool's real format. Three tests run the real
ruff / mypy / bandit when a binary is found and are skipped otherwise.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "site" / "public" / "kit"
STATIC = KIT / "saica_static.py"


def _load(name: str, filename: str):
    # No bytecode: site/public/ is published as is (see test_saica_kit.py).
    spec = importlib.util.spec_from_file_location(name, str(KIT / filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # NamedTuple classes look their module up by name
    prev, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


st = _load("saica_static_kit", "saica_static.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("GIT_") or key.startswith("SAICA_"):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    root = tmp_path / "repo"
    root.mkdir()
    gitc(root, "init", "-q")
    gitc(root, "config", "user.name", "Test Human")
    gitc(root, "config", "user.email", "human@example.invalid")
    gitc(root, "config", "commit.gpgsign", "false")
    monkeypatch.chdir(root)
    return root


def gitc(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def fake_tool(tmp_path, name, stdout="", rc=0, stderr=""):
    """An executable that prints canned output and logs its arguments."""
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    out, log = d / (name + ".out"), d / (name + ".argv")
    out.write_text(stdout)
    script = d / name
    script.write_text(
        "#!%s\nimport json, sys\n"
        "open(%r, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.stdout.write(open(%r).read())\nsys.stderr.write(%r)\nsys.exit(%d)\n"
        % (sys.executable, str(log), str(out), stderr, rc)
    )
    script.chmod(0o755)
    return script, log


def run_static(*args, cwd=None, python=sys.executable, stdin=None):
    r = subprocess.run(
        [python, "-B", str(STATIC), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        input=stdin,
        timeout=120,
    )
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return r.returncode, (lines[-1] if lines else ""), r


def calls(log):
    return (
        [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []
    )


FAB_CODES = "name-defined,import-not-found,attr-defined,call-arg,import"
MYPY_OLD = (
    'app.py:2:1: error: Cannot find implementation or library stub for module named "old_missing"'
    "  [import-not-found]\n"
)
MYPY_NEW = (
    'app.py:6:5: error: Module "os" has no attribute "no_such_call"  [attr-defined]\n'
)
MYPY_STYLE = 'app.py:7:5: error: Returning Any from function declared to return "int"  [no-any-return]\n'
MYPY_NOTE = "app.py:6:5: note: See https://mypy.readthedocs.io/en/stable/\n"


def kt01_repo(repo):
    """One error that was there before, then a change that adds lines 5-7."""
    (repo / "app.py").write_text("import os\nimport old_missing\n\nX = 1\n")
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "base")
    with (repo / "app.py").open("a") as fh:
        fh.write("def f() -> int:\n    os.no_such_call()\n    return X\n")
    gitc(repo, "add", "-A")


# ---------------------------------------------------------------------------
# The flag rule (KT-01)
# ---------------------------------------------------------------------------


def test_only_counted_codes_on_added_lines_flag(repo, tmp_path):
    kt01_repo(repo)
    tool, log = fake_tool(
        tmp_path, "mypy", MYPY_OLD + MYPY_NEW + MYPY_NOTE + MYPY_STYLE, rc=1
    )
    base = ["--tool", "mypy", "--tool-bin", str(tool), "--staged"]
    rc, line, _ = run_static(*base, "--codes", FAB_CODES, "--added-lines-only")
    assert rc == 1
    assert line.startswith("flagged: app.py:6 attr-defined")
    assert "old_missing" not in line and "no-any-return" not in line
    # what the tool was run as: the wrapper's fixed options, then the file
    argv = calls(log)[0]
    assert argv[:4] == [
        "--show-error-codes",
        "--no-error-summary",
        "--no-color-output",
        "--show-column-numbers",
    ]
    assert argv[-2:] == ["--", "./app.py"]  # anchored, and after the options


def test_a_pre_existing_error_alone_does_not_flag(repo, tmp_path):
    """The exit-code rule flagged this change (the checker exits 1); the benchmark rule does not."""
    kt01_repo(repo)
    tool, _log = fake_tool(tmp_path, "mypy", MYPY_OLD + MYPY_STYLE, rc=1)
    rc, line, _ = run_static(
        "--tool", "mypy", "--tool-bin", str(tool), "--staged",
        "--codes", FAB_CODES, "--added-lines-only",
    )  # fmt: skip
    assert rc == 0
    assert line == (
        "ok: mypy found 2 finding(s) in 1 file(s); none with a counted code on an added line"
    )


def test_without_added_lines_only_every_line_of_a_changed_file_counts(repo, tmp_path):
    kt01_repo(repo)
    tool, _log = fake_tool(tmp_path, "mypy", MYPY_OLD + MYPY_NEW, rc=1)
    rc, line, _ = run_static(
        "--tool", "mypy", "--tool-bin", str(tool), "--staged", "--codes", FAB_CODES
    )
    assert rc == 1
    assert "app.py:2 import-not-found" in line and "app.py:6 attr-defined" in line


def test_without_codes_every_finding_on_an_added_line_counts(repo, tmp_path):
    kt01_repo(repo)
    tool, _log = fake_tool(tmp_path, "mypy", MYPY_OLD + MYPY_STYLE, rc=1)
    rc, line, _ = run_static(
        "--tool", "mypy", "--tool-bin", str(tool), "--staged", "--added-lines-only"
    )
    assert rc == 1 and line.startswith("flagged: app.py:7 no-any-return")


def test_clean_tool_output_is_ok(repo, tmp_path):
    kt01_repo(repo)
    tool, _log = fake_tool(tmp_path, "mypy", "", rc=0)
    rc, line, _ = run_static("--tool", "mypy", "--tool-bin", str(tool), "--staged")
    assert rc == 0 and line == "ok: mypy found no findings in 1 file(s)"


def test_tool_args_and_python_are_passed_through(repo, tmp_path):
    kt01_repo(repo)
    tool, log = fake_tool(tmp_path, "mypy", "", rc=0)
    rc, _line, _ = run_static(
        "--tool", "mypy", "--tool-bin", str(tool), "--staged",
        "--tool-arg=--check-untyped-defs", "--tool-arg=--follow-imports=silent",
        "--python", sys.executable,
    )  # fmt: skip
    assert rc == 0
    argv = calls(log)[0]
    assert "--check-untyped-defs" in argv and "--follow-imports=silent" in argv
    assert argv[argv.index("--python-executable") + 1] == sys.executable
    assert "--exit-zero" not in argv


# ---------------------------------------------------------------------------
# Codes, severity, extensions
# ---------------------------------------------------------------------------


def ruff_json(repo, items):
    return json.dumps(
        [
            {
                "code": code,
                "message": msg,
                "filename": str(repo / path),
                "location": {"row": row, "column": 1},
                "end_location": {"row": row, "column": 5},
                "fix": None,
                "noqa_row": row,
                "url": None,
            }
            for path, row, code, msg in items
        ]
    )


def test_codes_prefix_and_exact_match(repo, tmp_path):
    (repo / "calc.py").write_text(
        "import numpy as np\nimport os\nx = np.product([1])\n"
    )
    gitc(repo, "add", "-A")
    out = ruff_json(
        repo,
        [
            ("calc.py", 2, "F401", "`os` imported but unused"),
            (
                "calc.py",
                3,
                "NPY003",
                "`np.product` is deprecated; use `np.prod` instead",
            ),
        ],
    )
    tool, log = fake_tool(tmp_path, "ruff", out, rc=1)
    base = ["--tool", "ruff", "--tool-bin", str(tool), "--staged", "--added-lines-only"]
    rc, line, _ = run_static(*base, "--codes", "NPY*")
    assert rc == 1 and "calc.py:3 NPY003" in line and "F401" not in line
    rc, line, _ = run_static(*base, "--codes", "f401")  # case does not matter
    assert rc == 1 and "calc.py:2 F401" in line and "NPY003" not in line
    rc, line, _ = run_static(*base, "--codes", "E501,B*")
    assert rc == 0 and line.startswith("ok: ruff found 2 finding(s)")
    assert calls(log)[0][:3] == ["check", "--output-format", "json"]


def test_severity_filter_with_pyright_output(repo, tmp_path):
    (repo / "m.py").write_text("import nope\nx: int = 'a'\n")
    gitc(repo, "add", "-A")
    out = json.dumps(
        {
            "version": "1.1.414",
            "generalDiagnostics": [
                {
                    "file": str(repo / "m.py"),
                    "severity": "warning",
                    "message": 'Import "nope" could not be resolved from source',
                    "range": {
                        "start": {"line": 0, "character": 7},
                        "end": {"line": 0, "character": 11},
                    },
                    "rule": "reportMissingModuleSource",
                },
                {
                    "file": str(repo / "m.py"),
                    "severity": "error",
                    "message": 'Type "str" is not assignable to declared type "int"',
                    "range": {
                        "start": {"line": 1, "character": 9},
                        "end": {"line": 1, "character": 12},
                    },
                    "rule": "reportAssignmentType",
                },
            ],
            "summary": {"filesAnalyzed": 1, "errorCount": 1, "warningCount": 1},
        }
    )
    tool, log = fake_tool(tmp_path, "pyright", out, rc=1)
    base = [
        "--tool",
        "pyright",
        "--tool-bin",
        str(tool),
        "--staged",
        "--added-lines-only",
    ]
    rc, line, _ = run_static(*base, "--severity", "error")
    assert rc == 1 and "m.py:2 reportAssignmentType" in line
    assert "reportMissingModuleSource" not in line
    rc, line, _ = run_static(
        *base, "--severity", "error", "--codes", "reportMissingModuleSource"
    )
    assert rc == 0
    rc, line, _ = run_static(*base)
    assert rc == 1 and "m.py:1 reportMissingModuleSource" in line
    assert calls(log)[0][0] == "--outputjson"


def test_only_matching_extensions_are_handed_to_the_tool(repo, tmp_path):
    (repo / "a.py").write_text("x = 1\n")
    (repo / "notes.md").write_text("# notes\n")
    (repo / "run.sh").write_text("echo hi\n")
    gitc(repo, "add", "-A")
    tool, log = fake_tool(tmp_path, "ruff", "[]", rc=0)
    rc, _line, _ = run_static("--tool", "ruff", "--tool-bin", str(tool), "--staged")
    assert rc == 0 and calls(log)[-1][3:] == ["--", "./a.py"]
    rc, _line, _ = run_static(
        "--tool", "ruff", "--tool-bin", str(tool), "--staged", "--ext", ".sh,md"
    )
    assert rc == 0 and calls(log)[-1][3:] == ["--", "./notes.md", "./run.sh"]
    gitc(repo, "commit", "-q", "-m", "one")
    (repo / "notes.md").write_text("# notes\nmore\n")
    gitc(repo, "add", "-A")
    rc, line, _ = run_static("--tool", "ruff", "--tool-bin", str(tool), "--staged")
    assert rc == 0 and line == "skipped: no changed .py, .pyi files for ruff"


# ---------------------------------------------------------------------------
# Parsers, on output in each tool's real format
# ---------------------------------------------------------------------------


def test_parse_mypy():
    out = (
        MYPY_OLD
        + MYPY_NOTE
        + 'pkg/b.py:10: error: Name "undefined_name" is not defined  [name-defined]\n'
    )
    findings, unparsed = st.parse_mypy(out, "", 1)
    assert [(f.path, f.line, f.code, f.severity) for f in findings] == [
        ("app.py", 2, "import-not-found", "error"),
        ("pkg/b.py", 10, "name-defined", "error"),
    ]
    assert unparsed == []
    with pytest.raises(st.ToolFailure):
        st.parse_mypy(
            "", "mypy: can't read file 'x.py': No such file or directory\n", 1
        )


def test_parse_bandit():
    out = json.dumps(
        {
            "errors": [
                {
                    "filename": "bad.py",
                    "reason": "syntax error while parsing AST from file",
                }
            ],
            "results": [
                {
                    "filename": "./app.py",
                    "line_number": 4,
                    "test_id": "B602",
                    "test_name": "subprocess_popen_with_shell_equals_true",
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "issue_text": "subprocess call with shell=True identified, security issue.",
                }
            ],
        }
    )
    findings, unparsed = st.parse_bandit(out, "", 1)
    assert [(f.path, f.line, f.code, f.severity) for f in findings] == [
        ("./app.py", 4, "B602", "HIGH")
    ]
    assert unparsed == [("bad.py", "syntax error while parsing AST from file")]
    with pytest.raises(st.ToolFailure):
        st.parse_bandit("Traceback (most recent call last):\n", "", 1)


def test_parse_semgrep_and_last_part_of_rule_id():
    out = json.dumps(
        {
            "errors": [],
            "paths": {"scanned": ["app.py"]},
            "results": [
                {
                    "check_id": "python.lang.security.audit.eval-detected.eval-detected",
                    "path": "app.py",
                    "start": {"line": 9, "col": 5, "offset": 120},
                    "end": {"line": 9, "col": 15, "offset": 130},
                    "extra": {
                        "severity": "WARNING",
                        "message": "Detected the use of eval().",
                    },
                }
            ],
        }
    )
    findings, unparsed = st.parse_semgrep(out, "", 0)
    assert [(f.path, f.line, f.severity) for f in findings] == [
        ("app.py", 9, "WARNING")
    ]
    assert unparsed == []
    code = findings[0].code
    assert st.code_matches(code, ["eval-detected"], "semgrep")
    assert st.code_matches(code, ["python.lang.security.*"], "semgrep")
    assert not st.code_matches(code, ["exec-detected"], "semgrep")
    broken = json.dumps(
        {"results": [], "errors": [{"level": "error", "message": "invalid rule"}]}
    )
    with pytest.raises(st.ToolFailure):
        st.parse_semgrep(broken, "", 0)


def test_parse_ruff_and_pyright_reject_other_output():
    for parse in (st.parse_ruff, st.parse_pyright):
        with pytest.raises(st.ToolFailure):
            parse("error: unexpected argument '--frobnicate' found\n", "", 0)
    findings, unparsed = st.parse_ruff(
        json.dumps(
            [{"code": None, "message": "SyntaxError: Expected an expression", "filename": "/r/x.py",
              "location": {"row": 3, "column": 1}}]
        ),
        "",
        1,
    )  # fmt: skip
    assert findings[0].code == "syntax" and unparsed == [
        ("/r/x.py", "line 3: SyntaxError: Expected an expression")
    ]


def test_added_lines_parser():
    diff = (
        "diff --git a/a.py b/a.py\nindex 1..2 100644\n--- a/a.py\n+++ b/a.py\n"
        "@@ -1,0 +2,2 @@\n+x = 1\n+++ not a header\n@@ -9 +11 @@\n-old\n+new\n\\ No newline at end of file\n"
        'diff --git "a/sp ace\\303\\274.py" "b/sp ace\\303\\274.py"\n--- "a/sp ace\\303\\274.py"\n'
        '+++ "b/sp ace\\303\\274.py"\n@@ -0,0 +1 @@\n+y = 2\n'
        "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\n--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-z\n"
        "diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n"
    )
    assert st.parse_added_lines(diff) == {"a.py": {2, 3, 11}, "sp aceü.py": {1}}


# ---------------------------------------------------------------------------
# Which change: staged, a commit, a root commit, a diff file, a rename
# ---------------------------------------------------------------------------


def test_commit_root_commit_and_diff_file(repo, tmp_path):
    (repo / "a.py").write_text("x = 1\nimport nope_a\n")
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "root")
    (repo / "b.py").write_text("import nope_b\n")
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "second")
    out = (
        'a.py:2:1: error: Cannot find implementation or library stub for module named "nope_a"  [import-not-found]\n'
        'b.py:1:1: error: Cannot find implementation or library stub for module named "nope_b"  [import-not-found]\n'
    )
    tool, log = fake_tool(tmp_path, "mypy", out, rc=1)
    base = [
        "--tool",
        "mypy",
        "--tool-bin",
        str(tool),
        "--added-lines-only",
        "--codes",
        FAB_CODES,
    ]
    rc, line, _ = run_static(
        *base
    )  # default outside pre-commit: HEAD against its parent
    assert rc == 1 and "b.py:1" in line and "a.py" not in line
    assert calls(log)[-1][-1] == "./b.py"
    rc, line, _ = run_static(
        *base, "--commit", "HEAD~1"
    )  # the root commit: everything is new
    assert rc == 1 and "a.py:2" in line and "b.py" not in line
    diff = gitc(repo, "diff", "HEAD~1", "HEAD")
    (tmp_path / "change.diff").write_text(diff)
    rc, line, _ = run_static(*base, "--diff-file", str(tmp_path / "change.diff"))
    assert rc == 1 and "b.py:1" in line and "a.py" not in line
    rc, line, _ = run_static(*base, "--diff-file", "-", stdin=diff)
    assert rc == 1 and "b.py:1" in line
    rc, line, _ = run_static(*base, "--commit", "no-such-rev")
    assert rc == 127 and line.startswith("error: not a commit")


def test_staged_is_the_default_inside_the_runner(repo, tmp_path, monkeypatch):
    (repo / "a.py").write_text("x = 1\n")
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "root")
    (repo / "b.py").write_text("import nope_b\n")
    gitc(repo, "add", "-A")
    out = 'b.py:1:1: error: Cannot find module "nope_b"  [import-not-found]\n'
    tool, _log = fake_tool(tmp_path, "mypy", out, rc=1)
    monkeypatch.setenv(
        "SAICA_REPO_ROOT", str(repo)
    )  # as saica_check.py run --staged sets it
    rc, line, _ = run_static(
        "--tool", "mypy", "--tool-bin", str(tool), "--added-lines-only"
    )
    assert rc == 1 and "b.py:1" in line


def test_a_file_that_was_only_renamed_has_no_added_lines(repo, tmp_path):
    (repo / "old_name.py").write_text("import nope\n" + "x = 1\n" * 20)
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "base")
    gitc(repo, "mv", "old_name.py", "new_name.py")
    tool, log = fake_tool(
        tmp_path, "mypy", "new_name.py:1:1: error: boom  [import-not-found]\n", rc=1
    )
    rc, line, _ = run_static(
        "--tool", "mypy", "--tool-bin", str(tool), "--staged", "--added-lines-only"
    )
    assert rc == 0 and line.startswith("skipped:")
    assert calls(log) == []  # the tool was not even started


def test_no_changes_is_skipped(repo, tmp_path):
    (repo / "a.py").write_text("x = 1\n")
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "base")
    tool, _log = fake_tool(tmp_path, "ruff", "[]")
    rc, line, _ = run_static("--tool", "ruff", "--tool-bin", str(tool), "--staged")
    assert rc == 0 and line.startswith("skipped: no changes to check")


# ---------------------------------------------------------------------------
# A tool failure is an error: never ok, never a finding
# ---------------------------------------------------------------------------


def test_missing_tool_is_an_error(repo, tmp_path):
    kt01_repo(repo)
    rc, line, _ = run_static(
        "--tool", "mypy", "--tool-bin", "saica-no-such-binary-xyz", "--staged"
    )
    assert rc == 127 and line.startswith("error:") and "not installed" in line
    rc, line, _ = run_static(
        "--tool", "mypy", "--tool-bin", "./no/such/path", "--staged"
    )
    assert rc == 127 and line.startswith("error:")


@pytest.mark.parametrize(
    "name, stdout, stderr, tool_rc",
    [
        (
            "mypy",
            "",
            "usage: mypy [-h] ...\nmypy: error: unrecognized arguments: --frobnicate\n",
            2,
        ),
        ("ruff", "", "error: unexpected argument '--frobnicate' found\n", 2),
        ("pyright", "", "No configuration file found.\nenoent\n", 3),
        ("bandit", "", "Traceback (most recent call last):\nRuntimeError: boom\n", 2),
        (
            "semgrep",
            json.dumps(
                {
                    "results": [],
                    "errors": [{"level": "error", "message": "invalid config"}],
                }
            ),
            "",
            7,
        ),
        ("ruff", "this is not JSON", "", 0),
        ("pyright", "{}", "", 0),
        ("mypy", "", "", -9 % 256),
    ],
)
def test_tool_failures_are_errors(repo, tmp_path, name, stdout, stderr, tool_rc):
    kt01_repo(repo)
    tool, _log = fake_tool(tmp_path, name, stdout, rc=tool_rc, stderr=stderr)
    rc, line, _ = run_static(
        "--tool", name, "--tool-bin", str(tool), "--staged", "--added-lines-only"
    )
    assert rc == 127, line
    assert line.startswith("error:")
    rc, _line, _ = run_static(
        "--tool", name, "--tool-bin", str(tool), "--staged", "--error-exit", "3"
    )
    assert rc == 3


def test_tool_timeout_is_an_error(repo, tmp_path):
    kt01_repo(repo)
    d = tmp_path / "fakebin"
    d.mkdir()
    slow = d / "ruff"
    slow.write_text("#!/bin/sh\nsleep 30\n")
    slow.chmod(0o755)
    rc, line, _ = run_static(
        "--tool", "ruff", "--tool-bin", str(slow), "--staged", "--timeout", "1"
    )
    assert rc == 127 and "timed out" in line


def test_bad_arguments_are_errors_not_findings(repo):
    for args in (
        ["--tool", "eslint"],
        [],
        ["--tool", "mypy", "--error-exit", "1"],
        ["--tool", "mypy", "--timeout", "0"],
    ):
        rc, line, _ = run_static(*args)
        assert rc == 127 and line.startswith("error:"), (args, line)


def test_outside_a_repository_is_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    rc, line, _ = run_static("--tool", "ruff", cwd=tmp_path)
    assert rc == 127 and line.startswith("error:")


# ---------------------------------------------------------------------------
# File names
# ---------------------------------------------------------------------------


def test_odd_file_names_reach_the_tool_as_plain_arguments(repo, tmp_path):
    names = ["sp ace.py", "-dash.py", "it's $(touch PWNED).py", "ünï.py"]
    for n in names:
        (repo / n).write_text("import nope\n")
    gitc(repo, "add", "-A")
    out = "".join(
        "%s:1:1: error: nope  [import-not-found]\n" % n
        for n in ["sp ace.py", "./-dash.py"]
    )
    tool, log = fake_tool(tmp_path, "mypy", out, rc=1)
    rc, line, _ = run_static(
        "--tool",
        "mypy",
        "--tool-bin",
        str(tool),
        "--staged",
        "--added-lines-only",
        "--codes",
        FAB_CODES,
    )
    assert rc == 1 and "-dash.py:1" in line and "sp ace.py:1" in line
    argv = calls(log)[0][4:]
    assert argv[0] == "--" and sorted(argv[1:]) == sorted(
        ["./sp ace.py", "./-dash.py", "./it's $(touch PWNED).py", "./ünï.py"]
    )
    assert not (repo / "PWNED").exists()


def test_a_file_name_with_a_newline_runs_nothing_and_is_not_ok(repo, tmp_path):
    marker = repo / "INJECTED_BY_FILENAME"
    evil = "zz\ntouch INJECTED_BY_FILENAME\n.py"
    (repo / evil).write_text("import nope\n")
    (repo / "ok.py").write_text("x = 1\n")
    gitc(repo, "add", "-A")
    tool, log = fake_tool(tmp_path, "mypy", "", rc=0)
    rc, line, _ = run_static("--tool", "mypy", "--tool-bin", str(tool), "--staged")
    assert not marker.exists()
    assert rc == 127 and line.startswith("error:") and "not checked" in line
    assert "\n" not in line
    assert calls(log)[0][4:] == [
        "--",
        "./ok.py",
    ]  # the odd name was never handed to the tool


def test_three_thousand_files_are_checked_in_batches(repo, tmp_path):
    (repo / "pkg").mkdir()
    names = [
        "pkg/module_with_a_rather_long_file_name_%04d_for_batching.py" % i
        for i in range(3000)
    ]
    for n in names:
        (repo / n).write_text("x = 1\n")
    gitc(repo, "add", "-A")
    tool, log = fake_tool(tmp_path, "ruff", "[]", rc=0)
    rc, line, _ = run_static("--tool", "ruff", "--tool-bin", str(tool), "--staged")
    assert rc == 0 and line == "ok: ruff found no findings in 3000 file(s)"
    runs = calls(log)
    assert len(runs) >= 2
    assert all(argv[3] == "--" for argv in runs)
    assert sorted(f[2:] for argv in runs for f in argv[4:]) == sorted(names)
    assert max(sum(len(a) + 1 for a in argv) for argv in runs) < 110000


def test_findings_in_files_outside_the_change_are_ignored(repo, tmp_path):
    kt01_repo(repo)
    out = "other.py:1:1: error: nope  [import-not-found]\n" + MYPY_OLD
    tool, _log = fake_tool(tmp_path, "mypy", out, rc=1)
    rc, line, _ = run_static(
        "--tool", "mypy", "--tool-bin", str(tool), "--staged", "--codes", FAB_CODES
    )
    assert rc == 1 and "other.py" not in line and "app.py:2" in line


# ---------------------------------------------------------------------------
# Through the kit runner, and under Python 3.9
# ---------------------------------------------------------------------------


def test_through_saica_check_run_staged(repo, tmp_path):
    """The entry the builder writes: no {files}, benchmark rule, right outcome."""
    import shlex

    saica = repo / ".saica"
    saica.mkdir()
    shutil.copy2(str(KIT / "saica_check.py"), str(saica / "saica_check.py"))
    shutil.copy2(str(STATIC), str(saica / "saica_static.py"))
    tool, _log = fake_tool(tmp_path, "mypy", MYPY_OLD + MYPY_NEW, rc=1)
    quiet, _log2 = fake_tool(tmp_path, "ruff", "[]", rc=0)
    cmd = "%s .saica/saica_static.py --tool %s --tool-bin %s --codes %s --added-lines-only"
    config = {
        "version": 1,
        "builtin": {"enabled": False},
        "tools": [
            {
                "id": "fabrication-mypy",
                "failure_modes": ["fabrication"],
                "command": cmd
                % (
                    shlex.quote(sys.executable),
                    "mypy",
                    shlex.quote(str(tool)),
                    FAB_CODES,
                ),
            },
            {
                "id": "ruff-clean",
                "failure_modes": ["obsolescence"],
                "command": cmd
                % (
                    shlex.quote(sys.executable),
                    "ruff",
                    shlex.quote(str(quiet)),
                    "NPY*",
                ),
            },
            {
                "id": "not-installed",
                "failure_modes": ["logic_error"],
                "blocking": True,
                "on_error": "pass",  # (by default a blocking check that cannot run blocks)
                "command": "%s .saica/saica_static.py --tool pyright --tool-bin saica-no-such-binary"
                % shlex.quote(sys.executable),
            },
        ],
    }
    (saica / "checks.json").write_text(json.dumps(config))
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "kit")
    kt01_repo(repo)
    r = subprocess.run(
        [sys.executable, "-B", ".saica/saica_check.py", "run", "--staged"],
        cwd=repo, capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    events = [
        json.loads(ln) for ln in (saica / "pending.jsonl").read_text().splitlines()
    ]
    by = {e["tool_id"]: e for e in events if e["tool_id"]}
    assert by["fabrication-mypy"]["outcome"] == "caught"
    assert by["fabrication-mypy"]["detail"].startswith("flagged: app.py:6 attr-defined")
    assert by["ruff-clean"]["outcome"] == "pass"
    assert by["ruff-clean"]["detail"].startswith("ok: ruff found no findings")
    assert (
        by["not-installed"]["outcome"] == "error"
    )  # and it did not block (exit 0 above)
    assert by["not-installed"]["detail"].startswith("error:")


def test_cli_runs_under_python_3_9(repo, tmp_path):
    py39 = "/usr/bin/python3"
    if not os.path.exists(py39):
        pytest.skip("no /usr/bin/python3")
    v = subprocess.run(
        [py39, "-c", "import sys; print(sys.version_info[:2])"],
        capture_output=True,
        text=True,
    )
    if "(3, 9)" not in v.stdout:
        pytest.skip("/usr/bin/python3 is not Python 3.9")
    kt01_repo(repo)
    tool, _log = fake_tool(tmp_path, "mypy", MYPY_OLD + MYPY_NEW, rc=1)
    rc, line, _ = run_static(
        "--tool", "mypy", "--tool-bin", str(tool), "--staged", "--codes", FAB_CODES, "--added-lines-only",
        python=py39,
    )  # fmt: skip
    assert rc == 1 and line.startswith("flagged: app.py:6 attr-defined")
    rc, _line, r = run_static("--help", python=py39)
    assert rc == 0 and "--added-lines-only" in r.stdout


# ---------------------------------------------------------------------------
# Real binaries, when one is around (skipped otherwise)
# ---------------------------------------------------------------------------


def _real(name):
    for cand in (
        shutil.which(name),
        str(REPO / ".venv" / "bin" / name),
        str(REPO / "bench" / "security" / ".venv" / "bin" / name),
    ):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    pytest.skip("no %s binary found" % name)


def _real_repo(repo):
    (repo / "app.py").write_text(
        "import os\nimport subprocess\n\n\ndef old():\n    return undefined_before\n"
    )
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "base")
    with (repo / "app.py").open("a") as fh:
        fh.write(
            "\n\ndef new(cmd):\n    subprocess.call(cmd, shell=True)\n    return undefined_now\n"
        )
    gitc(repo, "add", "-A")


def test_real_ruff(repo):
    ruff = _real("ruff")
    _real_repo(repo)
    base = [
        "--tool",
        "ruff",
        "--tool-bin",
        ruff,
        "--staged",
        "--tool-arg=--isolated",
        "--tool-arg=--no-cache",
    ]
    rc, line, _ = run_static(*base, "--codes", "F821", "--added-lines-only")
    assert rc == 1 and "app.py:11 F821" in line and "app.py:6" not in line, line
    rc, line, _ = run_static(*base, "--codes", "F821")
    assert rc == 1 and "app.py:6 F821" in line and "app.py:11 F821" in line
    rc, line, _ = run_static(*base, "--codes", "NPY*", "--added-lines-only")
    assert rc == 0 and line.startswith("ok: ruff found"), line
    rc, line, _ = run_static(*base, "--tool-arg=--no-such-option")
    assert rc == 127 and line.startswith("error:")


def test_real_mypy(repo):
    mypy = _real("mypy")
    _real_repo(repo)
    base = ["--tool", "mypy", "--tool-bin", mypy, "--staged", "--tool-arg=--cache-dir=/dev/null",
            "--tool-arg=--check-untyped-defs"]  # fmt: skip
    rc, line, _ = run_static(*base, "--codes", FAB_CODES, "--added-lines-only")
    assert rc == 1 and "app.py:11 name-defined" in line and "app.py:6" not in line, line
    rc, line, _ = run_static(*base, "--codes", "deprecated", "--added-lines-only")
    assert rc == 0 and line.startswith("ok: mypy found"), line


def test_real_bandit(repo):
    bandit = _real("bandit")
    _real_repo(repo)
    base = ["--tool", "bandit", "--tool-bin", bandit, "--staged", "--added-lines-only"]
    rc, line, _ = run_static(*base)
    assert rc == 1 and "app.py:10 B602" in line, line
    rc, line, _ = run_static(*base, "--codes", "B101")
    assert rc == 0 and line.startswith("ok: bandit found"), line
