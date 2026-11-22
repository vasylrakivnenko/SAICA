"""Logic of the Claude Code ``PreToolUse`` guard.

``.claude/hooks/pretool_guard.py`` feeds the hook's JSON input to
:func:`run`. The guard decides by itself; it does not wait for anybody
else's decision (a PreToolUse input carries none):

* **deny** a ``Bash`` command that skips commit or push hooks:
  ``--no-verify`` anywhere in the command, or ``git commit -n``.
  ``CLAUDE.md``: "Do not bypass hooks with ``--no-verify``."
* **ask** the user before ``Edit`` / ``Write`` / ``MultiEdit`` /
  ``NotebookEdit`` touches a file under a path that ``CLAUDE.md`` lists as
  off-limits unless the task names it (:data:`OFF_LIMITS`).
* otherwise say nothing, and Claude Code's normal permission flow goes on.

Each deny or ask is appended to the prevention log with
``recorded_by: "hook"``: the hook reports its own decision. For an "ask"
the log records that the question was put, not what the user answered.

What it does not catch: other ways around commit hooks (``SKIP=…``,
``-c core.hooksPath=…``, ``HUSKY=0``), edits made by a shell command
(``sed -i``, ``>``), and anything while the hook is not enabled. It is
opt-in: see ``.claude/hooks/settings.example.json``.

Input and output follow the Claude Code hooks reference (read
2026-11-21): the input has ``tool_name`` and ``tool_input``
(``command`` for Bash, ``file_path`` for Edit and Write); the decision is
printed as ``hookSpecificOutput.permissionDecision`` with exit code 0. The
reference documents no input table for MultiEdit and NotebookEdit; the
guard reads ``file_path`` or ``notebook_path`` if present.

Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.supervision.logger import REPO_ROOT, log_prevention

# The directories CLAUDE.md lists under "Files explicitly off-limits unless
# the task names them". A test compares this tuple with that file.
OFF_LIMITS: tuple[str, ...] = (
    "pipeline/audit/",
    "pipeline/mcp/",
    "pipeline/ask/",
    "validator/",
    "data/",
)

EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

_NO_VERIFY_RE = re.compile(r"(?<![\w-])--no-verify(?![\w-])")
# Options of ``git commit`` that take a value in the next word.
_COMMIT_VALUE_FLAGS = frozenset("mFCct")


@dataclass(frozen=True)
class Decision:
    """What the guard decided for one tool call."""

    decision: str  # "deny" | "ask"
    reason: str  # shown to the user and to the model
    failure_mode: str
    mechanism: str
    detail: str

    def output(self) -> dict[str, Any]:
        """The JSON Claude Code expects on stdout."""
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": self.decision,
                "permissionDecisionReason": self.reason,
            }
        }


def _short_commit_no_verify(command: str) -> bool:
    """True for ``git commit -n`` (also ``-an``, ``-nm msg``)."""
    try:
        words = shlex.split(command, comments=True)
    except ValueError:
        return False
    for i, word in enumerate(words):
        if word != "git":
            continue
        rest = words[i + 1 :]
        # Skip git's own options (``git -C dir -c key=value commit``).
        j = 0
        while j < len(rest) and rest[j].startswith("-"):
            j += 2 if rest[j] in ("-C", "-c") else 1
        if j >= len(rest) or rest[j] != "commit":
            continue
        skip = False
        for arg in rest[j + 1 :]:
            if skip:
                skip = False
                continue
            if arg in ("&&", "||", ";", "|", "--"):
                break
            if arg.startswith("-") and not arg.startswith("--"):
                flags = arg[1:]
                for position, flag in enumerate(flags):
                    if flag == "n":
                        return True
                    if flag in _COMMIT_VALUE_FLAGS:
                        # The rest of the word, or the next word, is its value.
                        skip = position == len(flags) - 1
                        break
    return False


def _relative_to_project(path: str, cwd: str | None, project_dir: Path) -> str | None:
    """``path`` as a POSIX path relative to the project, or ``None`` when it
    lies outside. ``..`` and symlinked folders are resolved first."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(cwd or project_dir) / candidate
    try:
        resolved = Path(os.path.realpath(candidate))
        return resolved.relative_to(Path(os.path.realpath(project_dir))).as_posix()
    except (OSError, ValueError):
        return None


def decide(payload: Any, project_dir: Path | None = None) -> Decision | None:
    """The guard's decision for one PreToolUse input, or ``None`` for
    "no opinion". Never raises on a malformed input."""
    if not isinstance(payload, dict):
        return None
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        return None

    if tool == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return None
        if _NO_VERIFY_RE.search(command) or _short_commit_no_verify(command):
            return Decision(
                decision="deny",
                reason=(
                    "CLAUDE.md: do not bypass commit hooks (--no-verify / "
                    "git commit -n). Fix what the hook reports, then commit."
                ),
                failure_mode="incomplete_execution",
                mechanism="denied-no-verify-via-pretooluse-hook",
                detail="command: " + " ".join(command.split())[:300],
            )
        return None

    if tool in EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not isinstance(path, str) or not path:
            return None
        cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
        rel = _relative_to_project(path, cwd, project_dir or REPO_ROOT)
        if rel is None:
            return None
        for prefix in OFF_LIMITS:
            if (rel + "/").startswith(prefix):
                return Decision(
                    decision="ask",
                    reason=(
                        f"CLAUDE.md lists {prefix} as off-limits unless the task "
                        f"names it. Allow this {tool} of {rel}?"
                    ),
                    failure_mode="scope_creep",
                    mechanism="asked-before-off-limits-edit-via-pretooluse-hook",
                    detail=f"{tool} {rel}",
                )
    return None


def run(
    stdin_text: str, *, project_dir: Path | None = None, log_dir: Path | None = None
) -> str:
    """Handle one hook call: return what to print on stdout ("" for no
    opinion) and append the decision to the prevention log."""
    try:
        payload = json.loads(stdin_text)
    except ValueError:
        return ""
    verdict = decide(payload, project_dir)
    if verdict is None:
        return ""
    try:
        log_prevention(
            tool_id="claude-md",
            failure_mode=verdict.failure_mode,
            mechanism=verdict.mechanism,
            detail=verdict.detail,
            invoked_by="claude-code-hook",
            log_dir=log_dir,
            recorded_by="hook",
            decision=verdict.decision,
        )
    except (OSError, ValueError):
        pass  # a log that cannot be written must not change the decision
    return json.dumps(verdict.output())


def main() -> int:
    """Entry point of the hook script. Always exits 0: the decision is in
    the JSON, and an internal error must fall back to the normal flow."""
    try:
        project = os.environ.get("CLAUDE_PROJECT_DIR")
        override = os.environ.get("SAICA_PREVENTION_LOG_DIR")
        out = run(
            sys.stdin.read(1_048_576),
            project_dir=Path(project) if project else None,
            log_dir=Path(override) if override else None,
        )
    except Exception:  # noqa: BLE001 - never block every tool call on a bug here
        return 0
    if out:
        sys.stdout.write(out + "\n")
    return 0


__all__ = ["Decision", "EDIT_TOOLS", "OFF_LIMITS", "decide", "main", "run"]
