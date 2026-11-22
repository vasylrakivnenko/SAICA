"""Tests for the SAICA supervision kit runner (site/public/kit/saica_check.py).

The kit files are standalone scripts meant to be copied into other repos, so
they are loaded by path rather than imported as a package.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2] / "site" / "public" / "kit"


def _load(name: str, filename: str):
    # No bytecode: site/public/ is copied verbatim into site/dist/ by the
    # Astro build, so a site/public/kit/__pycache__/ left behind by this
    # test run would otherwise be published at https://saica.ai/kit/.
    spec = importlib.util.spec_from_file_location(name, str(KIT / filename))
    mod = importlib.util.module_from_spec(spec)
    prev, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


sc = _load("saica_check_kit", "saica_check.py")
selftest = _load("saica_selftest_kit", "selftest.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_git_env(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))


@pytest.fixture
def repo(tmp_path, clean_git_env, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()

    gitc(root, "init", "-q")
    gitc(root, "config", "user.name", "Test Human")
    gitc(root, "config", "user.email", "human@example.invalid")
    gitc(root, "config", "commit.gpgsign", "false")
    (root / ".saica").mkdir()
    monkeypatch.chdir(root)
    return root


def gitc(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def cs_from(diffs: dict, files=None):
    """Build a ChangeSet from {path: (added_lines, removed_lines)}."""
    out = {}
    for path, (added, removed) in diffs.items():
        fd = sc.FileDiff(path)
        fd.added = [(i + 1, t) for i, t in enumerate(added)]
        fd.removed = [(i + 1, t) for i, t in enumerate(removed)]
        out[path] = fd
    return sc.ChangeSet(list(files if files is not None else diffs), out)


def tool(command, **kw):
    t = {
        "id": "t",
        "failure_modes": ["logic_error"],
        "runs_per_commit": True,
        "command": command,
        "blocking": False,
        "timeout_s": 30.0,
        "metric": None,
    }
    t.update(kw)
    return t


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_example_config_parses():
    """The example is generated from the benchmark results (tests/kit/test_builder.py checks it against them)."""
    cfg = sc.load_config(KIT / "checks.example.json")
    assert cfg["tools"], "the default kit has at least one check"
    assert cfg["builtin"] == {
        "enabled": True,
        "blocking": False,
        "tamper_blocking": True,
    }
    for t in cfg["tools"]:
        # nothing in the example blocks a commit, and every entry says where its numbers come from
        assert t["blocking"] is False
        assert t["note"] and "Benchmark J" in t["note"]
        assert t["caught_exit_codes"] == [1]
        if t["runs_per_commit"]:
            assert t["command"].startswith("python3 .saica/saica_")


def test_config_defaults():
    cfg = sc.parse_config(
        {
            "version": 1,
            "tools": [{"id": "x", "failure_modes": ["fabrication"], "command": "true"}],
        }
    )
    t = cfg["tools"][0]
    assert t["runs_per_commit"] is True and t["blocking"] is False
    assert t["timeout_s"] == sc.DEFAULT_TIMEOUT_S
    assert cfg["builtin"]["enabled"] is True


@pytest.mark.parametrize(
    "raw, msg",
    [
        ({"version": 2}, "unsupported version"),
        (
            {"tools": [{"id": "x", "failure_modes": ["nope"], "command": "true"}]},
            "unknown failure mode",
        ),
        (
            {"tools": [{"id": "x", "failure_modes": ["fabrication"]}]},
            "'command' is required",
        ),
        ({"tools": [{"id": "x", "failure_modes": []}]}, "non-empty list"),
        (
            {
                "tools": [{"id": "x", "failure_modes": ["fabrication"], "command": "a"}]
                * 2
            },
            "duplicate",
        ),
        (
            {
                "tools": [
                    {"id": "saica:x", "failure_modes": ["fabrication"], "command": "a"}
                ]
            },
            "reserved",
        ),
        (
            {
                "tools": [
                    {
                        "id": "x",
                        "failure_modes": ["fabrication"],
                        "command": "a",
                        "metric": {"name": "q", "regex": "q"},
                    }
                ]
            },
            "capture group",
        ),
    ],
)
def test_config_errors(raw, msg):
    with pytest.raises(sc.SaicaError, match=msg):
        sc.parse_config(raw)


def test_config_invalid_json(tmp_path):
    p = tmp_path / "checks.json"
    p.write_text("{ // comment\n}")
    with pytest.raises(sc.SaicaError, match="not valid JSON"):
        sc.load_config(p)


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------


def test_parse_unified_diff_line_numbers():
    text = (
        "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n"
        "@@ -3 +3,2 @@\n-old\n+new\n++plus-prefixed\n"
        "diff --git a/gone.py b/gone.py\n--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-bye\n"
    )
    d = sc.parse_unified_diff(text)
    assert d["x.py"].added == [(3, "new"), (4, "+plus-prefixed")]
    assert d["x.py"].removed == [(3, "old")]
    assert d["gone.py"].removed == [(1, "bye")]


# ---------------------------------------------------------------------------
# Built-in checks
# ---------------------------------------------------------------------------


def test_stub_markers_positive():
    cs = cs_from(
        {
            "a.py": (
                [
                    "def f():",
                    "    pass",
                    "x = 1  # TODO: fix",
                    "    raise NotImplementedError",
                ],
                [],
            ),
            "b.js": (["// FIXME later"], []),
        }
    )
    hits = sc.check_stub_markers(cs)
    joined = " ".join(hits)
    assert "a.py:2 body-only pass" in joined
    assert "a.py:3 TODO" in joined
    assert "raise NotImplemented" in joined
    assert "b.js:1 FIXME" in joined


def test_stub_markers_negative():
    cs = cs_from(
        {
            "a.py": (
                [
                    'msg = "TODO list app"',  # not a comment
                    "class E(Exception):",
                    "    pass",  # class body, not def
                    "@abstractmethod",
                    "def g(self):",
                    "    ...",
                ],
                ["# TODO removed"],  # removed lines never count
            ),
            "notes.md": (["- TODO: write docs"], []),  # docs skipped
        }
    )
    assert sc.check_stub_markers(cs) == []


def test_test_weakening_removed_assertions():
    cs = cs_from(
        {"tests/test_x.py": (["    x = 1"], ["    assert x == 1", "    assert y"])}
    )
    hits = sc.check_test_weakening(cs)
    assert hits and "removed (2) > added (0)" in hits[0]


def test_test_weakening_skip_markers():
    cs = cs_from(
        {
            "test_a.py": (["@pytest.mark.skip(reason='flaky')"], []),
            "src/a.test.ts": (["it.only('works', () => {})"], []),
        }
    )
    hits = sc.check_test_weakening(cs)
    assert len(hits) == 2


def test_test_weakening_negative():
    cs = cs_from(
        {
            "tests/test_x.py": (
                [
                    "    assert x == 2",
                    "@pytest.mark.skipif(sys.platform == 'win32', reason='posix')",
                ],
                ["    assert x == 1"],
            ),
            "src/app.py": ([], ["assert ok"]),  # not a test file
        }
    )
    assert sc.check_test_weakening(cs) == []


def _phantom_repo(repo):
    (repo / "requirements.txt").write_text(
        "requests>=2\nPyYAML==6.0  # yaml\n-e git+https://x/y#egg=mylib\n"
    )
    (repo / "pyproject.toml").write_text(
        '[project]\ndependencies = ["httpx[http2]>=0.27"]\n'
    )
    (repo / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18", "@scope/ui": "1"}})
    )
    (repo / "localpkg").mkdir()
    (repo / "localpkg" / "__init__.py").write_text("")
    (repo / "helper.py").write_text("")
    gitc(repo, "add", "-A")
    return sc.RepoIndex(repo)


def test_phantom_import_negative(repo):
    index = _phantom_repo(repo)
    cs = cs_from(
        {
            "app.py": (
                [
                    "import os, json",
                    "import requests",
                    "import yaml",
                    "from httpx import Client",
                    "from . import sibling",
                    "from localpkg.sub import thing",
                    "import helper",
                    "import mylib",
                ],
                [],
            ),
            "web/index.ts": (
                [
                    "import React from 'react'",
                    "import { Button } from '@scope/ui/button'",
                    "import fs from 'node:fs'",
                    "import path from 'path'",
                    "import x from './local'",
                    "const y = require('../y')",
                ],
                [],
            ),
        }
    )
    assert sc.check_phantom_imports(cs, index) == []


def test_phantom_import_positive(repo):
    index = _phantom_repo(repo)
    cs = cs_from(
        {
            "app.py": (
                ["import totally_made_up_pkg", "from fakelib.core import x"],
                [],
            ),
            "web/index.ts": (
                [
                    "import left from 'left-padder-9000'",
                    "const z = require('@ghost/pkg')",
                ],
                [],
            ),
        }
    )
    hits = sc.check_phantom_imports(cs, index)
    joined = " ".join(hits)
    assert "totally_made_up_pkg" in joined and "fakelib" in joined
    assert "left-padder-9000" in joined and "@ghost/pkg" in joined


def test_declared_dist_prefix_counts_as_import_name():
    # umap-learn ships `import umap`; seen as a false positive on a real repo.
    names = sc._declared_import_names(["umap-learn", "google-cloud-storage"])
    assert "umap" in names and "google" in names
    assert "beautifulsoup" not in sc._declared_import_names(["requests"])


def test_phantom_import_quiet_without_manifest(repo):
    index = sc.RepoIndex(repo)
    cs = cs_from({"app.py": (["import totally_made_up_pkg"], [])})
    assert sc.check_phantom_imports(cs, index) == []


# ---------------------------------------------------------------------------
# Outcome mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command, outcome",
    [
        ("exit 0", "pass"),
        ("exit 1", "caught"),
        # Only the listed exit codes (default: 1) are findings. A tool that
        # fails for its own reasons (pytest 2-5, ruff 2, a shell syntax error)
        # is an error, never a catch.
        ("exit 2", "error"),
        ("exit 3", "error"),
        ("exit 127", "error"),
        ("definitely-not-a-binary-xyz", "error"),
        ("kill -9 $$", "error"),
    ],
)
def test_tool_outcomes(tmp_path, command, outcome):
    assert sc.run_tool(tool(command), ["a.py"], tmp_path)[0] == outcome


def test_caught_exit_codes_per_tool(tmp_path):
    t = tool("exit 100", caught_exit_codes=[100])
    assert sc.run_tool(t, [], tmp_path)[0] == "caught"
    t = tool("exit 1", caught_exit_codes=[100])
    outcome, detail, _ = sc.run_tool(t, [], tmp_path)
    assert outcome == "error" and "not a finding" in detail and "100" in detail
    cfg = sc.parse_config(
        {
            "tools": [
                {"id": "a", "failure_modes": ["logic_error"], "command": "true"},
                {
                    "id": "b",
                    "failure_modes": ["logic_error"],
                    "command": "true",
                    "caught_exit_codes": [100, 1, 1],
                },
            ]
        }
    )
    assert cfg["tools"][0]["caught_exit_codes"] == [1]
    assert cfg["tools"][1]["caught_exit_codes"] == [1, 100]


@pytest.mark.parametrize("codes", [[], [0], [127], [256], [True], ["1"], 1, [1.5]])
def test_caught_exit_codes_validation(codes):
    raw = {
        "tools": [
            {
                "id": "a",
                "failure_modes": ["logic_error"],
                "command": "true",
                "caught_exit_codes": codes,
            }
        ]
    }
    with pytest.raises(sc.SaicaError, match="caught_exit_codes"):
        sc.parse_config(raw)


def test_missing_python_module_is_an_error_not_a_catch(tmp_path):
    # `python -m <tool>` exits 1 when the tool is not installed: the same code
    # most tools use for a finding. It must not be logged as a catch.
    cmd = "%s -m saica_no_such_module_xyz" % shlex.quote(sys.executable)
    outcome, detail, _ = sc.run_tool(tool(cmd, blocking=True), [], tmp_path)
    assert outcome == "error" and "No module named" in detail


@pytest.mark.parametrize(
    "command, outcome, detail",
    [
        ("echo noise; echo 'ok: nothing found'", "pass", "ok: nothing found"),
        ("echo 'skipped: no Python files'", "skipped", "skipped: no Python files"),
        (
            "echo warn; echo 'flagged: a.py:3 bad'; exit 1",
            "caught",
            "flagged: a.py:3 bad",
        ),
        ("echo 'error: no API key'; exit 127", "error", "error: no API key"),
        ("echo 'partial: half was read'; exit 127", "error", "partial: half was read"),
        ("echo plain output", "pass", ""),
    ],
)
def test_helper_result_lines(tmp_path, command, outcome, detail):
    assert sc.run_tool(tool(command), [], tmp_path)[:2] == (outcome, detail)


def test_timeout_stops_the_tools_children(tmp_path):
    if os.name != "posix":
        pytest.skip("process groups are POSIX only")
    t = tool("sleep 30 & echo $! > child.pid; wait", timeout_s=0.5)
    start = time.time()
    outcome, detail, _ = sc.run_tool(t, [], tmp_path)
    assert outcome == "error" and "timeout" in detail
    assert time.time() - start < 15
    pid = int((tmp_path / "child.pid").read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        pytest.fail("the tool's child process survived the timeout")


def test_tool_timeout(tmp_path):
    out, detail, _ = sc.run_tool(tool("sleep 5", timeout_s=0.3), [], tmp_path)
    assert out == "error" and "timeout" in detail


def test_tool_files_substitution_and_skip(tmp_path):
    t = tool("printf '%s\\n' {files} > out.txt")
    assert sc.run_tool(t, ["a b.py", "c.py"], tmp_path)[0] == "pass"
    assert (tmp_path / "out.txt").read_text().splitlines() == ["a b.py", "c.py"]
    assert sc.run_tool(t, [], tmp_path)[0] == "skipped"
    odd = ["-n.py", "it's $(touch PWNED) `touch PWNED2`.py", "semi;colon&.py"]
    assert sc.run_tool(t, odd, tmp_path)[0] == "pass"
    assert (tmp_path / "out.txt").read_text().splitlines() == ["./-n.py"] + odd[1:]
    assert not (tmp_path / "PWNED").exists() and not (tmp_path / "PWNED2").exists()


EVIL = "zz\ntouch INJECTED_BY_FILENAME\n.py"


@pytest.mark.parametrize(
    "command, where",
    [
        ("echo checked  # benchmark command: use {files} for changed files", "comment"),
        ("sh -c 'echo {files}'", "single quotes"),
        ('echo "{files}"', "double quotes"),
        ("cat <<EOF\n{files}\nEOF", "here-document"),
        ("echo done #{files_from}", "comment"),
    ],
)
def test_files_placeholder_outside_a_plain_word_is_refused(tmp_path, command, where):
    """KT-04: a file name must never reach a place where the shell would run it."""
    outcome, detail, _ = sc.run_tool(tool(command), [EVIL, "a.py"], tmp_path)
    assert outcome == "error"
    assert "configuration error" in detail and where in detail
    assert not (tmp_path / "INJECTED_BY_FILENAME").exists()


@pytest.mark.parametrize(
    "command",
    [
        "printf '%s\\n' {files} # trailing words are fine",
        "printf '%s\\n' 'a # b' {files}",
        'printf "%s\\n" {files}',
        "printf '%s\\n' \\# {files}",
        "printf '%s\\n' x#y {files}",
    ],
)
def test_files_placeholder_as_a_plain_word_is_accepted(tmp_path, command):
    assert sc.placeholder_problem(command) is None
    assert sc.run_tool(tool(command), ["a.py"], tmp_path)[0] == "pass"


def test_paths_with_control_characters_are_refused_for_files(tmp_path):
    for bad in (EVIL, "a\rb.py"):
        t = tool("printf '%s\\n' {files} > out.txt")
        outcome, detail, _ = sc.run_tool(t, ["ok.py", bad], tmp_path)
        assert outcome == "error" and "refused" in detail and "{files_from}" in detail
        assert not (tmp_path / "out.txt").exists()  # the command did not run at all
    assert not (tmp_path / "INJECTED_BY_FILENAME").exists()


def test_files_from_is_a_nul_separated_list(tmp_path):
    reader = (
        "import sys; names = open(sys.argv[1], 'rb').read().split(b'\\0'); "
        "open('out.txt', 'w').write(repr(names))"
    )
    t = tool(
        "%s -c %s {files_from}" % (shlex.quote(sys.executable), shlex.quote(reader))
    )
    files = ["a b.py", "-n.py", EVIL]
    assert sc.run_tool(t, files, tmp_path)[0] == "pass"
    want = [b"a b.py", b"./-n.py", EVIL.encode(), b""]
    assert (tmp_path / "out.txt").read_text() == repr(want)
    assert not (tmp_path / "INJECTED_BY_FILENAME").exists()
    assert sc.run_tool(t, [], tmp_path)[0] == "skipped"


def test_very_long_file_lists(tmp_path):
    """KT-18: 30,000 paths do not fit on a command line; that must be said, not hidden."""
    files = [
        "src/pkg_%05d/module_with_a_long_name_%05d.py" % (i, i) for i in range(30000)
    ]
    outcome, detail, _ = sc.run_tool(tool("true {files}"), files, tmp_path)
    assert outcome == "error" and "too many changed files" in detail
    assert "{files_from}" in detail
    count = "import sys; print(len(open(sys.argv[1], 'rb').read().split(b'\\0')) - 1)"
    t = tool(
        "%s -c %s {files_from}" % (shlex.quote(sys.executable), shlex.quote(count)),
        metric={"name": "n", "regex": r"^(\d+)$"},
    )
    outcome, _detail, metric = sc.run_tool(t, files, tmp_path)
    assert outcome == "pass" and metric == 30000


def test_newline_path_in_a_scratch_repository(repo):
    """KT-04 end to end: the builder's old draft comment plus a hostile directory name."""
    marker = repo / "INJECTED_BY_FILENAME"
    _write_cfg(
        repo,
        [
            {
                "id": "draft",
                "failure_modes": ["fabrication"],
                "command": "true  # benchmark command: adapt paths, keep the flags; "
                "use {files} for changed files",
            },
            {
                "id": "plain",
                "failure_modes": ["logic_error"],
                "command": "true {files}",
            },
        ],
    )
    # Tools run in a temporary checkout; SAICA_REPO_ROOT names the real one.
    evil_dir = repo / "zz\ntouch $SAICA_REPO_ROOT" / "INJECTED_BY_FILENAME\n"
    evil_dir.mkdir(parents=True)
    (evil_dir / "x.py").write_text("x = 1\n")
    gitc(repo, "add", "-A")
    assert sc.main(["run", "--staged"]) == 0
    assert not marker.exists()
    pending = {
        e["tool_id"]: e for e in sc.read_jsonl(repo / ".saica" / "pending.jsonl")
    }
    assert pending["draft"]["outcome"] == "error"
    assert "configuration error" in pending["draft"]["detail"]
    # A command without shell operators runs without a shell: the odd name is
    # one plain argument there, so nothing has to be refused.
    assert pending["plain"]["outcome"] == "pass"


def test_tool_metric(tmp_path):
    t = tool(
        "echo 'quality: 8.25'; exit 1",
        metric={"name": "quality", "regex": r"quality[^0-9]*([0-9.]+)"},
    )
    outcome, _detail, metric = sc.run_tool(t, [], tmp_path)
    assert outcome == "caught" and metric == 8.25


# ---------------------------------------------------------------------------
# not_covered / evaluate
# ---------------------------------------------------------------------------


def test_not_covered_emission(tmp_path):
    cfg = sc.parse_config(
        {
            "builtin": {"enabled": False},
            "tools": [
                {
                    "id": "a",
                    "failure_modes": ["logic_error", "fabrication"],
                    "command": "exit 0",
                },
                {"id": "b", "failure_modes": ["scope_creep"], "runs_per_commit": False},
            ],
        }
    )
    events = sc.evaluate(
        cfg,
        cs_from({"x.py": (["x = 1"], [])}),
        tmp_path,
        {"commit": "staged"},
        "manual",
        verbose=False,
    )
    nc = {e["failure_mode"] for e in events if e["outcome"] == "not_covered"}
    assert nc == set(sc.FAILURE_MODES) - {"logic_error", "fabrication"}
    assert all(
        e["tool_id"] is None and e["blocking"] is False
        for e in events
        if e["outcome"] == "not_covered"
    )
    b = [e for e in events if e["tool_id"] == "b"]
    assert [e["outcome"] for e in b] == ["not_runnable"]
    a = [e for e in events if e["tool_id"] == "a"]
    assert len(a) == 2 and {e["outcome"] for e in a} == {"pass"}
    for e in events:
        assert selftest.validate_event(e) == []


def test_builtins_do_not_count_as_coverage(tmp_path):
    """KT-09: the built-in heuristics were never benchmarked, so a failure mode
    that only a built-in watches is still reported as not covered."""
    cfg = sc.parse_config({"tools": []})
    events = sc.evaluate(
        cfg, cs_from({}), tmp_path, {"commit": "staged"}, "manual", verbose=False
    )
    nc = {e["failure_mode"]: e for e in events if e["outcome"] == "not_covered"}
    assert set(nc) == set(sc.FAILURE_MODES)
    assert sc.covered_failure_modes(cfg) == set()
    for fm in ("incomplete_execution", "test_manipulation", "fabrication"):
        assert "not benchmarked" in nc[fm]["detail"]
    assert "not benchmarked" not in nc["scope_creep"]["detail"]
    builtin = [e for e in events if e["tool_id"] and e["tool_id"].startswith("saica:")]
    assert {e["tool_id"] for e in builtin} == {tid for tid, _fm in sc.BUILTIN_CHECKS}
    assert {e["outcome"] for e in builtin} == {"skipped"}
    for e in events:
        assert selftest.validate_event(e) == []


def test_summary_marks_builtins_as_heuristics(tmp_path, capsys):
    cfg = sc.parse_config({"tools": []})
    events = sc.evaluate(
        cfg,
        cs_from({"a.py": (["x = 1  # TODO"], [])}),
        tmp_path,
        {"commit": "staged"},
        "manual",
        verbose=False,
    )
    sc.print_summary(events, "saica: checks")
    err = capsys.readouterr().err
    line = [ln for ln in err.splitlines() if "saica:stub-markers" in ln][0]
    assert "CAUGHT" in line and "heuristic, not benchmarked" in line


# ---------------------------------------------------------------------------
# run --staged / stamp flow
# ---------------------------------------------------------------------------


def _write_cfg(repo, tools):
    (repo / ".saica" / "checks.json").write_text(
        json.dumps({"version": 1, "kit": "test", "tools": tools})
    )


def test_stamp_flow(repo):
    _write_cfg(
        repo, [{"id": "ok", "failure_modes": ["logic_error"], "command": "exit 0"}]
    )
    (repo / "a.py").write_text("x = 1  # TODO\n")
    gitc(repo, "add", "a.py")
    assert sc.main(["run", "--staged"]) == 0
    pending = sc.read_jsonl(repo / ".saica" / "pending.jsonl")
    assert pending and all(e["commit"] == "staged" for e in pending)
    gitc(
        repo,
        "commit",
        "-q",
        "-m",
        "Add a\n\nCo-Authored-By: GitHub Copilot <copilot@users.noreply.github.com>",
    )
    assert sc.main(["stamp"]) == 0
    assert not (repo / ".saica" / "pending.jsonl").exists()
    head = gitc(repo, "rev-parse", "HEAD").strip()
    events = sc.read_jsonl(repo / ".saica" / "events.jsonl")
    assert len(events) == len(pending)
    assert all(
        e["commit"] == head and e["subject"] == "Add a" and e["agent"] == "copilot"
        for e in events
    )
    assert all(selftest.validate_event(e) == [] for e in events)
    stub = [e for e in events if e["tool_id"] == "saica:stub-markers"][0]
    assert stub["outcome"] == "caught"
    # stamp with nothing pending is a no-op
    assert sc.main(["stamp"]) == 0
    assert len(sc.read_jsonl(repo / ".saica" / "events.jsonl")) == len(events)


def test_run_staged_blocks_and_discards_stale_pending(repo):
    _write_cfg(
        repo,
        [
            {
                "id": "gate",
                "failure_modes": ["security_vulnerability"],
                "command": "test ! -e BAD",
                "blocking": True,
            }
        ],
    )
    (repo / "BAD").write_text("")
    gitc(repo, "add", "BAD")
    assert sc.main(["run", "--staged"]) == 1
    assert sc.main(["run", "--staged", "--no-block"]) == 0
    # Deleting BAD from the working tree does not unstage it: the check looks
    # at the index snapshot, so the commit stays blocked.
    os.remove(repo / "BAD")
    assert sc.main(["run", "--staged"]) == 1
    pending = sc.read_jsonl(repo / ".saica" / "pending.jsonl")
    gate = [e for e in pending if e["tool_id"] == "gate"]
    assert [e["outcome"] for e in gate] == ["caught"]
    # Only removing it from the index clears the gate.
    gitc(repo, "rm", "--cached", "-q", "BAD")
    assert sc.main(["run", "--staged"]) == 0
    pending = sc.read_jsonl(repo / ".saica" / "pending.jsonl")
    gate = [e for e in pending if e["tool_id"] == "gate"]
    assert [e["outcome"] for e in gate] == ["pass"]  # earlier runs discarded


def test_stamp_discards_pending_from_different_staged_tree(repo, capsys):
    _write_cfg(
        repo, [{"id": "ok", "failure_modes": ["logic_error"], "command": "exit 0"}]
    )
    pending_path = repo / ".saica" / "pending.jsonl"
    events_path = repo / ".saica" / "events.jsonl"
    meta_path = repo / ".git" / sc.PENDING_META_NAME
    (repo / "a.py").write_text("x = 1\n")
    gitc(repo, "add", "a.py")
    assert sc.main(["run", "--staged"]) == 0
    assert sc.read_jsonl(pending_path)
    assert meta_path.is_file()
    # The index changes after the check, and the commit is made without
    # re-running it: the pending results describe a tree that was never committed.
    (repo / "b.py").write_text("y = 2  # TODO\n")
    gitc(repo, "add", "b.py")
    gitc(repo, "commit", "-q", "-m", "a and unchecked b")
    capsys.readouterr()
    assert sc.main(["stamp"]) == 0
    assert "NOT stamped" in capsys.readouterr().err
    assert not pending_path.exists()
    assert not meta_path.exists()
    assert sc.read_jsonl(events_path) == []
    # Nothing is left behind for a later commit to pick up.
    (repo / "c.py").write_text("z = 3\n")
    gitc(repo, "add", "c.py")
    gitc(repo, "commit", "-q", "-m", "c")
    assert sc.main(["stamp"]) == 0
    assert sc.read_jsonl(events_path) == []


def test_run_commit_and_replay(repo):
    _write_cfg(
        repo, [{"id": "ok", "failure_modes": ["logic_error"], "command": "exit 0"}]
    )
    (repo / "a.py").write_text("def f():\n    pass\n")
    gitc(repo, "add", "a.py")
    gitc(repo, "commit", "-q", "-m", "root commit")
    (repo / "b.py").write_text("y = 2\n")
    gitc(repo, "add", "b.py")
    gitc(repo, "commit", "-q", "-m", "second")
    assert sc.main(["run", "--commit", "HEAD~1", "--source", "ci"]) == 0
    events = sc.read_jsonl(repo / ".saica" / "events.jsonl")
    assert {e["source"] for e in events} == {"ci"}
    assert [e["outcome"] for e in events if e["tool_id"] == "saica:stub-markers"] == [
        "caught"
    ]
    assert sc.main(["replay", "--last", "5"]) == 0
    replay = [
        e
        for e in sc.read_jsonl(repo / ".saica" / "events.jsonl")
        if e["source"] == "replay"
    ]
    assert len({e["commit"] for e in replay}) == 2
    assert {e["outcome"] for e in replay if e["tool_id"] == "ok"} == {"skipped"}
    n = len(replay)
    assert sc.main(["replay", "--last", "5"]) == 0  # idempotent
    assert (
        len(
            [
                e
                for e in sc.read_jsonl(repo / ".saica" / "events.jsonl")
                if e["source"] == "replay"
            ]
        )
        == n
    )


def test_missing_config_exit_code(repo, capsys):
    assert sc.main(["run", "--staged"]) == 2
    assert "config not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Diff parsing details
# ---------------------------------------------------------------------------


def test_unquote_path():
    assert sc._unquote_path("plain/name.py") == "plain/name.py"
    assert sc._unquote_path('"tab\\there.py"') == "tab\there.py"
    assert sc._unquote_path('"q\\"uote\\\\.py"') == 'q"uote\\.py'
    assert (
        sc._unquote_path('"tests/\\303\\274n\\303\\257_test.py"') == "tests/ünï_test.py"
    )
    assert sc._unquote_path('"nl\\nname.py"') == "nl\nname.py"


def test_diff_lines_are_split_on_newlines_only():
    text = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1,3 @@\n"
        "+x = 1\x0c+not a new line\n+y = 2\u2028# TODO still line 2\n+z = 3\r\n"
    )
    fd = sc.parse_unified_diff(text)["a.py"]
    assert [no for no, _t in fd.added] == [1, 2, 3]
    assert fd.added[2][1] == "z = 3"


def test_rename_does_not_report_old_markers(repo):
    """KT-09: a file that was only moved has no added lines."""
    _write_cfg(repo, [])
    (repo / "old_name.py").write_text("def f():\n    return 1  # TODO later\n" * 5)
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "one")
    gitc(repo, "mv", "old_name.py", "new_name.py")
    cs = sc.staged_changeset(repo)
    assert sc.check_stub_markers(cs) == []
    assert cs.files == ["new_name.py"]
    assert sorted(cs.touched) == ["new_name.py", "old_name.py"]


def test_non_ascii_paths_are_reported_readably(repo):
    _write_cfg(repo, [])
    (repo / "tests").mkdir()
    (repo / "tests" / "ünï_test.py").write_text("x = 1  # TODO\n")
    gitc(repo, "add", "-A")
    hits = sc.check_stub_markers(sc.staged_changeset(repo))
    assert hits == ["tests/ünï_test.py:1 TODO"]


# ---------------------------------------------------------------------------
# The check that watches the kit itself (KT-08)
# ---------------------------------------------------------------------------


def _tamper(events):
    return [e for e in events if e["tool_id"] == "saica:kit-tamper"]


def _staged_events(repo, config=None):
    cfg = config or sc.load_config(repo / ".saica" / "checks.json")
    cs = sc.staged_changeset(repo)
    return sc.evaluate(
        cfg, cs, repo, {"commit": "staged"}, "manual", run_tools=False, verbose=False
    )


@pytest.mark.parametrize(
    "path, kit",
    [
        (".saica/checks.json", True),
        (".saica/saica_check.py", True),
        (".saica/saica_llm_review.py", True),
        (".saica/prompts/scope_creep.md", True),
        (".saica/hooks/pre-commit", True),
        (".saica/cache/llm/abc.json", True),
        (".github/workflows/saica-ci.yml", True),
        (".saica/events.jsonl", True),  # a tracked log could replace the record
        (".saica/dashboard.html", False),
        (".saica/task.md", False),
        (".github/workflows/tests.yml", False),
        ("src/saica/checks.json", False),
    ],
)
def test_is_kit_path(path, kit):
    assert sc.is_kit_path(path) is kit


def test_kit_tamper_first_install_then_edits(repo):
    _write_cfg(
        repo, [{"id": "ok", "failure_modes": ["logic_error"], "command": "true"}]
    )
    (repo / "app.py").write_text("x = 1\n")
    gitc(repo, "add", "-A")
    ev = _tamper(_staged_events(repo))
    assert [e["outcome"] for e in ev] == ["pass"]  # nothing was supervising before
    assert "no kit before" in ev[0]["detail"]
    assert ev[0]["failure_mode"] == "test_manipulation"
    gitc(repo, "commit", "-q", "-m", "install kit")

    # An ordinary change: the tamper check passes quietly.
    (repo / "app.py").write_text("x = 2\n")
    gitc(repo, "add", "-A")
    assert [(e["outcome"], e["detail"]) for e in _tamper(_staged_events(repo))] == [
        ("pass", "")
    ]

    # The change edits the config (here: it drops the only tool).
    _write_cfg(repo, [])
    gitc(repo, "add", "-A")
    ev = _tamper(_staged_events(repo))
    assert [e["outcome"] for e in ev] == ["caught"]
    assert ".saica/checks.json" in ev[0]["detail"]
    assert all(selftest.validate_event(e) == [] for e in ev)
    gitc(repo, "commit", "-q", "-m", "weaken", "--no-verify")

    # Deleting the config and touching the workflow are both seen.
    gitc(repo, "rm", "-q", ".saica/checks.json")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "saica-ci.yml").write_text("name: x\n")
    gitc(repo, "add", "-A")
    cfg = sc.parse_config({"tools": []})
    ev = _tamper(_staged_events(repo, cfg))
    assert [e["outcome"] for e in ev] == ["caught"]
    assert ".saica/checks.json" in ev[0]["detail"]
    assert ".github/workflows/saica-ci.yml" in ev[0]["detail"]


def test_kit_tamper_cannot_be_switched_off_by_the_same_change(repo):
    (repo / ".saica" / "checks.json").write_text(
        json.dumps(
            {"version": 1, "builtin": {"enabled": True, "blocking": True}, "tools": []}
        )
    )
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "install kit")
    # The next change turns every built-in off and plants a stub.
    (repo / ".saica" / "checks.json").write_text(
        json.dumps({"version": 1, "builtin": {"enabled": False}, "tools": []})
    )
    (repo / "app.py").write_text("def f():\n    pass  # TODO\n")
    gitc(repo, "add", "-A")
    events = _staged_events(repo)
    builtin = [e for e in events if e["tool_id"] and e["tool_id"].startswith("saica:")]
    assert [e["tool_id"] for e in builtin] == ["saica:kit-tamper"]
    assert builtin[0]["outcome"] == "caught"
    assert builtin[0]["blocking"] is True  # as configured before this change
    assert sc.main(["run", "--staged"]) == 1  # so the commit is refused
    # With the built-ins off before the change as well, nothing runs.
    gitc(repo, "commit", "-q", "-m", "off", "--no-verify")
    (repo / "b.py").write_text("y = 1\n")
    (repo / ".saica" / "extra.py").write_text("")
    gitc(repo, "add", "-A")
    assert [e for e in _staged_events(repo) if e["tool_id"]] == []


def test_kit_tamper_hook_config_lines(repo):
    _write_cfg(repo, [])
    (repo / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: saica\n"
        "        entry: python3 .saica/saica_check.py run --staged\n      - id: other\n"
    )
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "install")
    text = (repo / ".pre-commit-config.yaml").read_text()
    (repo / ".pre-commit-config.yaml").write_text(text + "      - id: black\n")
    gitc(repo, "add", "-A")
    assert sc.check_kit_tamper(sc.staged_changeset(repo)) == []
    (repo / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: other\n"
    )
    gitc(repo, "add", "-A")
    assert sc.check_kit_tamper(sc.staged_changeset(repo)) == [".pre-commit-config.yaml"]


def test_run_commit_records_kit_tamper(repo):
    _write_cfg(repo, [])
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "install kit")
    cfg_copy = repo.parent / "trusted-checks.json"
    cfg_copy.write_text((repo / ".saica" / "checks.json").read_text())
    (repo / ".saica" / "checks.json").write_text(
        json.dumps({"version": 1, "builtin": {"enabled": False}, "tools": []})
    )
    gitc(repo, "add", "-A")
    gitc(repo, "commit", "-q", "-m", "switch the kit off")
    # CI takes the config from the base ref, so the change is judged by the old
    # rules; a change to the kit itself stops the job until a person looks.
    assert (
        sc.main(
            ["--config", str(cfg_copy), "run", "--commit", "HEAD", "--source", "ci"]
        )
        == 1
    )
    events = sc.read_jsonl(repo / ".saica" / "events.jsonl")
    assert [e["outcome"] for e in _tamper(events)] == ["caught"]


# ---------------------------------------------------------------------------
# Agent detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, email, body, expected",
    [
        (
            "Jane Dev",
            "jane@example.com",
            "Fix\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n",
            "claude",
        ),
        ("Copilot", "198982749+Copilot@users.noreply.github.com", "", "copilot"),
        (
            "Jane Dev",
            "jane@example.com",
            "x\n\nCo-authored-by: Cursor Agent <cursoragent@cursor.com>",
            "cursor",
        ),
        (
            "devin-ai-integration[bot]",
            "158243242+devin-ai-integration[bot]@users.noreply.github.com",
            "",
            "devin",
        ),
        ("chatgpt-codex-connector[bot]", "x@users.noreply.github.com", "", "codex"),
        ("Jane Dev (aider)", "jane@example.com", "", "aider"),
        (
            "dependabot[bot]",
            "49699333+dependabot[bot]@users.noreply.github.com",
            "",
            "bot",
        ),
        ("Jane Dev", "jane@example.com", "plain message", None),
        ("Claude Monet", "claude@painters.example", "", None),
        ("Devin Smith", "devin@company.example", "", None),
    ],
)
def test_detect_agent(name, email, body, expected):
    assert sc.detect_agent(name, email, body) == expected


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def test_dashboard_escaping():
    tpl = '<html><script id="saica-events" type="application/json">[]</script><script>x()</script></html>'
    events = [{"detail": "</script><script>alert(1)</script><!-- x"}]
    html = sc.embed_events(tpl, events)
    payload = html.split('type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "</" not in payload and "<!--" not in payload
    assert json.loads(payload) == events
    assert html.endswith("<script>x()</script></html>")
    # Re-embedding into an already-rendered page replaces, not appends.
    again = sc.embed_events(html, [])
    assert '<script id="saica-events" type="application/json">[]</script>' in again


def test_dashboard_template_missing_tag():
    with pytest.raises(sc.SaicaError, match="saica-events"):
        sc.embed_events("<html></html>", [])


def test_dashboard_command(repo):
    tpl = repo / "tpl.html"
    tpl.write_text('<script id="saica-events" type="application/json">[]</script>')
    (repo / ".saica" / "events.jsonl").write_text(
        json.dumps({"commit": "abc", "detail": "</b>"}) + "\nnot json\n"
    )
    assert sc.main(["dashboard", "--template", str(tpl)]) == 0
    html = (repo / ".saica" / "dashboard.html").read_text()
    assert '"commit":"abc"' in html and "<\\/b>" in html


# ---------------------------------------------------------------------------
# install-hooks
# ---------------------------------------------------------------------------


def test_install_hooks_refuses_foreign(repo):
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\necho mine\n")
    assert sc.main(["install-hooks"]) == 1
    assert "echo mine" in (hooks / "pre-commit").read_text()
    assert sc.main(["install-hooks", "--force"]) == 0
    assert "saica_check.py" in (hooks / "pre-commit").read_text()
    assert (hooks / "pre-commit.saica-backup").exists()
    assert os.access(hooks / "post-commit", os.X_OK)


def test_hook_files_match_embedded_copies():
    assert (KIT / "hooks" / "pre-commit").read_text() == sc.PRE_COMMIT_HOOK
    assert (KIT / "hooks" / "post-commit").read_text() == sc.POST_COMMIT_HOOK
    assert os.access(KIT / "hooks" / "pre-commit", os.X_OK)


def test_install_hooks_refuses_a_shared_hooks_directory(repo, tmp_path, capsys):
    """KT-13: with a global core.hooksPath one install would change every repository."""
    shared = tmp_path / "home" / ".githooks"
    gitc(repo, "config", "--global", "core.hooksPath", str(shared))
    assert sc.main(["install-hooks"]) == 1
    err = capsys.readouterr().err
    assert "refusing to install" in err and "core.hooksPath" in err
    assert not shared.exists()
    assert sc.main(["install-hooks", "--force"]) == 1
    assert not shared.exists()
    # A hooks directory of its own (inside the repository) is fine.
    gitc(repo, "config", "--local", "core.hooksPath", ".git/hooks")
    assert sc.main(["install-hooks"]) == 0
    assert (repo / ".git" / "hooks" / "pre-commit").is_file()
    assert not shared.exists()


def test_install_hooks_inside_the_work_tree_is_allowed(repo):
    gitc(repo, "config", "--local", "core.hooksPath", ".githooks")
    assert sc.main(["install-hooks"]) == 0
    assert os.access(repo / ".githooks" / "pre-commit", os.X_OK)


def test_install_hooks_replaces_an_earlier_kit_hook(repo, monkeypatch):
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    old = "#!/bin/sh\n# an earlier kit hook\nexec python3 .saica/saica_check.py run --staged\n"
    (hooks / "pre-commit").write_text(old)
    assert sc.main(["install-hooks"]) == 1  # unknown text: refused
    monkeypatch.setattr(
        sc, "EARLIER_KIT_HOOKS", {hashlib.sha256(old.encode()).hexdigest()}
    )
    assert sc.main(["install-hooks"]) == 0
    assert (hooks / "pre-commit").read_text() == sc.PRE_COMMIT_HOOK
    assert not (hooks / "pre-commit.saica-backup").exists()


def test_hooks_pick_a_python_that_is_new_enough(repo, tmp_path):
    """KT-18: a `python3` that is too old (or a stub that fails) must not be used."""
    _write_cfg(repo, [])
    kit_dir = repo / ".saica"
    (kit_dir / "saica_check.py").write_text((KIT / "saica_check.py").read_text())
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "python3").write_text("#!/bin/sh\nexit 1\n")  # e.g. the Windows Store stub
    (fake / "python3").chmod(0o755)
    real = fake / "python"
    real.write_text('#!/bin/sh\nexec %s "$@"\n' % shlex.quote(sys.executable))
    real.chmod(0o755)
    env = dict(os.environ, PATH="%s:/usr/bin:/bin" % fake)
    (repo / "a.py").write_text("x = 1\n")
    gitc(repo, "add", "-A")
    r = subprocess.run(
        ["sh", str(KIT / "hooks" / "pre-commit")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "saica: checks for staged changes" in r.stderr
    assert "NOT checked" not in r.stderr


# ---------------------------------------------------------------------------
# One contract, four copies (KT-20)
# ---------------------------------------------------------------------------


def _js_list(text, name):
    m = re.search(r"var %s = \[(.*?)\];" % name, text, re.S)
    assert m, name
    return re.findall(r"'([a-z_]+)'", m.group(1))


def test_contract_lists_agree_across_the_kit_files():
    dash = (KIT / "dashboard.html").read_text()
    readme = (KIT / "README.md").read_text()
    assert list(selftest.FAILURE_MODES) == list(sc.FAILURE_MODES)
    assert _js_list(dash, "FMS") == list(sc.FAILURE_MODES)
    assert set(selftest.OUTCOMES) == set(sc.OUTCOMES)
    assert _js_list(dash, "OUTCOMES") == list(sc.OUTCOMES)
    assert set(selftest.SOURCES) == set(sc.SOURCES)
    for fm in sc.FAILURE_MODES:
        assert "`%s`" % fm in readme
    for outcome in sc.OUTCOMES:
        assert "`%s`" % outcome in readme
    for tid, fm in sc.BUILTIN_CHECKS:
        assert "`%s`" % tid in readme, tid
        assert fm in sc.FAILURE_MODES


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


def test_selftest_sandbox_end_to_end(clean_git_env):
    r = subprocess.run(
        [sys.executable, "-B", str(KIT / "selftest.py"), "--sandbox"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[FAIL]" not in r.stdout
    assert "PASS: all checks passed" in r.stdout
