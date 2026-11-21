"""Tests for the SAICA supervision kit runner (site/public/kit/saica_check.py).

The kit files are standalone scripts meant to be copied into other repos, so
they are loaded by path rather than imported as a package.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
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
    cfg = sc.load_config(KIT / "checks.example.json")
    ids = [t["id"] for t in cfg["tools"]]
    assert ids == ["semgrep", "sentrux", "pytest", "dependency-blindness-review"]
    assert cfg["kit"] == "custom"
    assert cfg["builtin"] == {"enabled": True, "blocking": False}
    # The last entry is the LLM-reviewer runner (non-blocking, per commit).
    review = cfg["tools"][-1]
    assert review["runs_per_commit"] is True and review["blocking"] is False
    assert review["command"].startswith("python3 .saica/saica_llm_review.py")
    assert cfg["tools"][1]["metric"]["name"] == "quality"


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
        ("exit 3", "caught"),
        ("exit 127", "error"),
        ("definitely-not-a-binary-xyz", "error"),
    ],
)
def test_tool_outcomes(tmp_path, command, outcome):
    assert sc.run_tool(tool(command), ["a.py"], tmp_path)[0] == outcome


def test_tool_timeout(tmp_path):
    out, detail, _ = sc.run_tool(tool("sleep 5", timeout_s=0.3), [], tmp_path)
    assert out == "error" and "timeout" in detail


def test_tool_files_substitution_and_skip(tmp_path):
    t = tool("printf '%s\\n' {files} > out.txt")
    assert sc.run_tool(t, ["a b.py", "c.py"], tmp_path)[0] == "pass"
    assert (tmp_path / "out.txt").read_text().splitlines() == ["a b.py", "c.py"]
    assert sc.run_tool(t, [], tmp_path)[0] == "skipped"


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


def test_builtins_reduce_not_covered(tmp_path):
    cfg = sc.parse_config({"tools": []})
    events = sc.evaluate(
        cfg, cs_from({}), tmp_path, {"commit": "staged"}, "manual", verbose=False
    )
    nc = {e["failure_mode"] for e in events if e["outcome"] == "not_covered"}
    assert not nc & {"incomplete_execution", "test_manipulation", "fabrication"}
    assert {
        e["outcome"]
        for e in events
        if e["tool_id"] and e["tool_id"].startswith("saica:")
    } == {"skipped"}


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
