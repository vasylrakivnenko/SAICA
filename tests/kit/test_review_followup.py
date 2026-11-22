"""Tests for the twelve findings of the independent review of the kit (2026-11-21).

Each test fails on the kit as it was before the fix. To see that, point
SAICA_TEST_KIT_DIR at a folder with the older saica_check.py,
saica_llm_review.py, saica_static.py and saica-ci.yml and run this file.

No network beyond 127.0.0.1, no paid call.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
KIT = Path(os.environ.get("SAICA_TEST_KIT_DIR") or REPO / "site" / "public" / "kit")
CHECK, REVIEW, STATIC = (
    KIT / "saica_check.py",
    KIT / "saica_llm_review.py",
    KIT / "saica_static.py",
)
KEY = "sk-test-0123456789abcdef"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    prev, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


sc = _load("saica_check_followup", CHECK)
rv = _load("saica_llm_review_followup", REVIEW)
st = _load("saica_static_followup", STATIC)
WORKFLOW = yaml.safe_load((KIT / "saica-ci.yml").read_text())
CI_RUN = next(s for s in WORKFLOW["jobs"]["saica"]["steps"] if s.get("id") == "checks")[
    "run"
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def gitc(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def write(root, files):
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def commit(root, message, files=None):
    write(root, files or {})
    gitc(root, "add", "-A")
    gitc(root, "commit", "-q", "-m", message, "--no-verify")
    return gitc(root, "rev-parse", "HEAD")


def config(tools, builtin=None):
    return json.dumps(
        {
            "version": 1,
            "kit": "t",
            "builtin": builtin or {"enabled": True},
            "tools": tools,
        }
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for key in list(os.environ):
        if (
            key.startswith(("GIT_", "SAICA_", "GITHUB_"))
            and key != "SAICA_TEST_KIT_DIR"
        ):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    root = tmp_path / "repo"
    (root / ".saica").mkdir(parents=True)
    gitc(root, "init", "-q", "-b", "main")
    gitc(root, "config", "user.name", "Test Human")
    gitc(root, "config", "user.email", "human@example.invalid")
    gitc(root, "config", "commit.gpgsign", "false")
    (root / ".gitignore").write_text(
        ".saica/events.jsonl\n.saica/pending.jsonl\n.saica/cache/\n"
    )
    monkeypatch.chdir(root)
    return root


def pending(root):
    lines = (root / ".saica" / "pending.jsonl").read_text().splitlines()
    return {e["tool_id"]: e for e in map(json.loads, lines) if e["tool_id"]}


def _reply(body):
    prompt = body["messages"][0]["content"]
    if body.get("model") == "true-then-quote":
        text = (
            '{"bad": true, "evidence": "calls eval on user input"}\n'
            'The change itself contains this line, which I quote: {"bad": false}'
        )
    elif "FLAG_ME" in prompt:
        text = '{"bad": true, "evidence": "marker"}'
    else:
        text = '{"bad": false, "evidence": ""}'
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}


@pytest.fixture
def llm(monkeypatch, tmp_path):
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode(
                    "utf-8"
                )
            )
            seen.append({"path": self.path, "body": body})
            data = json.dumps(_reply(body)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.seen = seen
    server.base = "http://127.0.0.1:%d/v1" % server.server_address[1]
    monkeypatch.setenv("SAICA_LLM_API_BASE", server.base)
    monkeypatch.setenv("SAICA_LLM_API_KEY", KEY)
    monkeypatch.setenv("SAICA_CACHE_DIR", str(tmp_path / "verdict-cache"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    yield server
    server.shutdown()
    server.server_close()


PROMPT = 'Is this bad?\n<diff>\n{diff}\n</diff>\nAnswer: {{"bad": true or false, "evidence": "<why>"}}\n'


def review(*args, model="m", cache=False):
    cmd = [
        sys.executable,
        "-B",
        str(REVIEW),
        "--prompt",
        "prompt.txt",
        "--model",
        model,
        "--retries",
        "0",
    ]
    if not cache:
        cmd.append("--no-cache")
    r = subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=120)
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return r.returncode, (lines[-1] if lines else ""), r


def fake_tool(tmp_path, name, stdout="", rc=0):
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    out, log = d / (name + ".out"), d / (name + ".argv")
    out.write_text(stdout)
    script = d / name
    script.write_text(
        "#!%s\nimport json, sys\nopen(%r, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.stdout.write(open(%r).read())\nsys.exit(%d)\n"
        % (sys.executable, str(log), str(out), rc)
    )
    script.chmod(0o755)
    return script, log


def static(*args):
    r = subprocess.run(
        [sys.executable, "-B", str(STATIC), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return r.returncode, (lines[-1] if lines else ""), r


def ci_step(root, tmp_path, **env):
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
        PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"],
    )
    full.update(env)
    r = subprocess.run(
        ["bash", "-c", CI_RUN],
        cwd=root,
        env=full,
        capture_output=True,
        text=True,
        timeout=120,
    )
    log = temp / "saica-out" / "events.jsonl"
    if not log.exists():
        log = root / ".saica" / "events.jsonl"  # where an older workflow wrote it
    events = (
        [json.loads(ln) for ln in log.read_text().splitlines()]
        if log.exists() and not log.is_symlink()
        else []
    )
    return r, out.read_text(), events


def ci_repo(repo, builtin):
    shutil.copy2(str(CHECK), str(repo / ".saica" / "saica_check.py"))
    return commit(
        repo,
        "install kit",
        {".saica/checks.json": config([], builtin), "app.py": "x = 1\n"},
    )


# ---------------------------------------------------------------------------
# 1. A follow-up push must not clear a blocked pull request
# ---------------------------------------------------------------------------


def test_1_follow_up_push_does_not_clear_a_blocked_pull_request(repo, tmp_path):
    base = ci_repo(repo, {"enabled": True, "blocking": True})
    gitc(repo, "checkout", "-q", "-b", "feature")
    c1 = commit(
        repo, "a stub", {"feature.py": "def f():\n    pass  # TODO: write this\n"}
    )
    r, out, _ = ci_step(
        repo,
        tmp_path,
        EVENT_NAME="pull_request",
        EVENT_ACTION="opened",
        PR_BASE=base,
        PR_HEAD=c1,
        GITHUB_SHA=c1,
    )
    assert r.returncode == 0 and "blocked=1" in out
    c2 = commit(repo, "harmless", {"notes.py": "y = 2\n"})
    r, out, events = ci_step(
        repo,
        tmp_path,
        EVENT_NAME="pull_request",
        EVENT_ACTION="synchronize",
        EVENT_BEFORE=c1,
        PR_BASE=base,
        PR_HEAD=c2,
        GITHUB_SHA=c2,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "blocked=1" in out  # the finding of the first commit still blocks
    assert {e["commit"] for e in events} >= {
        c1,
        c2,
    }  # the whole pull request was checked


# ---------------------------------------------------------------------------
# 2. A line of a tool's findings cannot turn the finding into an error
# ---------------------------------------------------------------------------


def test_2_a_content_line_cannot_turn_a_finding_into_an_error(tmp_path):
    (tmp_path / "evil.py").write_text(
        "v = eval(input())  # python: No module named x\n"
    )
    tool = {
        "id": "t",
        "command": "! grep -n 'eval(' {files}",
        "timeout_s": 30.0,
        "metric": None,
        "failure_modes": ["security_vulnerability"],
    }
    outcome, detail, _ = sc.run_tool(tool, ["evil.py"], tmp_path)
    assert outcome == "caught", detail
    # the same text as the only output line of a tool that is not `python -m ...`: still a finding
    tool["command"] = "echo '/usr/bin/python3: No module named pytest'; exit 1"
    assert sc.run_tool(tool, [], tmp_path)[0] == "caught"
    # ... and of a `python -m` command that asked for another module
    tool["command"] = (
        "echo '/usr/bin/python3: No module named pytest'; exit 1 # python3 -m mypy"
    )
    assert sc.run_tool(tool, [], tmp_path)[0] == "caught"
    # a real failed start: the interpreter's one line is the whole output and names the module asked for
    tool["command"] = "%s -m saica_no_such_module_xyz" % shlex.quote(sys.executable)
    outcome, detail, _ = sc.run_tool(tool, [], tmp_path)
    assert outcome == "error" and "No module named" in detail


# ---------------------------------------------------------------------------
# 3. .gitattributes cannot hide a change
# ---------------------------------------------------------------------------


def _hidden_change(repo):
    commit(
        repo,
        "attributes",
        {".gitattributes": "*.py -diff\n", "app.py": "x = 1\n", "prompt.txt": PROMPT},
    )
    write(repo, {"app.py": "x = 1\n\n\ndef f():\n    pass  # TODO FLAG_ME\n"})
    gitc(repo, "add", "-A")


def test_3_gitattributes_cannot_hide_a_change_from_the_runner(repo):
    _hidden_change(repo)
    hits = sc.check_stub_markers(sc.staged_changeset(repo))
    assert hits and hits[0].startswith("app.py:5 TODO")


def test_3_gitattributes_cannot_hide_a_change_from_the_reviewer(repo, llm):
    _hidden_change(repo)
    rc, line, _ = review("--staged")
    assert rc == 1 and line.startswith("flagged:"), line
    assert "FLAG_ME" in llm.seen[-1]["body"]["messages"][0]["content"]
    rc, line, _ = review("--staged", "--whole-file")
    assert rc == 1 and "x = 1" in llm.seen[-1]["body"]["messages"][0]["content"]


def test_3_gitattributes_cannot_hide_a_change_from_the_static_wrapper(repo, tmp_path):
    _hidden_change(repo)
    tool, _log = fake_tool(
        tmp_path, "mypy", "app.py:5:5: error: boom  [name-defined]\n", rc=1
    )
    rc, line, _ = static(
        "--tool", "mypy", "--tool-bin", str(tool), "--staged", "--added-lines-only"
    )
    assert rc == 1 and line.startswith("flagged: app.py:5"), line


def test_3_a_binary_file_is_not_fed_to_the_heuristics(repo):
    commit(repo, "base", {"a.py": "x = 1\n"})
    (repo / "blob.py").write_bytes(b"# TODO\x00\x01\x02 binary\n# FIXME\x00\n")
    gitc(repo, "add", "-A")
    assert sc.check_stub_markers(sc.staged_changeset(repo)) == []


# ---------------------------------------------------------------------------
# 4. A blocking check that could not run blocks
# ---------------------------------------------------------------------------


def _gate_repo(repo, **extra):
    tool = dict(
        {
            "id": "gate",
            "failure_modes": ["logic_error"],
            "command": "printf '%s' {files} > /dev/null",
        },
        **extra,
    )
    commit(
        repo,
        "kit",
        {".saica/checks.json": config([tool], {"enabled": False}), "a.py": "x = 1\n"},
    )
    evil = repo / "zz\nname.py"
    evil.write_text("y = 1\n")
    gitc(repo, "add", "-A")


def test_4_a_blocking_check_that_could_not_run_blocks(repo, capsys):
    _gate_repo(repo, blocking=True)
    assert sc.main(["run", "--staged"]) == 1
    err = capsys.readouterr().err
    assert "gate" in err and "could not run on this change" in err and "on_error" in err
    assert pending(repo)["gate"]["outcome"] == "error"


def test_4_too_many_files_block_a_blocking_check(repo, capsys):
    tool = {
        "id": "gate",
        "failure_modes": ["logic_error"],
        "command": "true {files}",
        "blocking": True,
    }
    commit(repo, "kit", {".saica/checks.json": config([tool], {"enabled": False})})
    (repo / "d").mkdir()
    for i in range(1500):
        (
            repo
            / "d"
            / (
                "a_rather_long_file_name_to_fill_the_command_line_%04d_%s.py"
                % (i, "x" * 60)
            )
        ).write_text("")
    gitc(repo, "add", "-A")
    assert sc.main(["run", "--staged"]) == 1
    assert "too many changed files" in pending(repo)["gate"]["detail"]


def test_4_on_error_pass_and_non_blocking_checks_do_not_block(repo):
    _gate_repo(repo, blocking=True, on_error="pass")
    assert sc.main(["run", "--staged"]) == 0
    assert pending(repo)["gate"]["outcome"] == "error"


def test_4_a_check_that_is_not_blocking_does_not_block_on_error(repo):
    _gate_repo(repo)
    assert sc.main(["run", "--staged"]) == 0


def test_4_on_error_in_the_config():
    def cfg(**kw):
        t = dict({"id": "a", "failure_modes": ["logic_error"], "command": "true"}, **kw)
        return sc.parse_config({"tools": [t]})["tools"][0]

    assert cfg()["on_error"] == "pass"
    assert cfg(blocking=True)["on_error"] == "block"
    assert cfg(blocking=True, on_error="pass")["on_error"] == "pass"
    assert cfg(on_error="block")["on_error"] == "block"
    with pytest.raises(sc.SaicaError, match="on_error"):
        cfg(on_error="maybe")


# ---------------------------------------------------------------------------
# 5. A commit cannot replace or discard the event log
# ---------------------------------------------------------------------------

FORGED = (
    '{"v": 1, "tool_id": "forged", "outcome": "pass", "commit": "f", "source": "ci"}\n'
)


def test_5_ci_keeps_its_own_event_log_when_a_commit_tracks_one(repo, tmp_path):
    base = ci_repo(repo, {"enabled": True, "blocking": True})
    gitc(repo, "checkout", "-q", "-b", "feature")
    c1 = commit(repo, "a stub", {"feature.py": "def f():\n    pass  # TODO\n"})
    write(repo, {".saica/events.jsonl": FORGED})
    gitc(repo, "add", "-f", ".saica/events.jsonl")
    gitc(repo, "commit", "-q", "-m", "track a forged log", "--no-verify")
    c2 = gitc(repo, "rev-parse", "HEAD")
    r, out, events = ci_step(
        repo,
        tmp_path,
        EVENT_NAME="pull_request",
        EVENT_ACTION="opened",
        PR_BASE=base,
        PR_HEAD=c2,
        GITHUB_SHA=c2,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert all(e["tool_id"] != "forged" for e in events)
    stub = [
        e for e in events if e["commit"] == c1 and e["tool_id"] == "saica:stub-markers"
    ]
    assert (
        stub and stub[0]["outcome"] == "caught"
    )  # the first commit's row is still there
    tamper = [
        e for e in events if e["commit"] == c2 and e["tool_id"] == "saica:kit-tamper"
    ]
    assert (
        tamper
        and tamper[0]["outcome"] == "caught"
        and ".saica/events.jsonl" in tamper[0]["detail"]
    )
    assert "blocked=1" in out


def test_5_ci_keeps_its_event_log_when_a_commit_links_it_to_dev_null(repo, tmp_path):
    base = ci_repo(repo, {"enabled": True, "blocking": True})
    gitc(repo, "checkout", "-q", "-b", "feature")
    c1 = commit(repo, "a stub", {"feature.py": "def f():\n    pass  # TODO\n"})
    os.symlink("/dev/null", str(repo / ".saica" / "events.jsonl"))
    gitc(repo, "add", "-f", ".saica/events.jsonl")
    gitc(repo, "commit", "-q", "-m", "send the log away", "--no-verify")
    c2 = gitc(repo, "rev-parse", "HEAD")
    r, out, events = ci_step(
        repo,
        tmp_path,
        EVENT_NAME="pull_request",
        EVENT_ACTION="opened",
        PR_BASE=base,
        PR_HEAD=c2,
        GITHUB_SHA=c2,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert {e["commit"] for e in events} >= {c1, c2}
    assert "blocked=1" in out


def test_5_local_event_log_must_be_an_untracked_regular_file(repo, capsys):
    commit(repo, "kit", {".saica/checks.json": config([]), "a.py": "x = 1\n"})
    assert sc.main(["run", "--commit", "HEAD"]) == 0
    write(repo, {".saica/events.jsonl": FORGED})
    gitc(repo, "add", "-f", ".saica/events.jsonl")
    assert sc.main(["run", "--commit", "HEAD"]) == 2
    assert "tracked by git" in capsys.readouterr().err
    assert (
        sc.main(["run", "--staged"]) == 2
    )  # the commit that would track it is refused
    gitc(repo, "rm", "-q", "--cached", "-f", ".saica/events.jsonl")
    (repo / ".saica" / "events.jsonl").unlink()
    os.symlink("/dev/null", str(repo / ".saica" / "events.jsonl"))
    assert sc.main(["run", "--commit", "HEAD"]) == 2
    assert "symbolic link" in capsys.readouterr().err
    (repo / ".saica" / "events.jsonl").unlink()
    # a log outside the repository is fine when it is named on purpose (CI does this)
    outside = repo.parent / "out" / "events.jsonl"
    assert sc.main(["--events", str(outside), "run", "--commit", "HEAD"]) == 0
    assert (
        outside.read_text().strip() and not (repo / ".saica" / "events.jsonl").exists()
    )


def test_5_event_log_and_pending_file_are_kit_paths():
    assert sc.is_kit_path(".saica/events.jsonl") and sc.is_kit_path(
        ".saica/pending.jsonl"
    )
    assert not sc.is_kit_path(".saica/task.md") and not sc.is_kit_path(
        ".saica/dashboard.html"
    )


# ---------------------------------------------------------------------------
# 6. Files the reviewer leaves out by default are not "reviewed"
# ---------------------------------------------------------------------------


def test_6_default_excludes_make_the_result_partial(repo, llm):
    commit(repo, "base", {"prompt.txt": PROMPT, "app.py": "x = 1\n"})
    write(
        repo,
        {
            "app.py": "x = 2\n",
            "web/node_modules/pkg/index.js": "evil()\n",
            "static/app.min.js": "evil()\n",
            "deps.lock": "evil\n",
        },
    )
    gitc(repo, "add", "-A")
    rc, line, r = review("--staged")
    assert rc == 127 and line.startswith("partial:"), line
    for name in ("deps.lock", "static/app.min.js", "web/node_modules/pkg/index.js"):
        assert name in line
    assert "ok:" not in r.stdout
    rc, line, _ = review("--staged", "--per-file")
    assert rc == 127 and line.startswith("partial:") and "deps.lock" in line
    # accepted on purpose: ok, and the files are still named
    rc, line, _ = review(
        "--staged",
        "--exclude",
        "node_modules/",
        "--exclude",
        "*.min.js",
        "--exclude",
        "*.lock",
    )
    assert rc == 0 and line.startswith("ok:") and "3 files left out" in line
    # a finding in what was reviewed is still a finding
    write(repo, {"app.py": "x = 2  # FLAG_ME\n"})
    gitc(repo, "add", "-A")
    rc, line, _ = review("--staged")
    assert rc == 1 and line.startswith("flagged:") and "left out" in line


def test_6_only_excluded_files_is_partial_not_skipped(repo, llm):
    commit(repo, "base", {"prompt.txt": PROMPT})
    write(repo, {"vendor.min.js": "evil()\n"})
    gitc(repo, "add", "-A")
    rc, line, _ = review("--staged")
    assert (
        rc == 127
        and line.startswith("partial: nothing was reviewed")
        and "vendor.min.js" in line
    )
    assert llm.seen == []
    rc, line, _ = review("--staged", "--exclude", "*.min.js")
    assert rc == 0 and line.startswith("skipped:")


# ---------------------------------------------------------------------------
# 7. Static wrapper: renames into a checked extension, suppressions, config edits
# ---------------------------------------------------------------------------


def test_7_a_rename_into_a_checked_extension_counts_as_added(repo, tmp_path):
    commit(
        repo,
        "base",
        {"payload.txt": "import os\nos.system(input())\n" + "# filler\n" * 30},
    )
    gitc(repo, "mv", "payload.txt", "payload.py")
    tool, log = fake_tool(
        tmp_path, "mypy", "payload.py:2:1: error: boom  [name-defined]\n", rc=1
    )
    rc, line, _ = static(
        "--tool", "mypy", "--tool-bin", str(tool), "--staged", "--added-lines-only"
    )
    assert rc == 1 and line.startswith("flagged: payload.py:2"), line
    assert json.loads(log.read_text().splitlines()[0])[-1].endswith("payload.py")


def _ruff(tmp_path, items=()):
    return fake_tool(tmp_path, "ruff", json.dumps(list(items)), rc=1 if items else 0)[0]


def test_7_an_added_suppression_comment_is_never_ok(repo, tmp_path):
    commit(repo, "base", {"a.py": "x = 1\n"})
    write(repo, {"a.py": "x = 1\ny = undefined_name  # noqa: F821\n"})
    gitc(repo, "add", "-A")
    rc, line, _ = static(
        "--tool",
        "ruff",
        "--tool-bin",
        str(_ruff(tmp_path)),
        "--staged",
        "--added-lines-only",
        "--codes",
        "F821",
    )
    assert rc == 127 and line.startswith("partial:"), line
    assert "suppression" in line and "a.py:2" in line
    # with mypy the same line is not a suppression; `# type: ignore` is
    mypy, _log = fake_tool(tmp_path, "mypy", "", rc=0)
    rc, line, _ = static(
        "--tool", "mypy", "--tool-bin", str(mypy), "--staged", "--added-lines-only"
    )
    assert rc == 0 and line.startswith("ok:")
    write(repo, {"a.py": "x = 1\ny = undefined_name  # type: ignore[name-defined]\n"})
    gitc(repo, "add", "-A")
    rc, line, _ = static(
        "--tool", "mypy", "--tool-bin", str(mypy), "--staged", "--added-lines-only"
    )
    assert rc == 127 and "suppression" in line
    # a suppression that was already there is not the change's doing
    gitc(repo, "commit", "-q", "-m", "with ignore")
    write(repo, {"a.py": "x = 2\ny = undefined_name  # type: ignore[name-defined]\n"})
    gitc(repo, "add", "-A")
    rc, line, _ = static(
        "--tool", "mypy", "--tool-bin", str(mypy), "--staged", "--added-lines-only"
    )
    assert rc == 0 and line.startswith("ok:")


def test_7_an_edit_to_the_tools_own_config_is_never_ok(repo, tmp_path):
    pyproject = "[project]\nname = 'x'\n\n[tool.ruff]\nline-length = 100\n\n[tool.black]\nline-length = 100\n"
    commit(
        repo,
        "base",
        {
            "a.py": "x = 1\n",
            "ruff.toml": "line-length = 100\n",
            "pyproject.toml": pyproject,
        },
    )
    ruff = str(_ruff(tmp_path))
    base = ["--tool", "ruff", "--tool-bin", ruff, "--staged", "--added-lines-only"]
    write(
        repo, {"a.py": "x = 2\n", "ruff.toml": 'line-length = 100\nignore = ["F821"]\n'}
    )
    gitc(repo, "add", "-A")
    rc, line, _ = static(*base)
    assert (
        rc == 127
        and line.startswith("partial:")
        and "ruff.toml" in line
        and "configuration" in line
    )
    gitc(repo, "commit", "-q", "-m", "c")
    # only the config changes (no Python file): not "skipped"
    write(repo, {"ruff.toml": "line-length = 100\n"})
    gitc(repo, "add", "-A")
    rc, line, _ = static(*base)
    assert rc == 127 and line.startswith("partial:") and "ruff.toml" in line
    gitc(repo, "commit", "-q", "-m", "c")
    # the tool's section of pyproject.toml counts, another tool's section does not
    write(
        repo,
        {
            "a.py": "x = 3\n",
            "pyproject.toml": pyproject.replace(
                "[tool.ruff]\nline-length = 100",
                '[tool.ruff]\nline-length = 100\nignore = ["F821"]',
            ),
        },
    )
    gitc(repo, "add", "-A")
    rc, line, _ = static(*base)
    assert rc == 127 and "pyproject.toml" in line
    gitc(repo, "commit", "-q", "-m", "c")
    write(
        repo,
        {
            "a.py": "x = 4\n",
            "pyproject.toml": (repo / "pyproject.toml")
            .read_text()
            .replace(
                "[tool.black]\nline-length = 100", "[tool.black]\nline-length = 88"
            ),
        },
    )
    gitc(repo, "add", "-A")
    rc, line, _ = static(*base)
    assert rc == 0 and line.startswith("ok:"), line
    # with a counted finding the result is flagged and the note is added
    write(repo, {"a.py": "x = undefined_name\n", "ruff.toml": "line-length = 90\n"})
    gitc(repo, "add", "-A")
    finding = {
        "code": "F821",
        "message": "Undefined name",
        "filename": str(repo / "a.py"),
        "location": {"row": 1, "column": 5},
    }
    rc, line, _ = static(
        "--tool",
        "ruff",
        "--tool-bin",
        str(_ruff(tmp_path, [finding])),
        "--staged",
        "--added-lines-only",
    )
    assert rc == 1 and line.startswith("flagged: a.py:1 F821") and "ruff.toml" in line


# ---------------------------------------------------------------------------
# 8. At commit time the committed config and helpers judge the change
# ---------------------------------------------------------------------------

GATE = {
    "id": "gate",
    "failure_modes": ["security_vulnerability"],
    "command": "test ! -e BAD",
    "blocking": True,
}


def test_8_an_unstaged_config_edit_does_not_switch_the_checks_off(repo):
    commit(repo, "kit", {".saica/checks.json": config([GATE]), "a.py": "x = 1\n"})
    write(
        repo,
        {
            ".saica/checks.json": '{"builtin": {"enabled": false}, "tools": []}',
            "BAD": "x\n",
        },
    )
    gitc(repo, "add", "BAD")  # the weakened config stays unstaged
    assert sc.main(["run", "--staged"]) == 1
    by = pending(repo)
    assert by["gate"]["outcome"] == "caught"  # the committed gate still ran
    assert "saica:stub-markers" in by  # and the committed built-ins


def test_8_a_staged_config_edit_is_judged_by_the_committed_config(repo):
    commit(repo, "kit", {".saica/checks.json": config([GATE]), "a.py": "x = 1\n"})
    write(
        repo,
        {
            ".saica/checks.json": '{"builtin": {"enabled": false}, "tools": []}',
            "BAD": "x\n",
        },
    )
    gitc(repo, "add", "-A")
    assert sc.main(["run", "--staged"]) == 1
    by = pending(repo)
    assert by["gate"]["outcome"] == "caught"
    assert (
        by["saica:kit-tamper"]["outcome"] == "caught"
        and by["saica:kit-tamper"]["blocking"] is True
    )


def test_8_a_staged_helper_does_not_check_its_own_change(repo, monkeypatch):
    helper = {
        "id": "helper",
        "failure_modes": ["logic_error"],
        "command": "sh .saica/helper.sh",
        "blocking": True,
    }
    strict = "if [ -e BAD ]; then echo 'flagged: BAD is there'; exit 1; fi\necho 'ok: clean'\n"
    commit(
        repo,
        "kit",
        {
            ".saica/checks.json": config([helper]),
            ".saica/helper.sh": strict,
            "a.py": "x = 1\n",
        },
    )
    write(
        repo, {".saica/helper.sh": "echo 'ok: rewritten by the change'\n", "BAD": "x\n"}
    )
    gitc(repo, "add", "-A")
    assert sc.main(["run", "--staged"]) == 1
    by = pending(repo)
    assert (
        by["helper"]["outcome"] == "caught"
        and by["helper"]["detail"] == "flagged: BAD is there"
    )
    assert (
        by["saica:kit-tamper"]["outcome"] == "caught"
        and by["saica:kit-tamper"]["blocking"] is True
    )
    # a person can let a kit change through; the committed helper still judges it
    monkeypatch.setenv("SAICA_KIT_CHANGE_OK", "1")
    assert sc.main(["run", "--staged"]) == 1  # still blocked: by the helper's finding
    by = pending(repo)
    assert by["helper"]["outcome"] == "caught"
    assert (
        by["saica:kit-tamper"]["outcome"] == "caught"
        and by["saica:kit-tamper"]["blocking"] is False
    )


def test_8_kit_tamper_blocks_by_default_and_can_be_allowed(repo, monkeypatch, capsys):
    commit(repo, "kit", {".saica/checks.json": config([]), "a.py": "x = 1\n"})
    write(
        repo, {".saica/checks.json": config([], {"enabled": True, "blocking": False})}
    )
    gitc(repo, "add", "-A")
    assert sc.main(["run", "--staged"]) == 1
    assert "SAICA_KIT_CHANGE_OK" in capsys.readouterr().err
    monkeypatch.setenv("SAICA_KIT_CHANGE_OK", "1")
    assert sc.main(["run", "--staged"]) == 0
    assert (
        pending(repo)["saica:kit-tamper"]["outcome"] == "caught"
    )  # allowed, and still recorded
    monkeypatch.delenv("SAICA_KIT_CHANGE_OK")
    # the committed config may say that kit changes do not block
    gitc(repo, "reset", "-q", "--hard")
    commit(
        repo,
        "relax",
        {".saica/checks.json": config([], {"enabled": True, "tamper_blocking": False})},
    )
    write(repo, {".saica/notes.py": "x = 1\n"})
    gitc(repo, "add", "-A")
    assert sc.main(["run", "--staged"]) == 0
    assert pending(repo)["saica:kit-tamper"]["outcome"] == "caught"


def test_8_first_install_reads_the_staged_config_and_passes(repo):
    write(repo, {".saica/checks.json": config([GATE]), "a.py": "x = 1\n"})
    gitc(repo, "add", "-A")
    assert sc.main(["run", "--staged"]) == 0
    by = pending(repo)
    assert (
        by["gate"]["outcome"] == "pass" and by["saica:kit-tamper"]["outcome"] == "pass"
    )


def test_8_a_hooks_directory_in_the_work_tree_is_part_of_the_kit(repo):
    commit(
        repo,
        "kit",
        {
            ".saica/checks.json": config([]),
            "tools/hooks/pre-commit": "#!/bin/sh\nexit 0\n",
        },
    )
    gitc(repo, "config", "core.hooksPath", "tools/hooks")
    write(repo, {"tools/hooks/pre-commit": "#!/bin/sh\n# quiet now\nexit 0\n"})
    gitc(repo, "add", "-A")
    assert sc.check_kit_tamper(
        sc.staged_changeset(repo), sc.tracked_hooks_dir(repo)
    ) == ["tools/hooks/pre-commit"]
    events = sc.evaluate(
        sc.parse_config({"tools": []}),
        sc.staged_changeset(repo),
        repo,
        {"commit": "staged"},
        "manual",
        verbose=False,
    )
    tamper = [e for e in events if e["tool_id"] == "saica:kit-tamper"][0]
    assert (
        tamper["outcome"] == "caught" and "tools/hooks/pre-commit" in tamper["detail"]
    )


# ---------------------------------------------------------------------------
# 9. {files} inside a command substitution; commands without a shell
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    ["echo `wc -c {files}`", "echo $(wc -c {files})", 'echo "$(cat {files_from})"'],
)
def test_9_files_inside_a_command_substitution_is_refused(tmp_path, command):
    name = "a`touch PWNED9`.py"
    (tmp_path / name).write_text("x = 1\n")
    tool = {
        "id": "t",
        "command": command,
        "timeout_s": 30.0,
        "metric": None,
        "failure_modes": ["logic_error"],
    }
    outcome, detail, _ = sc.run_tool(tool, [name], tmp_path)
    assert outcome == "error" and "configuration error" in detail, detail
    assert not (tmp_path / "PWNED9").exists()


def test_9_a_command_without_shell_operators_runs_without_a_shell(tmp_path):
    assert sc.plain_argv("mytool --strict 'two words' {files}") == [
        "mytool",
        "--strict",
        "two words",
        "{files}",
    ]
    for needs_shell in (
        "a | b",
        "a > out",
        "a $HOME",
        "a *.py",
        "X=1 a",
        "a `b`",
        "a; b",
        "a --opt={files}",
        'a "{files}"',
    ):
        assert sc.plain_argv(needs_shell) is None, needs_shell
    dump = "import json, sys; json.dump(sys.argv[1:], open('argv.json', 'w'))"
    script = tmp_path / "dump.py"
    script.write_text(dump)
    names = [
        "plain.py",
        "-dash.py",
        "$(touch PWNED).py",
        "back`touch PWNED`tick.py",
        "new\nline.py",
        "sp ace.py",
    ]
    tool = {
        "id": "t",
        "command": "%s dump.py {files}" % shlex.quote(sys.executable),
        "timeout_s": 30.0,
        "metric": None,
        "failure_modes": ["logic_error"],
    }
    outcome, detail, _ = sc.run_tool(tool, names, tmp_path)
    assert outcome == "pass", detail
    assert (
        json.loads((tmp_path / "argv.json").read_text())
        == ["plain.py", "./-dash.py"] + names[2:]
    )
    assert not (tmp_path / "PWNED").exists()
    # a missing program is an error, as with the shell
    tool["command"] = "saica-no-such-binary-xyz {files}"
    assert sc.run_tool(tool, names, tmp_path)[0] == "error"


# ---------------------------------------------------------------------------
# 10. One "true" for the asked field is enough
# ---------------------------------------------------------------------------


def test_10_a_true_verdict_is_not_undone_by_a_quoted_false(repo, llm):
    answer = _reply({"model": "true-then-quote", "messages": [{"content": ""}]})[
        "choices"
    ][0]["message"]["content"]
    obj, field = rv.find_verdict(answer, "bad")
    assert rv.judge(obj, field, answer, "stop")[0] == "flagged"
    # a cut answer: any "true" for the field wins
    cut = '"bad": true, "evidence": "eval" ... the diff has {"bad": false ...'
    obj, field = rv.find_verdict(cut, "bad")
    assert rv.judge(obj, field, cut, "length")[0] == "flagged"
    # one verdict object: nothing changes
    obj, field = rv.find_verdict('{"bad": false, "evidence": ""}', "bad")
    assert rv.judge(obj, field, "", "stop")[0] == "ok"
    commit(repo, "base", {"prompt.txt": PROMPT, "a.py": "x = 1\n"})
    write(repo, {"a.py": "x = eval(input())\n"})
    gitc(repo, "add", "-A")
    rc, line, _ = review("--staged", model="true-then-quote")
    assert rc == 1 and line.startswith("flagged: calls eval on user input"), line


# ---------------------------------------------------------------------------
# 11. A verdict is never reused across endpoints or kit versions
# ---------------------------------------------------------------------------


def test_11_the_cache_key_holds_the_endpoint_and_the_kit_version(
    repo, llm, monkeypatch
):
    commit(repo, "base", {"prompt.txt": PROMPT, "a.py": "x = 1\n"})
    write(repo, {"a.py": "x = 2\n"})
    gitc(repo, "add", "-A")
    rc, line, _ = review("--staged", cache=True)
    rc2, line2, _ = review("--staged", cache=True)
    assert (rc, rc2) == (0, 0) and "(cached)" in line2 and len(llm.seen) == 1
    # another endpoint is another reviewer: no reuse
    monkeypatch.setenv("SAICA_LLM_API_BASE", llm.base.replace("/v1", "/other/v1"))
    rc, line, _ = review("--staged", cache=True)
    assert rc == 0 and "(cached)" not in line and len(llm.seen) == 2
    assert llm.seen[-1]["path"].startswith("/other/v1")
    args = rv.build_parser().parse_args(["--prompt", "p", "--model", "m"])
    args.extra_body = {}
    a = rv.cache_key(
        args, "bad", "prompt text", "https://one.example/v1/chat/completions"
    )
    b = rv.cache_key(
        args, "bad", "prompt text", "https://two.example/v1/chat/completions"
    )
    assert a != b
    monkeypatch.setattr(rv, "KIT_VERSION", rv.KIT_VERSION + "-next")
    assert (
        rv.cache_key(
            args, "bad", "prompt text", "https://one.example/v1/chat/completions"
        )
        != a
    )


# ---------------------------------------------------------------------------
# 12. File names that look like options; API keys only where they are needed
# ---------------------------------------------------------------------------


def test_12_file_names_are_anchored_and_come_after_a_double_dash(repo, tmp_path):
    commit(repo, "base", {"a.py": "x = 1\n"})
    write(repo, {"@resp.py": "x = 1\n", "-flag.py": "y = 1\n"})
    gitc(repo, "add", "-A")
    tool, log = fake_tool(tmp_path, "mypy", "", rc=0)
    rc, _line, _ = static("--tool", "mypy", "--tool-bin", str(tool), "--staged")
    assert rc == 0
    argv = json.loads(log.read_text().splitlines()[0])
    assert argv[-3:] == ["--", "./-flag.py", "./@resp.py"]
    tool, log = fake_tool(tmp_path, "pyright", '{"generalDiagnostics": []}', rc=0)
    rc, _line, _ = static("--tool", "pyright", "--tool-bin", str(tool), "--staged")
    argv = json.loads(log.read_text().splitlines()[0])
    assert rc == 0 and argv == [
        "--outputjson",
        "./-flag.py",
        "./@resp.py",
    ]  # pyright reads "--" as a path


def test_12_model_api_keys_reach_only_the_checks_that_name_them(tmp_path, monkeypatch):
    monkeypatch.setenv("AZURE_AI_API_KEY", "azure-secret")
    monkeypatch.setenv("HYPERBOLIC_API_KEY", "hyper-secret")
    monkeypatch.setenv("SAICA_LLM_API_KEY", "default-secret")
    monkeypatch.setenv("ORDINARY_SETTING", "kept")
    dump = "import json, os, sys; json.dump(dict(os.environ), open(sys.argv[1], 'w'))"
    (tmp_path / "saica_llm_review.py").write_text(dump)
    (tmp_path / "other.py").write_text(dump)
    py = shlex.quote(sys.executable)
    cfg = sc.parse_config(
        {
            "builtin": {"enabled": False},
            "tools": [
                {
                    "id": "azure",
                    "failure_modes": ["fabrication"],
                    "command": "%s saica_llm_review.py azure.json --api-key-env AZURE_AI_API_KEY"
                    % py,
                },
                {
                    "id": "hyper",
                    "failure_modes": ["scope_creep"],
                    "command": "%s saica_llm_review.py hyper.json --api-key-env=HYPERBOLIC_API_KEY"
                    % py,
                },
                {
                    "id": "default",
                    "failure_modes": ["obsolescence"],
                    "command": "%s saica_llm_review.py default.json" % py,
                },
                {
                    "id": "linter",
                    "failure_modes": ["logic_error"],
                    "command": "%s other.py linter.json" % py,
                },
            ],
        }
    )
    cs = sc.ChangeSet(["a.py"], {})
    events = sc.evaluate(
        cfg, cs, tmp_path, {"commit": "staged"}, "manual", verbose=False
    )
    assert {e["outcome"] for e in events if e["tool_id"]} == {"pass"}
    env = {
        name: json.loads((tmp_path / (name + ".json")).read_text())
        for name in ("azure", "hyper", "default", "linter")
    }
    keys = ("AZURE_AI_API_KEY", "HYPERBOLIC_API_KEY", "SAICA_LLM_API_KEY")
    assert [k for k in keys if k in env["azure"]] == ["AZURE_AI_API_KEY"]
    assert [k for k in keys if k in env["hyper"]] == ["HYPERBOLIC_API_KEY"]
    assert [k for k in keys if k in env["default"]] == ["SAICA_LLM_API_KEY"]
    assert [
        k for k in keys if k in env["linter"]
    ] == []  # a linter gets no model key at all
    assert all(e["ORDINARY_SETTING"] == "kept" and "PATH" in e for e in env.values())
