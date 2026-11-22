"""Tests for the kit's CI workflow template (site/public/kit/saica-ci.yml).

GitHub Actions cannot run here, so the shell script of the "Run SAICA checks"
step is taken out of the YAML and run with bash in a scratch repository, with
the environment GitHub would give it (review issue I6; evidence KT-07, KT-08):
the kit comes from the base of the change, a pull request update checks only
the new commits, a push checks the default branch's first-parent commits.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "site" / "public" / "kit"
WORKFLOW = yaml.safe_load((KIT / "saica-ci.yml").read_text())
STEPS = WORKFLOW["jobs"]["saica"]["steps"]
RUN = next(s for s in STEPS if s.get("id") == "checks")["run"]
SUMMARY = next(s for s in STEPS if s.get("name") == "Summarise")["run"]
ZERO = "0" * 40

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def gitc(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(root, message, files=None, remove=()):
    for name, text in (files or {}).items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for name in remove:
        (root / name).unlink()
    gitc(root, "add", "-A")
    gitc(root, "commit", "-q", "-m", message)
    return gitc(root, "rev-parse", "HEAD")


CONFIG = {
    "version": 1,
    "kit": "ci-test",
    "builtin": {"enabled": True, "blocking": False},
    "tools": [
        {
            "id": "marker",
            "failure_modes": ["logic_error"],
            "command": "test ! -e BAD_MARKER",
            "blocking": True,
        },
        {
            "id": "helper",
            "failure_modes": ["scope_creep"],
            "command": "sh .saica/helper.sh",
        },
    ],
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith(("GIT_", "SAICA_", "GITHUB_")):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    root = tmp_path / "repo"
    root.mkdir()
    gitc(root, "init", "-q", "-b", "main")
    gitc(root, "config", "user.name", "Test Human")
    gitc(root, "config", "user.email", "human@example.invalid")
    gitc(root, "config", "commit.gpgsign", "false")
    (root / ".saica").mkdir()
    shutil.copy2(str(KIT / "saica_check.py"), str(root / ".saica" / "saica_check.py"))
    (root / ".gitignore").write_text(
        ".saica/events.jsonl\n.saica/pending.jsonl\n.saica/dashboard.html\n"
    )
    commit(
        root,
        "install kit",
        {
            ".saica/checks.json": json.dumps(CONFIG),
            ".saica/helper.sh": "echo 'ok: base helper'\n",
            "app.py": "x = 1\n",
        },
    )
    return root


def run_step(root, tmp_path, **env):
    out = tmp_path / "github_output"
    out.write_text("")
    temp = tmp_path / "runner_temp"
    temp.mkdir(exist_ok=True)
    full = dict(
        os.environ,
        RUNNER_TEMP=str(temp),
        SAICA_OUT=str(temp / "saica-out"),
        GITHUB_OUTPUT=str(out),
        GITHUB_REF="refs/heads/main",
        DEFAULT_BRANCH="main",
        MAX_COMMITS="50",
        EVENT_ACTION="",
        EVENT_BEFORE="",
        PUSH_DELETED="",
        PR_BASE="",
        PR_HEAD="",
        PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"],
    )
    full.update(env)
    r = subprocess.run(
        ["bash", "-c", RUN],
        cwd=root,
        env=full,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return r, out.read_text()


def events(root):
    """The event log of the last run: CI writes it outside the checkout."""
    p = root.parent / "runner_temp" / "saica-out" / "events.jsonl"
    return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []


def checked(root):
    seen = []
    for e in events(root):
        if e["commit"] not in seen:
            seen.append(e["commit"])
    return seen


def test_workflow_shape():
    on = WORKFLOW.get("on", WORKFLOW.get(True))  # YAML reads the key `on` as a boolean
    assert set(on) == {"push", "pull_request"}
    assert "pull_request_target" not in on
    assert WORKFLOW["permissions"] == {"contents": "read"}
    job = WORKFLOW["jobs"]["saica"]
    assert "default_branch" in job["if"] and "pull_request" in job["if"]
    uses = [s["uses"] for s in STEPS if "uses" in s]
    assert uses and all(
        len(u.split("@")[1]) == 40 for u in uses
    ), uses  # pinned by commit
    checkout = next(
        s for s in STEPS if s.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    step = next(s for s in STEPS if s.get("id") == "checks")
    # every value from the event reaches the script through env, never through ${{ }} in the script
    assert "${{" not in RUN and "${{" not in SUMMARY
    assert "saica-cache" in step["env"]["SAICA_CACHE_DIR"]
    cache = next(s for s in STEPS if s.get("uses", "").startswith("actions/cache@"))
    assert cache["with"]["path"] == step["env"]["SAICA_CACHE_DIR"]


def test_pull_request_uses_the_kit_of_the_base(repo, tmp_path):
    base = gitc(repo, "rev-parse", "HEAD")
    gitc(repo, "checkout", "-q", "-b", "feature")
    weaker = dict(CONFIG, builtin={"enabled": False}, tools=[])
    c1 = commit(
        repo,
        "switch the kit off and plant a marker",
        {
            ".saica/checks.json": json.dumps(weaker),
            ".saica/helper.sh": "echo 'ok: helper rewritten by the change'\n",
            ".saica/json.py": "raise SystemExit('planted module was imported')\n",
            "BAD_MARKER": "x\n",
        },
    )
    r, out = run_step(
        repo,
        tmp_path,
        EVENT_NAME="pull_request",
        EVENT_ACTION="opened",
        PR_BASE=base,
        PR_HEAD=c1,
        GITHUB_SHA=c1,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "taken from the base commit" in r.stdout
    by = {e["tool_id"]: e for e in events(repo) if e["commit"] == c1 and e["tool_id"]}
    # judged by the base's config: the dropped tool still ran and caught, the tamper check saw the edit
    assert by["marker"]["outcome"] == "caught" and by["marker"]["blocking"] is True
    assert by["saica:kit-tamper"]["outcome"] == "caught"
    assert ".saica/checks.json" in by["saica:kit-tamper"]["detail"]
    # helper scripts come from the base too, and files the change added under .saica/ are gone
    assert by["helper"]["detail"] == "ok: base helper"
    assert "blocked=1" in out
    assert (
        gitc(repo, "rev-parse", "HEAD") == c1
        and gitc(repo, "status", "--porcelain") == ""
    )


def test_every_push_to_a_pull_request_checks_all_of_its_commits(repo, tmp_path):
    """A later commit must not clear a finding of an earlier one (the verdict cache keeps repeats cheap)."""
    base = gitc(repo, "rev-parse", "HEAD")
    gitc(repo, "checkout", "-q", "-b", "feature")
    c1 = commit(repo, "one", {"a.py": "a = 1\n"})
    c2 = commit(repo, "two", {"b.py": "b = 1\n"})
    r, out = run_step(
        repo,
        tmp_path,
        EVENT_NAME="pull_request",
        EVENT_ACTION="opened",
        PR_BASE=base,
        PR_HEAD=c2,
        GITHUB_SHA=c2,
    )
    assert r.returncode == 0 and checked(repo) == [c1, c2] and "blocked=0" in out
    c3 = commit(repo, "three", {"c.py": "c = 1\n"})
    r, out = run_step(
        repo,
        tmp_path,
        EVENT_NAME="pull_request",
        EVENT_ACTION="synchronize",
        EVENT_BEFORE=c2,
        PR_BASE=base,
        PR_HEAD=c3,
        GITHUB_SHA=c3,
    )
    assert r.returncode == 0 and checked(repo) == [c1, c2, c3] and "blocked=0" in out
    # the log is outside the checkout; nothing is left in the work tree
    assert not (repo / ".saica" / "events.jsonl").exists()
    assert gitc(repo, "status", "--porcelain") == ""


def test_push_checks_the_first_parent_line_once(repo, tmp_path):
    before = gitc(repo, "rev-parse", "HEAD")
    gitc(repo, "checkout", "-q", "-b", "feature")
    f1 = commit(repo, "f1", {"a.py": "a = 1\n"})
    f2 = commit(repo, "f2", {"b.py": "b = 1  # TODO\n"})
    gitc(repo, "checkout", "-q", "main")
    direct = commit(repo, "direct", {"c.py": "c = 1\n"})
    gitc(repo, "merge", "-q", "--no-ff", "-m", "Merge feature", "feature")
    merge = gitc(repo, "rev-parse", "HEAD")
    r, out = run_step(
        repo, tmp_path, EVENT_NAME="push", EVENT_BEFORE=before, GITHUB_SHA=merge
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert checked(repo) == [
        direct,
        merge,
    ]  # the branch's own commits are not re-checked
    assert f1 not in checked(repo) and f2 not in checked(repo)
    stub = [
        e
        for e in events(repo)
        if e["commit"] == merge and e["tool_id"] == "saica:stub-markers"
    ]
    assert (
        stub[0]["outcome"] == "caught"
    )  # the merge is checked as one change: the whole branch
    assert "blocked=0" in out


def test_push_of_a_new_branch_and_deletion(repo, tmp_path):
    head = gitc(repo, "rev-parse", "HEAD")
    r, out = run_step(
        repo, tmp_path, EVENT_NAME="push", EVENT_BEFORE=ZERO, GITHUB_SHA=head
    )
    assert r.returncode == 0 and checked(repo) == [head]
    assert (
        "the kit files of the change itself are used" in r.stdout
    )  # no base: said loudly
    r, out = run_step(
        repo,
        tmp_path,
        EVENT_NAME="push",
        EVENT_BEFORE=head,
        GITHUB_SHA=ZERO,
        PUSH_DELETED="true",
    )
    assert r.returncode == 0 and "nothing to check" in r.stdout and "blocked=0" in out


def test_unresolvable_range_fails_instead_of_passing(repo, tmp_path):
    head = gitc(repo, "rev-parse", "HEAD")
    r, _ = run_step(
        repo,
        tmp_path,
        EVENT_NAME="pull_request",
        PR_BASE="1" * 40,
        PR_HEAD=head,
        GITHUB_SHA=head,
    )
    assert r.returncode == 1 and "cannot be resolved" in r.stdout and events(repo) == []
    r, _ = run_step(repo, tmp_path, EVENT_NAME="workflow_dispatch", GITHUB_SHA=head)
    assert r.returncode == 1 and "unsupported event" in r.stdout
    r, _ = run_step(repo, tmp_path, EVENT_NAME="push", EVENT_BEFORE="", GITHUB_SHA=head)
    assert r.returncode == 1


def test_summary_warns_when_a_tool_only_produced_errors(repo, tmp_path):
    broken = dict(
        CONFIG,
        tools=[
            {
                "id": "missing-tool",
                "failure_modes": ["logic_error"],
                "command": "saica-no-such-binary",
            }
        ],
    )
    base = commit(
        repo,
        "config with a tool that is not installed",
        {".saica/checks.json": json.dumps(broken)},
    )
    c1 = commit(repo, "work", {"a.py": "a = 1\n"})
    r, _ = run_step(repo, tmp_path, EVENT_NAME="push", EVENT_BEFORE=base, GITHUB_SHA=c1)
    assert r.returncode == 0
    summary = tmp_path / "summary.md"
    env = dict(
        os.environ,
        GITHUB_STEP_SUMMARY=str(summary),
        SAICA_OUT=str(tmp_path / "runner_temp" / "saica-out"),
        PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"],
    )
    s = subprocess.run(
        ["bash", "-c", SUMMARY],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert s.returncode == 0, s.stderr
    assert "::warning title=SAICA CI::missing-tool did not check any commit" in s.stdout
    assert "| missing-tool | 0 | 0 | 1 | 0 |" in summary.read_text()
