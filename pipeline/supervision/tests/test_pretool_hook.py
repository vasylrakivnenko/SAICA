"""Tests for the PreToolUse guard with sample hook inputs (review H6).

The inputs have the shape the Claude Code hooks reference gives for
``PreToolUse``. The hook is never enabled by these tests: they call the
logic directly, or run the script as a subprocess with a temp log folder.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline.supervision import pretool
from pipeline.supervision.logger import log_prevention, observed_events, read_events
from pipeline.supervision.pretool import OFF_LIMITS, decide, run

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK = REPO_ROOT / ".claude" / "hooks" / "pretool_guard.py"
EXAMPLE = REPO_ROOT / ".claude" / "hooks" / "settings.example.json"


def _input(tool: str, tool_input: dict, cwd: Path = REPO_ROOT) -> dict:
    return {
        "session_id": "abc123",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": str(cwd),
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": "toolu_01ABC",
    }


def _bash(command: str) -> dict:
    return _input("Bash", {"command": command, "description": "x"})


# ---------------------------------------------------------------------------
# Bash: commands that skip commit hooks are denied
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git commit --no-verify -m 'wip'",
        "git commit -m 'wip' --no-verify",
        "git push --no-verify origin main",
        "cd repo && git commit -am x --no-verify",
        "git   commit   -n -m 'skip hooks'",
        "git commit -nm 'skip hooks'",
        "git commit -an -m x",
        "git -C sub commit -n",
        "git -c user.name=x commit -n -m y",
        "pytest -q; git commit -n",
        "bash -c 'git commit --no-verify'",
    ],
)
def test_bash_commands_that_skip_hooks_are_denied(command: str) -> None:
    verdict = decide(_bash(command))
    assert verdict is not None and verdict.decision == "deny", command
    assert verdict.failure_mode == "incomplete_execution"
    assert "CLAUDE.md" in verdict.reason


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'explain the -n flag'",
        "git commit -m 'no verify needed here'",
        "git commit -m x",
        "git commit -F notes-n.txt",
        "git commit -m -n",  # "-n" is the message
        "git push -n origin main",  # -n is --dry-run for push
        "git log -n 5",
        "git commit --no-verify-signatures",  # another option
        "grep -rn no-verify docs/",
        "ls -n",
        "echo git commit; ls -n",
        "git commit -m 'unbalanced quote",
        "",
    ],
)
def test_ordinary_bash_commands_get_no_opinion(command: str) -> None:
    assert decide(_bash(command)) is None, command


# ---------------------------------------------------------------------------
# Edits: off-limits paths are asked about
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool, tool_input, prefix",
    [
        (
            "Edit",
            {
                "file_path": str(REPO_ROOT / "data/tools/semgrep.yml"),
                "old_string": "a",
                "new_string": "b",
            },
            "data/",
        ),
        (
            "Write",
            {"file_path": str(REPO_ROOT / "validator/new_check.py"), "content": "x"},
            "validator/",
        ),
        (
            "Write",
            {"file_path": "pipeline/ask/server.py", "content": "x"},
            "pipeline/ask/",
        ),  # relative to cwd
        (
            "MultiEdit",
            {"file_path": str(REPO_ROOT / "pipeline/mcp/server.py"), "edits": []},
            "pipeline/mcp/",
        ),
        (
            "NotebookEdit",
            {"notebook_path": str(REPO_ROOT / "data/notes.ipynb")},
            "data/",
        ),
        (
            "Edit",
            {"file_path": str(REPO_ROOT / "site/../pipeline/audit/kg.py")},
            "pipeline/audit/",
        ),  # .. resolved
    ],
)
def test_edits_under_off_limits_paths_are_asked_about(tool, tool_input, prefix) -> None:
    verdict = decide(_input(tool, tool_input), REPO_ROOT)
    assert verdict is not None and verdict.decision == "ask"
    assert verdict.failure_mode == "scope_creep"
    assert prefix in verdict.reason
    assert verdict.output() == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": verdict.reason,
        }
    }


@pytest.mark.parametrize(
    "tool, tool_input",
    [
        ("Edit", {"file_path": str(REPO_ROOT / "site/src/pages/index.astro")}),
        ("Write", {"file_path": str(REPO_ROOT / "README.md"), "content": "x"}),
        ("Write", {"file_path": str(REPO_ROOT / "pipeline/webapp.py"), "content": "x"}),
        (
            "Write",
            {"file_path": str(REPO_ROOT / "database/x.sql"), "content": "x"},
        ),  # not "data/"
        (
            "Write",
            {"file_path": str(REPO_ROOT / "research/data/x.csv"), "content": "x"},
        ),
        ("Edit", {"file_path": "/etc/hosts"}),  # outside the project
        ("Edit", {"file_path": str(REPO_ROOT.parent / "other" / "data" / "x.yml")}),
        (
            "Read",
            {"file_path": str(REPO_ROOT / "data/tools/semgrep.yml")},
        ),  # reading is fine
        ("Edit", {}),
        ("Edit", {"file_path": 7}),
    ],
)
def test_other_edits_and_reads_get_no_opinion(tool, tool_input) -> None:
    assert decide(_input(tool, tool_input), REPO_ROOT) is None


def test_a_symlink_into_an_off_limits_folder_is_still_asked_about(
    tmp_path: Path,
) -> None:
    project = tmp_path / "proj"
    (project / "data" / "tools").mkdir(parents=True)
    (project / "shortcut").symlink_to(project / "data")
    verdict = decide(
        _input("Write", {"file_path": str(project / "shortcut/tools/x.yml")}, project),
        project,
    )
    assert verdict is not None and verdict.detail == "Write data/tools/x.yml"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "text",
        {},
        {"tool_name": "Bash"},
        {"tool_name": 1, "tool_input": {}},
        {"tool_name": "Bash", "tool_input": {"command": ["git"]}},
    ],
)
def test_malformed_inputs_never_raise(payload) -> None:
    assert decide(payload) is None


def test_the_old_trigger_is_gone() -> None:
    """The first hook fired when its input *contained* ``"decision": "deny"``
    — which a PreToolUse input never does, except by accident in a file
    being written. That is no longer a trigger."""
    payload = _input(
        "Write",
        {"file_path": str(REPO_ROOT / "notes.md"), "content": '{"decision": "deny"}'},
    )
    assert run(json.dumps(payload), project_dir=REPO_ROOT) == ""


# ---------------------------------------------------------------------------
# The hook logs its own decisions, labelled as its own
# ---------------------------------------------------------------------------


def test_run_prints_the_decision_and_logs_it_as_recorded_by_the_hook(
    tmp_path: Path,
) -> None:
    out = run(
        json.dumps(_bash("git commit --no-verify -m x")),
        project_dir=REPO_ROOT,
        log_dir=tmp_path,
    )
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert run(json.dumps(_bash("ls")), project_dir=REPO_ROOT, log_dir=tmp_path) == ""
    assert run("not json", log_dir=tmp_path) == ""
    [event] = read_events(tmp_path)
    assert event["recorded_by"] == "hook" and event["decision"] == "deny"
    assert event["invoked_by"] == "claude-code-hook"
    assert event["tool_id"] == "claude-md"
    assert event["failure_mode"] == "incomplete_execution"
    assert event["mechanism"] == "denied-no-verify-via-pretooluse-hook"
    assert event["detail"] == "command: git commit --no-verify -m x"


def test_typed_in_events_are_never_counted_as_observed(tmp_path: Path) -> None:
    run(
        json.dumps(_input("Edit", {"file_path": str(REPO_ROOT / "data/x.yml")})),
        project_dir=REPO_ROOT,
        log_dir=tmp_path,
    )
    # An agent types in an event and claims to be the hook, as CLAUDE.md
    # used to instruct. The CLI stores it as a self-report.
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipeline.supervision",
            "log",
            "--tool-id",
            "ruff",
            "--failure-mode",
            "logic_error",
            "--mechanism",
            "blocked-commit-via-pre-commit",
            "--invoked-by",
            "claude-code-hook",
            "--log-dir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0 and "not a hook" in done.stderr
    # A line from before the field existed, as found in the real local log.
    with (tmp_path / "2026-05-01.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": "2026-05-01T10:00:00Z",
                    "tool_id": "black",
                    "failure_mode": "incomplete_execution",
                    "mechanism": "blocked-commit-via-pre-commit",
                    "detail": "",
                    "invoked_by": "claude-code-hook",
                }
            )
            + "\n"
        )

    events = read_events(tmp_path)
    assert sorted(e["recorded_by"] for e in events) == ["cli", "cli", "hook"]
    typed = next(e for e in events if e["tool_id"] == "ruff")
    assert typed["invoked_by"] == "agent-manual"
    [observed] = observed_events(tmp_path)
    assert observed["decision"] == "ask" and observed["detail"] == "Edit data/x.yml"

    shown = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipeline.supervision",
            "show",
            "--log-dir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    ).stdout
    assert "recorded by the hook itself (observed): 1" in shown
    assert "typed in through this command (self-reported): 2" in shown


def test_only_the_hook_may_claim_to_be_the_hook(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="recorded_by"):
        log_prevention(
            tool_id="x",
            failure_mode="scope_creep",
            mechanism="m",
            log_dir=tmp_path,
            recorded_by="observer",
        )
    done = subprocess.run(
        [sys.executable, "-m", "pipeline.supervision", "log", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert "--recorded-by" not in done.stdout  # the command line cannot set it


# ---------------------------------------------------------------------------
# The script, as Claude Code would run it
# ---------------------------------------------------------------------------


def _run_hook(
    payload: str, log_dir: Path, project: Path = REPO_ROOT
) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        CLAUDE_PROJECT_DIR=str(project),
        SAICA_PREVENTION_LOG_DIR=str(log_dir),
    )
    return subprocess.run(
        [str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        cwd=project,
    )


def test_hook_script_denies_asks_and_stays_silent(tmp_path: Path) -> None:
    assert os.access(HOOK, os.X_OK)
    deny = _run_hook(json.dumps(_bash("git commit --no-verify")), tmp_path)
    assert deny.returncode == 0
    assert json.loads(deny.stdout)["hookSpecificOutput"] == {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": json.loads(deny.stdout)["hookSpecificOutput"][
            "permissionDecisionReason"
        ],
    }
    ask = _run_hook(
        json.dumps(_input("Write", {"file_path": "validator/x.py", "content": ""})),
        tmp_path,
    )
    assert json.loads(ask.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"
    for quiet in (json.dumps(_bash("git status")), "", "{broken", json.dumps([1, 2])):
        done = _run_hook(quiet, tmp_path)
        assert (done.returncode, done.stdout) == (0, ""), quiet
    # Two decisions were taken, two lines were written; the silent runs wrote none.
    assert sorted(e["decision"] for e in observed_events(tmp_path)) == ["ask", "deny"]


def test_example_settings_use_the_documented_hook_schema() -> None:
    settings = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    [entry] = settings["hooks"]["PreToolUse"]
    assert set(entry) == {"matcher", "hooks"}
    # Only letters and "|": Claude Code reads it as a list of exact tool names.
    assert re.fullmatch(r"[A-Za-z|]+", entry["matcher"])
    assert set(entry["matcher"].split("|")) == {"Bash"} | pretool.EDIT_TOOLS
    [hook] = entry["hooks"]
    assert hook["type"] == "command"
    assert hook["command"] == '"$CLAUDE_PROJECT_DIR"/.claude/hooks/pretool_guard.py'
    assert (REPO_ROOT / ".claude/hooks/pretool_guard.py").is_file()
    assert not (REPO_ROOT / ".claude/hooks/log_pretool.sh").exists()


def test_off_limits_paths_are_the_ones_claude_md_lists() -> None:
    """If CLAUDE.md changes its list, change ``pretool.OFF_LIMITS`` with it."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    start = text.index("off-limits")
    section = text[start : text.index("\n## ", start)]
    listed = set(re.findall(r"`([A-Za-z0-9_./-]+/)`", section))
    assert listed == set(OFF_LIMITS)
