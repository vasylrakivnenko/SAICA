"""Cases from the independent review of the PreToolUse guard (2026-11-21).

The first version looked for ``--no-verify`` anywhere in the command line
and for ``-n`` anywhere after ``git commit``. It denied harmless commands
and missed a few one-line bypasses. The guard now splits the line into
simple commands and reads only the words of a ``git commit`` / ``git push``
/ ``git merge`` command.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from pipeline.supervision.logger import log_prevention, read_events
from pipeline.supervision.pretool import decide, simple_commands

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK = REPO_ROOT / ".claude" / "hooks" / "pretool_guard.py"


def _decision(command: str) -> str:
    verdict = decide(
        {"tool_name": "Bash", "tool_input": {"command": command}}, REPO_ROOT
    )
    return verdict.decision if verdict else "-"


FALSE_DENIALS = [
    "grep -rn -- --no-verify .",
    "rg 'no-verify' docs/",
    "echo '--no-verify is banned'",
    "git commit -m 'docs: never use --no-verify'",
    "git commit -m x; git log -n 1",
    "git commit -m x\ngit log -n 3",
    "git commit -m x && git log -n 1",
    "git commit -m x 2>&1 |head -n 5",
    "git commit -uno -m x",  # -u takes "no"; git still runs the hooks
    "git commit -m x -- -n",  # a path named "-n"
    "git commit -F - <<EOF\nfix the -n flag\nEOF",
    "git commit -m \"$(cat <<'EOF'\nuse -n here\nEOF\n)\"",
    "git commit -Sn0tAKey -m x",  # -S takes the key id
    "git commit -m x # -n",
    "git commit -m fix-n",
    "git commit-graph write; ls -n",
    "git status; npm run commit -n",
    "git commit --author 'n <n@n>' -m x",
    "git commit -m 'a' -m '-n'",
    "git commit --message -n",
    "git commit -vm x",
    "git commit --amend --no-edit",
    "git commit --no-verbose -m x",
    "git log -n 5",
    "git push -n origin main",  # dry run
    "git merge -n topic",  # --no-stat
    "pre-commit run --files x --no-verify-thing",
    "git commit -m x",
    "git -c core.hooksPath=.githooks log -n 1",  # not a commit
    "git -c user.name=core.hooksPath=x commit -m x",
]

BYPASSES = [
    "git commit --no-verify -m x",
    "git commit -n -m x",
    "git commit -anm x",
    "git commit -m x -n",
    "git commit -m x --no-verify",
    "git -C . commit -n",
    "cd r && git commit -n -m x",
    "git commit --no-verif -m x",  # git accepts unambiguous abbreviations
    "git commit --no-veri -m x",
    'git commit --no-"verify" -m x',
    "git commit --no-ver''ify -m x",
    "/usr/bin/git commit -n -m x",
    "(git commit -n -m x)",
    "x;git commit -n -m x",
    "true&&git commit -n",
    "bash -c 'git commit -n -m x'",
    'sh -c "git push --no-verify"',
    'eval "git commit -n"',
    "git --git-dir .git commit -n -m x",
    "git --work-tree . commit -n",
    "git -c user.name=x commit -n -m y",
    "git commit -n -m $'it\\'s'",
    'git commit -"n" -m x',
    "git commit \\\n -n -m x",
    "git\tcommit -n",
    "git push --no-verify",
    "git push --no-verif origin main",
    "git merge --no-verify topic",
    "FOO=1 git commit -n",
    "git commit -n 2>&1 | tee log",
    "{ git commit -n; }",
    "git -c core.hooksPath=/dev/null commit -m x",
]


@pytest.mark.parametrize("command", FALSE_DENIALS)
def test_commands_that_do_not_skip_hooks_are_left_alone(command: str) -> None:
    assert _decision(command) == "-", command


@pytest.mark.parametrize("command", BYPASSES)
def test_commands_that_skip_hooks_are_denied(command: str) -> None:
    assert _decision(command) == "deny", command


def test_simple_commands_splits_on_operators_newlines_and_groups() -> None:
    assert simple_commands("a -x; b 'c d' && (e|f)\ng \\\n h # i\nj") == [
        ["a", "-x"],
        ["b", "c d"],
        ["e"],
        ["f"],
        ["g", "h"],
        ["j"],
    ]
    assert simple_commands("echo 'unterminated") == [["echo", "unterminated"]]
    assert simple_commands("") == []


def test_long_inputs_are_handled_in_linear_time() -> None:
    import time

    started = time.perf_counter()
    assert _decision("git commit -n " + "'" * 900_001) == "deny"
    assert _decision("git " * 20_000 + "commit " * 20_000) == "-"
    assert _decision("git commit -m x; " * 50_000 + "git commit -n") == "deny"
    assert time.perf_counter() - started < 5.0


# Paths: compared after resolving, and without regard to letter case
# (macOS file systems fold case: DATA/ is data/).


@pytest.mark.parametrize(
    "path, cwd",
    [
        (str(REPO_ROOT / "DATA/tools/semgrep.yml"), None),
        (str(REPO_ROOT / "Data/tools/semgrep.yml"), None),
        (str(REPO_ROOT).upper() + "/data/x.yml", None),
        (str(REPO_ROOT / "pipeline/../data/x.yml"), None),
        (f"../{REPO_ROOT.name}/validator/cli.py", str(REPO_ROOT)),
        (str(REPO_ROOT / "data"), None),  # the folder itself
        ("~/" + str(REPO_ROOT.relative_to(Path.home())) + "/data/x.yml", None),
    ],
)
def test_off_limits_paths_in_other_spellings_are_asked_about(path, cwd) -> None:
    payload = {"tool_name": "Edit", "tool_input": {"file_path": path}, "cwd": cwd}
    verdict = decide(payload, REPO_ROOT)
    assert verdict is not None and verdict.decision == "ask", path


def test_paths_that_only_look_alike_are_left_alone() -> None:
    for path in (
        str(REPO_ROOT / "database/x"),
        str(REPO_ROOT / "research/data/x.csv"),
        "/tmp/data/x.yml",
    ):
        assert (
            decide({"tool_name": "Edit", "tool_input": {"file_path": path}}, REPO_ROOT)
            is None
        )


def _run_hook(payload: bytes, log_dir: Path) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        CLAUDE_PROJECT_DIR=str(REPO_ROOT),
        SAICA_PREVENTION_LOG_DIR=str(log_dir),
    )
    return subprocess.run(
        [str(HOOK)], input=payload, capture_output=True, env=env, timeout=60
    )


def test_large_write_under_an_off_limits_path_still_asks(tmp_path: Path) -> None:
    """The script read 1 MB of stdin; a bigger Write was cut and got no opinion."""
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(REPO_ROOT / "data/big.yml"),
            "content": "x" * 1_100_000,
        },
    }
    done = _run_hook(json.dumps(payload).encode(), tmp_path)
    assert done.returncode == 0
    assert json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"
    # Still silent, still exit 0, on input that is not a hook payload.
    for junk in (
        b"[" * 200_000,
        b"\xff\xfe",
        b'{"tool_name":"Bash","tool_input":{"command":null}}',
    ):
        done = _run_hook(junk, tmp_path)
        assert (done.returncode, done.stdout) == (0, b"")


def test_several_decisions_in_one_second_are_all_logged(
    tmp_path: Path, monkeypatch
) -> None:
    """Four denials in one second used to leave one line."""
    from pipeline.supervision import logger as logger_mod

    monkeypatch.setattr(logger_mod, "_utcnow_iso", lambda: "2026-11-21T12:00:00Z")
    for i in range(4):
        log_prevention(
            tool_id="claude-md",
            failure_mode="incomplete_execution",
            mechanism="denied-no-verify-via-pretooluse-hook",
            detail=f"command: git commit -n -m attempt{i}",
            log_dir=tmp_path,
            recorded_by="hook",
        )
    # The very same event twice in one second is still written once.
    log_prevention(
        tool_id="claude-md",
        failure_mode="incomplete_execution",
        mechanism="denied-no-verify-via-pretooluse-hook",
        detail="command: git commit -n -m attempt3",
        log_dir=tmp_path,
        recorded_by="hook",
    )
    assert sorted(e["detail"][-8:] for e in read_events(tmp_path)) == [
        f"attempt{i}" for i in range(4)
    ]
