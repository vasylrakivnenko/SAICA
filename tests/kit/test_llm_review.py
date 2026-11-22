"""Tests for the LLM reviewer of the kit (site/public/kit/saica_llm_review.py).

The model is always a fake chat-completions server on 127.0.0.1 inside the
test process: no network beyond the loopback interface, no paid call.

What is covered (review issues I2, I5, I6, I9; evidence KT-02, KT-06, KT-07,
KT-16, KT-19): a change that was not read in full is never `ok`; an unfilled
prompt is an error before any request; the kit's own files, lock files,
minified and binary files are left out and code goes first; the input adapters
(--context-lines, --per-file, --whole-file); the verdict cache; credentials in
the base URL never reach the output; the answer parser agrees with the
benchmark's (bench/common.py).
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "site" / "public" / "kit"
REVIEW = KIT / "saica_llm_review.py"
KEY = "sk-test-0123456789abcdef"

PROMPT = """# test reviewer

```text
Is this change bad?
<task>
{task}
</task>
<diff>
{diff}
</diff>
Answer with one JSON object only:
{{"bad": true or false, "evidence": "<what, or empty>"}}
```
"""


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    prev, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


rv = _load("saica_llm_review_kit", REVIEW)


# ---------------------------------------------------------------------------
# Fake model, scratch repository
# ---------------------------------------------------------------------------


def _reply(body: dict):
    """Flags a prompt that holds a marker; `garbage` and `http500` models misbehave."""
    model = body.get("model")
    prompt = body["messages"][0]["content"]
    if model == "http500":
        return 500, {"error": {"message": "upstream exploded"}}
    if model == "garbage":
        text = "I am not sure; it depends."
    elif "os.system(input())" in prompt or "FLAG_ME" in prompt:
        text = 'Thinking.\n```json\n{"bad": true, "evidence": "runs user input as a command"}\n```'
    else:
        text = '{"bad": false, "evidence": ""}'
    return 200, {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {},
    }


@pytest.fixture
def llm():
    seen: list = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            body = json.loads(raw.decode("utf-8"))
            seen.append(
                {"path": self.path, "headers": dict(self.headers), "body": body}
            )
            status, payload = _reply(body)
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.seen = seen
    server.base = "http://127.0.0.1:%d/v1" % server.server_address[1]
    yield server
    server.shutdown()
    server.server_close()


def gitc(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch, llm):
    for key in list(os.environ):
        if key.startswith("GIT_") or key.startswith("SAICA_"):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("SAICA_LLM_API_BASE", llm.base)
    monkeypatch.setenv("SAICA_LLM_API_KEY", KEY)
    monkeypatch.setenv("SAICA_CACHE_DIR", str(tmp_path / "verdict-cache"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    root = tmp_path / "repo"
    (root / ".saica" / "prompts").mkdir(parents=True)
    gitc(root, "init", "-q")
    gitc(root, "config", "user.name", "Test Human")
    gitc(root, "config", "user.email", "human@example.invalid")
    gitc(root, "config", "commit.gpgsign", "false")
    (root / ".saica" / "prompts" / "bad.md").write_text(PROMPT)
    (root / "app.py").write_text(
        "".join("line_%02d = %d\n" % (i, i) for i in range(1, 41))
    )
    gitc(root, "add", "-A")
    gitc(root, "commit", "-q", "-m", "base")
    monkeypatch.chdir(root)
    return root


def review(
    *args,
    model="m",
    prompt=".saica/prompts/bad.md",
    cache=False,
    python=sys.executable,
    env=None,
):
    cmd = [
        python,
        "-B",
        str(REVIEW),
        "--prompt",
        prompt,
        "--model",
        model,
        "--retries",
        "0",
    ]
    if not cache:
        cmd.append("--no-cache")
    r = subprocess.run(
        cmd + list(args), capture_output=True, text=True, timeout=120, env=env
    )
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return r.returncode, (lines[-1] if lines else ""), r


def sent(llm, i=-1):
    return llm.seen[i]["body"]["messages"][0]["content"]


def stage(repo, files):
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            p.write_bytes(text)
        else:
            p.write_text(text)
    gitc(repo, "add", "-A", "-f")


# ---------------------------------------------------------------------------
# 1. A change that was not read in full is never `ok` (KT-06)
# ---------------------------------------------------------------------------

LOCK = json.dumps(
    {"packages": {"pkg-%05d" % i: {"version": "1.0.%d" % i} for i in range(6000)}},
    indent=1,
)
BACKDOOR = "import os\n\n\ndef run():\n    os.system(input())\n"


def test_backdoor_behind_a_big_lock_file_is_reviewed(repo, llm):
    """The review's case: a 200 KB lock file sorts before zz_backdoor.py. It is left out, so the code is read."""
    stage(
        repo,
        {"aa-lock.json": LOCK, "package-lock.json": LOCK, "zz_backdoor.py": BACKDOOR},
    )
    rc, line, _ = review("--staged", "--exclude", "aa-lock.json")
    assert rc == 1 and line.startswith("flagged: runs user input as a command")
    assert "os.system(input())" in sent(llm) and "pkg-00001" not in sent(llm)
    assert "2 files left out" in line


def test_code_goes_first_so_a_cut_drops_data_not_code(repo, llm):
    stage(repo, {"aa-data.json": LOCK, "zz_backdoor.py": BACKDOOR})
    rc, line, _ = review(
        "--staged", "--no-default-excludes", "--max-diff-chars", "2000"
    )
    assert rc == 1 and line.startswith("flagged:")
    assert "partial review: first" in line  # flagged, and it says the rest was not read
    assert "os.system(input())" in sent(llm) and "pkg-00001" not in sent(llm)


def test_a_cut_diff_without_a_finding_is_partial_never_ok(repo, llm):
    stage(repo, {"a.py": "a = 1\n" * 400, "b.py": "b = 2\n" * 400})
    rc, line, r = review("--staged", "--max-diff-chars", "3000")
    assert rc == 127
    assert line.startswith("partial: no finding in the first") and "b.py" in line
    assert "ok:" not in r.stdout
    assert "b = 2" not in sent(llm)
    # the whole diff fits: an ordinary ok
    rc, line, _ = review("--staged")
    assert rc == 0 and line.startswith("ok: bad=false")


def test_one_file_over_the_limit_is_cut_and_partial(repo, llm):
    stage(repo, {"big.py": "value = 1\n" * 2000})
    rc, line, _ = review("--staged", "--max-diff-chars", "1500")
    assert rc == 127 and line.startswith("partial:") and "the rest of big.py" in line


# ---------------------------------------------------------------------------
# 2. An unfilled prompt is an error before any request (KT-06 b)
# ---------------------------------------------------------------------------


def test_missing_fill_is_an_error_without_a_request(repo, llm):
    (repo / "tm.txt").write_text(
        'Rule: {rule}\nSession:\n{transcript}\nAnswer: {{"bad": true or false}}\n'
    )
    stage(repo, {"x.py": "x = 1\n"})
    for extra in ([], ["--dry-run"]):
        rc, line, _ = review("--staged", *extra, prompt="tm.txt")
        assert rc == 127
        assert (
            line.startswith("error:")
            and "needs --fill NAME=FILE for {rule}, {transcript}" in line
        )
    assert llm.seen == []
    (repo / "rule.txt").write_text("Do not edit tests.\n")
    (repo / "session.txt").write_text("[1] USER: fix it FLAG_ME\n")
    (repo / "empty.txt").write_text("  \n")
    rc, line, _ = review(
        "--staged",
        "--fill",
        "rule=rule.txt",
        "--fill",
        "transcript=empty.txt",
        prompt="tm.txt",
    )
    assert rc == 127 and "is empty" in line and llm.seen == []
    rc, line, _ = review(
        "--staged",
        "--fill",
        "rule=rule.txt",
        "--fill",
        "transcript=session.txt",
        prompt="tm.txt",
    )
    assert rc == 1 and len(llm.seen) == 1
    assert "Do not edit tests." in sent(llm) and "[1] USER: fix it" in sent(llm)
    rc, line, _ = review(
        "--staged",
        "--fill",
        "rule=rule.txt",
        "--allow-empty",
        "transcript",
        prompt="tm.txt",
    )
    assert rc == 0 and len(llm.seen) == 2  # empty on purpose
    rc, line, _ = review(
        "--staged",
        "--fill",
        "rule=no-such-file.txt",
        "--allow-empty",
        "transcript",
        prompt="tm.txt",
    )
    assert rc == 127 and "--fill file not found" in line


def test_a_prompt_that_would_not_carry_the_change_is_an_error(repo, llm):
    (repo / "nodiff.txt").write_text('Task: {task}\nAnswer: {{"bad": true or false}}\n')
    stage(repo, {"x.py": "x = 1\n"})
    rc, line, _ = review("--staged", prompt="nodiff.txt")
    assert rc == 127 and "the change would not be sent" in line and llm.seen == []


# ---------------------------------------------------------------------------
# 3. What is left out, and what comes first (KT-06 c)
# ---------------------------------------------------------------------------


def test_default_excludes_and_order(repo, llm):
    stage(
        repo,
        {
            ".saica/checks.json": '{"KIT_MARKER": 1}\n',
            "package-lock.json": '{"LOCK_MARKER": 1}\n',
            "poetry.lock": "LOCK_MARKER\n",
            "web/app.min.js": "MIN_MARKER\n",
            "web/node_modules/x/index.js": "MODULE_MARKER\n",
            "logo.png": b"\x89PNG\r\n\x1a\n\x00\x00BINARY_MARKER\x00\xff",
            "README.md": "DOC_MARKER\n",
            "zz_code.py": "CODE_MARKER = 1\n",
            "requirements.txt": "MANIFEST_MARKER==1.0\n",
        },
    )
    # Six changed files are not sent. Nobody asked to leave them out, so the
    # change was not reviewed in full: partial, never ok.
    rc, line, _ = review("--staged")
    assert rc == 127 and line.startswith(
        "partial: no finding in the files that were reviewed"
    )
    assert "left out by default" in line and "--exclude" in line
    body = sent(llm)
    for gone in (
        "KIT_MARKER",
        "LOCK_MARKER",
        "MIN_MARKER",
        "MODULE_MARKER",
        "BINARY_MARKER",
    ):
        assert gone not in body, gone
    # code and dependency manifests first, documentation after them
    assert (
        body.index("MANIFEST_MARKER")
        < body.index("CODE_MARKER")
        < body.index("DOC_MARKER")
    )
    # left out on purpose: ok, with the files named and the missing task noted
    accept = [
        x
        for pat in (
            ".saica/",
            "*.lock",
            "package-lock.json",
            "*.min.js",
            "node_modules/",
            "*.png",
        )
        for x in ("--exclude", pat)
    ]
    rc, line, _ = review("--staged", *accept)
    assert rc == 0 and line.startswith("ok: bad=false")
    assert "6 files left out" in line and "no task file" in line
    rc, line, _ = review(
        "--staged",
        "--no-default-excludes",
        "--exclude",
        "*.md",
        "--exclude",
        "web/",
        "--exclude",
        "*.png",
    )
    body = sent(llm)
    assert rc == 0 and "KIT_MARKER" in body and "LOCK_MARKER" in body
    assert (
        "DOC_MARKER" not in body
        and "MIN_MARKER" not in body
        and "MODULE_MARKER" not in body
    )


def test_nothing_left_to_review_is_skipped_without_a_request(repo, llm):
    stage(repo, {".saica/notes.txt": "kit\n", "yarn.lock": "lock\n"})
    rc, line, _ = review("--staged")  # changed, and not reviewed: partial
    assert rc == 127 and line.startswith("partial: nothing was reviewed")
    rc, line, _ = review("--staged", "--exclude", ".saica/", "--exclude", "yarn.lock")
    assert rc == 0 and line.startswith(
        "skipped: no reviewable changes (2 files left out"
    )
    gitc(repo, "commit", "-q", "-m", "kit files")
    rc, line, _ = review("--staged")
    assert rc == 0 and line.startswith("skipped: no changes to review")
    assert llm.seen == []


def test_task_file_and_notes(repo, llm):
    stage(repo, {"x.py": "x = 1\n"})
    (repo / ".saica" / "task.md").write_text("Add x. TASK_MARKER\n")
    rc, line, _ = review("--staged")
    assert rc == 0 and "TASK_MARKER" in sent(llm) and "no task file" not in line
    assert (
        "task.md" not in sent(llm).split("<diff>")[1]
    )  # .saica/ is not part of the diff


# ---------------------------------------------------------------------------
# 4. Input adapters (KT-02)
# ---------------------------------------------------------------------------


def _edit_line_20(repo):
    text = (repo / "app.py").read_text().replace("line_20 = 20\n", "line_20 = 2000\n")
    (repo / "app.py").write_text(text)
    gitc(repo, "add", "-A")


def test_context_lines(repo, llm):
    _edit_line_20(repo)
    review("--staged")
    assert "line_17 = 17" in sent(llm) and "line_10 = 10" not in sent(
        llm
    )  # git's default: 3
    review("--staged", "--context-lines", "15")
    body = sent(llm)  # ("line_04" can still show up in the hunk header after "@@")
    assert "\n line_05 = 5\n" in body and "\n line_35 = 35\n" in body
    assert "\n line_04 = 4\n" not in body and "\n line_36 = 36\n" not in body
    gitc(repo, "commit", "-q", "-m", "edit")
    review("--commit", "HEAD", "--context-lines", "0")
    assert "\n line_19 = 19\n" not in sent(llm) and "+line_20 = 2000" in sent(llm)
    (repo / "c.diff").write_text(gitc(repo, "show", "HEAD"))
    rc, line, _ = review("--diff-file", "c.diff", "--context-lines", "15")
    assert rc == 127 and "cannot be used with --diff-file" in line


def test_per_file_one_request_per_file(repo, llm):
    stage(
        repo,
        {
            "a.py": "a = 1\n",
            "b.py": "b = 2  # FLAG_ME\n",
            "c.py": "c = 3\n",
            "yarn.lock": "x\n",
        },
    )
    rc, line, _ = review("--staged", "--per-file")
    assert rc == 1 and len(llm.seen) == 3
    assert line.startswith("flagged: b.py: runs user input")
    bodies = [s["body"]["messages"][0]["content"] for s in llm.seen]
    assert sum("a = 1" in b for b in bodies) == 1 and all(
        b.count("diff --git") == 1 for b in bodies
    )
    # no finding: every file reviewed -> ok; over the cap -> partial, never ok
    gitc(
        repo, "rm", "-q", "--cached", "yarn.lock"
    )  # (a lock file alone would make it partial)
    (repo / "yarn.lock").unlink()
    (repo / "b.py").write_text("b = 2\n")
    gitc(repo, "add", "-A")
    rc, line, _ = review("--staged", "--per-file")
    assert rc == 0 and line.startswith("ok: 3 file(s) reviewed, none flagged")
    rc, line, _ = review("--staged", "--per-file", "--max-files", "2")
    assert (
        rc == 127
        and line.startswith("partial: no finding in 2 of 3 file(s)")
        and "c.py" in line
    )


def test_per_file_failures_are_partial_or_error(repo, llm):
    stage(repo, {"a.py": "a = 1\n", "b.py": "b = 2\n"})
    rc, line, _ = review("--staged", "--per-file", model="garbage")
    assert rc == 127 and line.startswith("error: no file could be reviewed")
    rc, line, _ = review("--staged", "--per-file", model="http500")
    assert rc == 127 and line.startswith("error:") and "HTTP 500" in line
    rc, line, _ = review("--staged", "--per-file", "--prompt", ".saica/prompts/bad.md")
    assert (
        rc == 127 and "combined mode" in line
    )  # a prompt named twice is not a per-file run


def test_whole_file(repo, llm):
    _edit_line_20(repo)
    stage(repo, {"new.py": "fresh = 1\n"})
    gitc(
        repo, "rm", "-q", "--cached", ".saica/prompts/bad.md"
    )  # a deletion (and a left-out file)
    rc, line, _ = review("--staged", "--whole-file", "--exclude", ".saica/")
    assert rc == 0 and len(llm.seen) == 2
    app = [
        s["body"]["messages"][0]["content"]
        for s in llm.seen
        if "line_01" in s["body"]["messages"][0]["content"]
    ][0]
    assert "line_01 = 1" in app and "line_40 = 40" in app and "line_20 = 2000" in app
    assert "@@" not in app and "diff --git" not in app
    gitc(repo, "commit", "-q", "-m", "edit")
    (repo / "app.py").write_text(
        "WORKTREE_ONLY = 1\n"
    )  # not part of the commit under review
    llm.seen.clear()
    rc, line, _ = review("--commit", "HEAD", "--whole-file", "--exclude", ".saica/")
    assert rc == 0 and all(
        "WORKTREE_ONLY" not in s["body"]["messages"][0]["content"] for s in llm.seen
    )
    rc, line, _ = review("--diff-file", "x.diff", "--whole-file")
    assert rc == 127 and "cannot be used with --diff-file" in line


# ---------------------------------------------------------------------------
# 5. Verdict cache (KT-07)
# ---------------------------------------------------------------------------


def test_identical_request_is_answered_from_the_cache(repo, llm, tmp_path):
    stage(repo, {"a.py": "a = 1  # FLAG_ME\n"})
    rc1, line1, _ = review("--staged", cache=True)
    rc2, line2, _ = review("--staged", cache=True)
    assert (rc1, rc2) == (1, 1) and len(llm.seen) == 1
    assert "(cached)" in line2 and "(cached)" not in line1
    assert line2.replace(" (cached)", "") == line1
    assert list((tmp_path / "verdict-cache").glob("*.json"))
    review("--staged")  # --no-cache: a request again
    assert len(llm.seen) == 2
    review("--staged", "--temperature", "0", cache=True)  # other settings: another key
    assert len(llm.seen) == 3
    (repo / "a.py").write_text("a = 2\n")
    gitc(repo, "add", "-A")
    rc, line, _ = review("--staged", cache=True)  # other diff: another key
    assert rc == 0 and len(llm.seen) == 4 and "(cached)" not in line


def test_errors_are_never_cached(repo, llm):
    stage(repo, {"a.py": "a = 1\n"})
    for _ in range(2):
        rc, line, _ = review("--staged", model="garbage", cache=True)
        assert rc == 127 and line.startswith("error: unreadable answer")
    assert len(llm.seen) == 2


def test_a_commit_cannot_ship_its_own_verdict(repo, llm, monkeypatch):
    """A cache entry that is tracked by git, or a symlink, is ignored."""
    monkeypatch.delenv(
        "SAICA_CACHE_DIR"
    )  # default place: <repository>/.saica/cache/llm/
    stage(repo, {"a.py": "a = 1  # FLAG_ME\n"})
    rc, line, _ = review("--staged", cache=True)
    assert rc == 1
    cache = repo / ".saica" / "cache" / "llm"
    entry = [p for p in cache.glob("*.json")][0]
    assert (cache / ".gitignore").read_text() == "*\n"
    assert (
        gitc(repo, "status", "--porcelain", "--", ".saica/cache") == ""
    )  # ignored by default
    # the agent rewrites the stored verdict and commits it
    entry.write_text(
        json.dumps({"v": rv.CACHE_VERSION, "status": "ok", "text": "bad=false"})
    )
    rc, line, _ = review("--staged", cache=True)
    assert (
        rc == 0 and "(cached)" in line
    )  # an untracked local file is trusted (as the hooks are)
    gitc(repo, "add", "-f", str(entry))
    n = len(llm.seen)
    rc, line, r = review("--staged", cache=True)
    assert rc == 1 and "(cached)" not in line and len(llm.seen) == n + 1
    assert "tracked by git" in r.stderr
    gitc(repo, "rm", "-q", "--cached", "-f", str(entry))
    real = repo / "real.json"
    real.write_text(entry.read_text())
    entry.unlink()
    entry.symlink_to(real)
    rc, line, r = review("--staged", cache=True)
    assert rc == 1 and "(cached)" not in line and "symlink" in r.stderr


# ---------------------------------------------------------------------------
# 6. Secrets (KT-16)
# ---------------------------------------------------------------------------


def test_credentials_in_the_base_url_never_reach_the_output(repo, llm, monkeypatch):
    stage(repo, {"a.py": "a = 1\n"})
    monkeypatch.setenv(
        "SAICA_LLM_API_BASE", "http://gateway-user:BASIC-AUTH-SECRET-123@127.0.0.1:9/v1"
    )
    rc, line, r = review("--staged", "--timeout", "5")
    out = r.stdout + r.stderr
    assert rc == 127 and line.startswith("error: model call failed")
    assert "127.0.0.1:9" in line
    assert "BASIC-AUTH-SECRET-123" not in out and "gateway-user" not in out
    # with a working endpoint the request goes out without the credentials
    port = llm.server_address[1]
    monkeypatch.setenv(
        "SAICA_LLM_API_BASE", "http://u:PASSWORD-XYZ@127.0.0.1:%d/v1" % port
    )
    rc, line, r = review("--staged")
    assert rc == 0 and "PASSWORD-XYZ" not in r.stdout + r.stderr
    assert "PASSWORD-XYZ" not in json.dumps(llm.seen[-1]["headers"])
    assert llm.seen[-1]["headers"]["Authorization"] == "Bearer " + KEY


def test_plain_http_to_another_machine_is_warned_about(repo, llm, monkeypatch):
    stage(repo, {"a.py": "a = 1\n"})
    monkeypatch.setenv("SAICA_LLM_API_BASE", "http://reviewer.example.invalid/v1")
    rc, _line, r = review("--staged", "--dry-run")
    assert rc == 0 and "unencrypted" in r.stderr
    monkeypatch.setenv("SAICA_LLM_API_BASE", "https://reviewer.example.invalid/v1")
    rc, _line, r = review("--staged", "--dry-run")
    assert "unencrypted" not in r.stderr
    monkeypatch.setenv("SAICA_LLM_API_BASE", llm.base)
    rc, _line, r = review("--staged", "--dry-run")
    assert "unencrypted" not in r.stderr and llm.seen == []


def test_key_is_redacted_and_missing_settings_are_errors(repo, llm, monkeypatch):
    stage(repo, {"a.py": "a = 1\n"})
    rc, line, r = review("--staged", "--dry-run")
    assert KEY not in r.stdout + r.stderr
    monkeypatch.delenv("SAICA_LLM_API_KEY")
    rc, line, _ = review("--staged")
    assert rc == 127 and "SAICA_LLM_API_KEY" in line and llm.seen == []
    monkeypatch.delenv("SAICA_LLM_API_BASE")
    rc, line, _ = review("--staged", "--per-file")
    assert rc == 127 and line.startswith("error:") and "SAICA_LLM_API_BASE" in line


# ---------------------------------------------------------------------------
# 7. The parser agrees with the benchmark's (KT-19)
# ---------------------------------------------------------------------------

ANSWERS = [
    '{"bad": true, "evidence": "x"}',
    '{"bad": false, "evidence": ""}',
    'Sure.\n```json\n{"bad": true, "evidence": "fenced"}\n```\nDone.',
    '<think>{"bad": true}</think>\n{"bad": false, "evidence": ""}',
    '{"bad": false}\nOn reflection:\n{"bad": true, "evidence": "second object wins"}',
    '{"bad": true, "evidence": "cut before the closing bra',
    'first "bad": false ... then, cut: {"bad": true, "evid',
    'Answer with one JSON object only: {"bad": true or false, "evidence": "<what>"}',
    'The format is {"bad": true|false}. I cannot decide.',
    '{"bad": "yes", "evidence": "not a boolean"}',
    '{"bad": null}',
    '{"other": true}',
    "I am not sure; it depends.",
    "",
    '{"bad": true, "evidence": "nested {braces} and \\"quotes\\""}',
    '{"verdict": {"bad": true}}',
]


def test_parser_matches_the_benchmark_parser():
    sys.path.insert(0, str(REPO / "bench"))
    try:
        import common
    finally:
        sys.path.remove(str(REPO / "bench"))
    for answer in ANSWERS:
        want = common.read_answer(answer, "bad")
        obj, field = rv.find_verdict(answer, "bad")
        status, _text = rv.judge(obj, field, answer, "stop")
        got = {
            "flagged": (True, True),
            "ok": (False, True),
            "unreadable": (False, False),
        }[status]
        assert got == (want["flag"], want["parse_ok"]), answer


def test_flag_field_is_read_from_the_template():
    block = rv.first_fenced_block(PROMPT)
    assert rv.detect_flag_field(block) == "bad"
    assert rv.placeholder_names(block) == ["task", "diff"]
    filled, unknown = rv.fill_template(block, {"task": "T", "diff": "D"})
    assert (
        unknown == []
        and '{"bad": true or false, "evidence": "<what, or empty>"}' in filled
    )


# ---------------------------------------------------------------------------
# 8. Diff handling details
# ---------------------------------------------------------------------------


def test_split_diff_round_trip_and_paths():
    diff = (
        "diff --git a/a b.py b/a b.py\nindex 1..2 100644\n--- a/a b.py\t\n+++ b/a b.py\t\n@@ -1 +1 @@\n-x\n+y\n"
        'diff --git "a/\\303\\274.py" "b/\\303\\274.py"\nnew file mode 100644\n--- /dev/null\n+++ "b/\\303\\274.py"\n@@ -0,0 +1 @@\n+z\n'
        "diff --git a/img.png b/img.png\nBinary files a/img.png and b/img.png differ\n"
        "diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n"
        "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\n--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-q\n"
    )
    sections = rv.split_diff(diff)
    assert "".join(s.text for s in sections) == diff
    assert [s.path for s in sections] == [
        "a b.py",
        "ü.py",
        "img.png",
        "new.py",
        "gone.py",
    ]
    assert [s.binary for s in sections] == [False, False, True, False, False]
    assert sections[-1].deleted
    kept, left, unasked = rv.select_sections(sections, ["gone.py"], True)
    assert unasked == ["img.png"]  # binary: left out, but nobody asked for that
    assert left == ["img.png", "gone.py"] and [s.path for s in kept] == [
        "a b.py",
        "ü.py",
        "new.py",
    ]


@pytest.mark.parametrize(
    "path, pattern, hit",
    [
        (".saica/checks.json", ".saica/", True),
        ("pkg/.saica/x", ".saica/", True),
        ("src/saica/x.py", ".saica/", False),
        ("web/node_modules/a/b.js", "node_modules/", True),
        ("deep/dir/Cargo.lock", "Cargo.lock", True),
        ("a/b/app.min.js", "*.min.js", True),
        ("a/b/app.js", "*.min.js", False),
        ("docs/guide.md", "docs/*.md", True),
    ],
)
def test_path_matches(path, pattern, hit):
    assert rv.path_matches(path, pattern) is hit


def test_endpoint_url_drops_userinfo_and_keeps_the_rest():
    url = rv.endpoint_url("https://u:p@host.example:8443/openai/v1/?x=1", "2024-10-21")
    assert (
        url
        == "https://host.example:8443/openai/v1/chat/completions?x=1&api-version=2024-10-21"
    )
    assert rv.endpoint_name("http://u:p@[::1]:9/v1") == "[::1]:9"
    assert (
        rv.is_loopback("127.0.0.2")
        and rv.is_loopback("localhost")
        and not rv.is_loopback("10.0.0.1")
    )
    with pytest.raises(rv.ReviewError):
        rv.endpoint_url("ftp://host/v1", None)


# ---------------------------------------------------------------------------
# 9. Python 3.9
# ---------------------------------------------------------------------------


def test_cli_runs_under_python_3_9(repo, llm):
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
    stage(repo, {"a.py": "a = 1  # FLAG_ME\n", "b.py": "b = 1\n"})
    rc, line, _ = review(
        "--staged", "--per-file", "--context-lines", "15", python=py39, cache=True
    )
    assert rc == 1 and line.startswith("flagged: a.py:")
    rc, line, _ = review(
        "--staged", "--per-file", "--context-lines", "15", python=py39, cache=True
    )
    assert rc == 1 and "cached" in line and len(llm.seen) == 2
    rc, line, _ = review("--staged", "--whole-file", python=py39)
    assert rc == 1
