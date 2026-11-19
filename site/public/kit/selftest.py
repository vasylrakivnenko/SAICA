#!/usr/bin/env python3
"""SAICA supervision kit: end-to-end self-test (stdlib only).

Two parts:

* sandbox: builds a throwaway git repo in a temp dir, copies the runner and
  hooks into it with a test checks.json (built-ins plus fake ``sh`` tools, no
  real supervision tools needed), installs the hooks and proves that
  (a) a planted stub is ``caught`` after stamp, (b) a failing blocking tool
  blocks the commit, (c) events.jsonl matches the contract, (d) uncovered
  failure modes get ``not_covered`` events, (e) ``dashboard`` embeds events.
* repo: checks a real install (default: the current repo): .saica/checks.json
  is valid, hooks are installed and call the runner, runnable tools' binaries
  are on PATH (warning only), and the dashboard template is present.

Usage::

    python3 .saica/selftest.py              # sandbox + repo (repo skipped if no .saica/)
    python3 .saica/selftest.py --sandbox    # sandbox only
    python3 .saica/selftest.py --repo [DIR] # repo check only

Exit code 0 when every check passes (warnings allowed), 1 otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent

FAILURE_MODES = (
    "scope_creep",
    "fabrication",
    "security_vulnerability",
    "supply_chain_attack",
    "logic_error",
    "cascading_failure",
    "context_pollution",
    "obsolescence",
    "test_manipulation",
    "dependency_blindness",
    "incomplete_execution",
)
OUTCOMES = {"pass", "caught", "error", "skipped", "not_runnable", "not_covered"}
SOURCES = {"pre-commit", "ci", "replay", "manual"}
AGENTS = {None, "claude", "copilot", "cursor", "devin", "codex", "aider", "bot"}
EVENT_KEYS = (
    "v",
    "ts",
    "commit",
    "commit_ts",
    "subject",
    "agent",
    "kit",
    "source",
    "tool_id",
    "failure_mode",
    "outcome",
    "blocking",
    "detail",
    "metric",
    "metric_name",
)
_TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

MINIMAL_TEMPLATE = """<!doctype html><title>SAICA dashboard (selftest stub)</title>
<script id="saica-events" type="application/json">[]</script>
"""


class Report:
    def __init__(self) -> None:
        self.failed = 0
        self.warned = 0

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        print(
            "  [%s] %s%s"
            % (
                "PASS" if ok else "FAIL",
                label,
                (" - " + detail) if detail and not ok else "",
            )
        )
        if not ok:
            self.failed += 1
        return ok

    def warn(self, label: str) -> None:
        print("  [WARN] %s" % label)
        self.warned += 1

    def skip(self, label: str) -> None:
        print("  [SKIP] %s" % label)


def validate_event(ev: object) -> List[str]:
    """Return a list of contract violations for one event (empty = valid)."""
    if not isinstance(ev, dict):
        return ["not an object"]
    errs = []
    missing = [k for k in EVENT_KEYS if k not in ev]
    if missing:
        errs.append("missing keys: %s" % ", ".join(missing))
        return errs
    if ev["v"] != 1:
        errs.append("v != 1")
    if not isinstance(ev["ts"], str) or not _TS_RE.match(ev["ts"]):
        errs.append("bad ts %r" % ev["ts"])
    if not isinstance(ev["commit"], str) or not (
        ev["commit"] == "staged" or _SHA_RE.match(ev["commit"])
    ):
        errs.append("bad commit %r" % ev["commit"])
    if ev["commit_ts"] is not None and not (
        isinstance(ev["commit_ts"], str) and _TS_RE.match(ev["commit_ts"])
    ):
        errs.append("bad commit_ts %r" % ev["commit_ts"])
    if ev["subject"] is not None and not isinstance(ev["subject"], str):
        errs.append("bad subject")
    if ev["agent"] not in AGENTS:
        errs.append("bad agent %r" % ev["agent"])
    if ev["kit"] is not None and not isinstance(ev["kit"], str):
        errs.append("bad kit")
    if ev["source"] not in SOURCES:
        errs.append("bad source %r" % ev["source"])
    if ev["failure_mode"] not in FAILURE_MODES:
        errs.append("bad failure_mode %r" % ev["failure_mode"])
    if ev["outcome"] not in OUTCOMES:
        errs.append("bad outcome %r" % ev["outcome"])
    if ev["outcome"] == "not_covered":
        if ev["tool_id"] is not None:
            errs.append("not_covered must have tool_id null")
    elif not isinstance(ev["tool_id"], str) or not ev["tool_id"]:
        errs.append("bad tool_id %r" % ev["tool_id"])
    if not isinstance(ev["blocking"], bool):
        errs.append("blocking not bool")
    if ev["detail"] is not None and (
        not isinstance(ev["detail"], str) or len(ev["detail"]) > 500
    ):
        errs.append("detail not a string of <= 500 chars")
    if ev["metric"] is not None and (
        isinstance(ev["metric"], bool) or not isinstance(ev["metric"], (int, float))
    ):
        errs.append("bad metric")
    if ev["metric_name"] is not None and not isinstance(ev["metric_name"], str):
        errs.append("bad metric_name")
    return errs


def _clean_env(home: Optional[Path] = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if home is not None:
        env["HOME"] = str(home)
        env["XDG_CONFIG_HOME"] = str(home / ".config")
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_GLOBAL"] = str(home / ".gitconfig")
    return env


def _run(cmd: List[str], cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def _read_events(path: Path) -> List[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


SANDBOX_CONFIG = {
    "version": 1,
    "kit": "selftest",
    "builtin": {"enabled": True, "blocking": False},
    "tools": [
        {
            "id": "fake-blocker",
            "failure_modes": ["security_vulnerability"],
            "runs_per_commit": True,
            "command": "sh -c 'test ! -e BLOCK_ME'",
            "blocking": True,
            "timeout_s": 30,
        },
        {
            "id": "fake-metric",
            "failure_modes": ["logic_error"],
            "runs_per_commit": True,
            "command": "sh -c 'echo quality 7.5'",
            "blocking": False,
            "metric": {
                "name": "quality",
                "regex": "quality[^0-9]*([0-9]+(?:\\.[0-9]+)?)",
            },
        },
        {
            "id": "fake-platform",
            "failure_modes": ["scope_creep"],
            "runs_per_commit": False,
            "note": "selftest: not a per-commit tool",
        },
    ],
}
SANDBOX_COVERED = {
    "security_vulnerability",
    "logic_error",
    "incomplete_execution",
    "test_manipulation",
    "fabrication",
}


def run_sandbox(
    report: Report, runner: Optional[Path] = None, keep: bool = False
) -> None:
    print("Sandbox test (throwaway git repo)")
    runner = runner or HERE / "saica_check.py"
    if not report.check(runner.is_file(), "runner found at %s" % runner):
        return
    if shutil.which("git") is None:
        report.check(False, "git on PATH")
        return
    tmp = Path(tempfile.mkdtemp(prefix="saica-selftest-"))
    try:
        _sandbox_steps(report, runner, tmp)
    finally:
        if keep:
            print("  (sandbox kept at %s)" % tmp)
        else:
            shutil.rmtree(str(tmp), ignore_errors=True)


def _sandbox_steps(report: Report, runner: Path, tmp: Path) -> None:
    home = tmp / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("", encoding="utf-8")
    repo = tmp / "repo"
    repo.mkdir()
    env = _clean_env(home)
    py = sys.executable

    def git(*args: str) -> subprocess.CompletedProcess:
        return _run(["git"] + list(args), repo, env)

    git("init", "-q")
    git("config", "user.name", "SAICA Selftest")
    git("config", "user.email", "selftest@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("config", "core.hooksPath", ".git/hooks")

    saica = repo / ".saica"
    saica.mkdir()
    shutil.copy2(str(runner), str(saica / "saica_check.py"))
    hooks_src = runner.parent / "hooks"
    if hooks_src.is_dir():
        shutil.copytree(str(hooks_src), str(saica / "hooks"))
    template = None
    for cand in (
        runner.parent / "dashboard.template.html",
        runner.parent / "dashboard.html",
    ):
        if cand.is_file():
            template = cand
            break
    if template is not None:
        shutil.copy2(str(template), str(saica / "dashboard.template.html"))
    else:
        (saica / "dashboard.template.html").write_text(
            MINIMAL_TEMPLATE, encoding="utf-8"
        )
    (saica / "checks.json").write_text(
        json.dumps(SANDBOX_CONFIG, indent=2), encoding="utf-8"
    )
    (repo / ".gitignore").write_text(
        ".saica/events.jsonl\n.saica/pending.jsonl\n.saica/dashboard.html\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# sandbox\n", encoding="utf-8")

    r = _run([py, ".saica/saica_check.py", "install-hooks"], repo, env)
    hook = repo / ".git" / "hooks" / "pre-commit"
    report.check(
        r.returncode == 0
        and hook.is_file()
        and os.access(str(hook), os.X_OK)
        and "saica_check.py" in hook.read_text(),
        "install-hooks installs executable hooks",
        r.stdout.strip(),
    )
    git("add", "-A")
    r = git("commit", "-q", "-m", "Initial commit")
    report.check(
        r.returncode == 0, "initial commit succeeds with hooks", r.stdout.strip()
    )

    events_path = saica / "events.jsonl"
    pending_path = saica / "pending.jsonl"

    # (a) planted stub -> caught incomplete_execution after stamp.
    (repo / "app.py").write_text(
        "def handler(request):\n    # TODO: implement this\n    pass\n",
        encoding="utf-8",
    )
    git("add", "app.py")
    r = git(
        "commit",
        "-q",
        "-m",
        "Add handler\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
    )
    report.check(
        r.returncode == 0,
        "(a) commit with a planted stub succeeds (built-ins non-blocking)",
        r.stdout.strip(),
    )
    head = git("rev-parse", "HEAD").stdout.strip()
    events = _read_events(events_path)
    stub = [
        e
        for e in events
        if e["commit"] == head and e["tool_id"] == "saica:stub-markers"
    ]
    report.check(
        len(stub) == 1
        and stub[0]["outcome"] == "caught"
        and stub[0]["failure_mode"] == "incomplete_execution",
        "(a) stub-markers event is 'caught' for incomplete_execution, stamped with HEAD sha",
        repr(stub),
    )
    report.check(not pending_path.exists(), "(a) pending.jsonl removed after stamp")
    report.check(
        bool(stub) and stub[0]["agent"] == "claude",
        "(a) agent detected from Co-Authored-By trailer",
    )
    report.check(
        bool(stub)
        and stub[0]["subject"] == "Add handler"
        and stub[0]["source"] == "pre-commit",
        "(a) subject and source recorded",
    )
    metric = [
        e for e in events if e["commit"] == head and e["tool_id"] == "fake-metric"
    ]
    report.check(
        bool(metric) and metric[0]["metric"] == 7.5,
        "(a) tool metric parsed from output",
    )

    # (b) blocking fake tool fails -> commit blocked.
    before = len(_read_events(events_path))
    (repo / "BLOCK_ME").write_text("trigger\n", encoding="utf-8")
    (repo / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    git("add", "BLOCK_ME", "feature.py")
    r = git("commit", "-q", "-m", "Should be blocked")
    report.check(
        r.returncode != 0,
        "(b) failing blocking tool blocks the commit (non-zero exit)",
        "exit %d" % r.returncode,
    )
    report.check(
        git("rev-parse", "HEAD").stdout.strip() == head,
        "(b) HEAD unchanged after blocked commit",
    )
    report.check(
        len(_read_events(events_path)) == before,
        "(b) blocked commit adds nothing to events.jsonl",
    )
    report.check(
        pending_path.exists(),
        "(b) blocked run left pending.jsonl (discarded on next run)",
    )

    # Recover: unblock and commit; stale pending must be discarded.
    git("rm", "-q", "--cached", "BLOCK_ME")
    (repo / "BLOCK_ME").unlink()
    r = git("commit", "-q", "-m", "Add feature")
    report.check(
        r.returncode == 0,
        "(b) commit succeeds once the blocker is fixed",
        r.stdout.strip(),
    )
    head2 = git("rev-parse", "HEAD").stdout.strip()
    events = _read_events(events_path)
    blocker = [
        e for e in events if e["commit"] == head2 and e["tool_id"] == "fake-blocker"
    ]
    report.check(
        len(blocker) == 1 and blocker[0]["outcome"] == "pass",
        "(b) aborted commit's pending events were discarded (one fresh 'pass')",
        repr(blocker),
    )

    # CI-style run on an existing commit.
    r = _run(
        [py, ".saica/saica_check.py", "run", "--commit", head2, "--source", "ci"],
        repo,
        env,
    )
    report.check(
        r.returncode == 0, "run --commit HEAD --source ci exits 0", r.stdout.strip()
    )

    # (c) every line validates.
    events = _read_events(events_path)
    bad = []
    for i, ev in enumerate(events, 1):
        errs = validate_event(ev)
        if errs:
            bad.append("line %d: %s" % (i, "; ".join(errs)))
        elif ev["commit"] == "staged":
            bad.append("line %d: unstamped event in events.jsonl" % i)
    report.check(
        bool(events) and not bad,
        "(c) %d events.jsonl lines validate against the contract" % len(events),
        "; ".join(bad[:3]),
    )
    raw = events_path.read_text(encoding="utf-8")
    report.check(
        "selftest@example.invalid" not in raw and "SAICA Selftest" not in raw,
        "(c) no author names or emails recorded",
    )

    # (d) not_covered for uncovered failure modes.
    expected = set(FAILURE_MODES) - SANDBOX_COVERED
    got = {
        e["failure_mode"]
        for e in events
        if e["commit"] == head2
        and e["outcome"] == "not_covered"
        and e["source"] == "pre-commit"
    }
    report.check(
        got == expected,
        "(d) not_covered events for exactly the %d uncovered failure modes"
        % len(expected),
        "got %s" % sorted(got),
    )
    nr = [e for e in events if e["commit"] == head2 and e["tool_id"] == "fake-platform"]
    report.check(
        bool(nr) and nr[0]["outcome"] == "not_runnable",
        "(d) runs_per_commit:false tool recorded as not_runnable",
    )

    # (e) dashboard.
    r = _run([py, ".saica/saica_check.py", "dashboard"], repo, env)
    out = saica / "dashboard.html"
    ok = r.returncode == 0 and out.is_file()
    embedded: list = []
    if ok:
        html = out.read_text(encoding="utf-8")
        m = re.search(
            r'<script id="saica-events" type="application/json">(.*?)</script>',
            html,
            re.S,
        )
        try:
            embedded = json.loads(m.group(1)) if m else []
        except ValueError:
            embedded = []
    report.check(ok, "(e) dashboard writes .saica/dashboard.html", r.stdout.strip())
    report.check(
        len(embedded) == len(events)
        and any(e.get("commit") == head2 for e in embedded),
        "(e) dashboard embeds all %d events" % len(events),
    )

    # replay smoke test.
    r = _run([py, ".saica/saica_check.py", "replay", "--last", "5"], repo, env)
    replayed = [e for e in _read_events(events_path) if e["source"] == "replay"]
    report.check(
        r.returncode == 0 and bool(replayed),
        "replay --last 5 writes replay events",
        r.stdout.strip(),
    )


# ---------------------------------------------------------------------------
# Repo check
# ---------------------------------------------------------------------------


def _load_runner(path: Path):
    spec = importlib.util.spec_from_file_location("saica_check_under_test", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _git_root(start: Path) -> Optional[Path]:
    r = _run(["git", "rev-parse", "--show-toplevel"], start, _clean_env())
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def _command_binary(command: str) -> Optional[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    for tok in tokens:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            continue  # FOO=bar env assignment
        return tok
    return None


def run_repo(report: Report, root: Path) -> None:
    print("Repo check (%s)" % root)
    saica = root / ".saica"
    env = _clean_env()
    runner_path = saica / "saica_check.py"
    if not report.check(runner_path.is_file(), ".saica/saica_check.py present"):
        return
    try:
        runner = _load_runner(runner_path)
    except Exception as exc:  # noqa: BLE001
        report.check(False, "runner imports", repr(exc))
        return
    config = None
    try:
        config = runner.load_config(saica / "checks.json")
        report.check(
            True,
            ".saica/checks.json valid (kit=%s, %d tools)"
            % (config["kit"], len(config["tools"])),
        )
    except Exception as exc:  # noqa: BLE001
        report.check(False, ".saica/checks.json valid", str(exc))

    r = _run(["git", "rev-parse", "--git-path", "hooks"], root, env)
    hooks_dir = Path(r.stdout.strip())
    if not hooks_dir.is_absolute():
        hooks_dir = root / hooks_dir
    framework_cfg = root / ".pre-commit-config.yaml"
    framework_text = (
        framework_cfg.read_text(encoding="utf-8", errors="replace")
        if framework_cfg.is_file()
        else ""
    )
    for name, needle in (("pre-commit", "run --staged"), ("post-commit", "stamp")):
        hook = hooks_dir / name
        text = (
            hook.read_text(encoding="utf-8", errors="replace") if hook.is_file() else ""
        )
        direct = "saica_check.py" in text and os.access(str(hook), os.X_OK)
        via_framework = "saica_check.py" in framework_text and needle in framework_text
        report.check(
            direct or via_framework,
            "%s hook installed and calls saica_check.py" % name,
            "run: python3 .saica/saica_check.py install-hooks",
        )

    if config is not None:
        for tool in config["tools"]:
            if not tool["runs_per_commit"]:
                continue
            binary = _command_binary(tool["command"] or "")
            if binary and shutil.which(binary) is None and not (root / binary).exists():
                report.warn(
                    "tool %s: '%s' not found on PATH (its checks will record 'error')"
                    % (tool["id"], binary)
                )
            else:
                report.check(True, "tool %s: '%s' available" % (tool["id"], binary))

    report.check(
        (saica / "dashboard.template.html").is_file(),
        ".saica/dashboard.template.html present",
    )
    r = _run(["git", "check-ignore", "-q", ".saica/events.jsonl"], root, env)
    if r.returncode != 0:
        report.warn(".saica/events.jsonl is not gitignored")
    if not (root / ".github" / "workflows" / "saica-ci.yml").is_file():
        report.warn(
            ".github/workflows/saica-ci.yml not found (no CI backstop for --no-verify)"
        )


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="SAICA supervision kit self-test.")
    ap.add_argument(
        "--sandbox", action="store_true", help="run only the throwaway-repo test"
    )
    ap.add_argument(
        "--repo",
        nargs="?",
        const=".",
        metavar="DIR",
        help="run only the install check (default: current repo)",
    )
    ap.add_argument(
        "--keep", action="store_true", help="keep the sandbox directory for inspection"
    )
    args = ap.parse_args(argv)
    report = Report()
    do_sandbox = args.sandbox or args.repo is None
    do_repo = args.repo is not None or not args.sandbox

    if do_sandbox:
        run_sandbox(report, keep=args.keep)
    if do_repo:
        explicit = args.repo is not None
        root = _git_root(Path(args.repo or "."))
        if root is None:
            if explicit:
                report.check(False, "inside a git repository", args.repo)
            else:
                print("Repo check: skipped (not inside a git repository)")
        elif not explicit and not (
            (root / ".saica" / "saica_check.py").is_file()
            or (root / ".saica" / "checks.json").is_file()
        ):
            print("Repo check: skipped (%s has no .saica/ install)" % root)
        else:
            run_repo(report, root)

    print("")
    if report.failed:
        print(
            "FAIL: %d check(s) failed, %d warning(s)" % (report.failed, report.warned)
        )
        return 1
    print("PASS: all checks passed (%d warning(s))" % report.warned)
    return 0


if __name__ == "__main__":
    sys.exit(main())
