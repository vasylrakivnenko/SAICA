"""Logic of the Claude Code ``PreToolUse`` guard.

``.claude/hooks/pretool_guard.py`` feeds the hook's JSON input to
:func:`run`. The guard decides by itself; it does not wait for anybody
else's decision (a PreToolUse input carries none):

* **deny** a ``Bash`` command in which a ``git commit``, ``git push`` or
  ``git merge`` skips the hooks: ``--no-verify`` (or the abbreviations git
  accepts, down to ``--no-veri``), ``-c core.hooksPath=…`` and, for
  ``commit``, the short flag ``-n``. ``CLAUDE.md``: "Do not bypass hooks with ``--no-verify``."
* **ask** the user before ``Edit`` / ``Write`` / ``MultiEdit`` /
  ``NotebookEdit`` touches a file under a path that ``CLAUDE.md`` lists as
  off-limits unless the task names it (:data:`OFF_LIMITS`).
* otherwise say nothing, and Claude Code's normal permission flow goes on.

How a command line is read. It is split into simple commands at ``;``,
``&&``, ``||``, ``|``, ``&``, parentheses and newlines, with quotes,
backslashes, comments and redirections handled the way a shell would
(:func:`simple_commands`). Only the words of a git command are looked at,
and an option's value is never mistaken for an option: a commit message
that mentions ``--no-verify``, ``grep -- --no-verify``, ``git log -n 3``
on the next line and ``git commit -uno`` are all left alone. ``bash -c
"..."``, ``sh -c`` and ``eval`` are read one level deep.

What it does not catch, by design or because a hook cannot know: text
built at run time (``$(echo git) commit -n``, ``g=git; $g commit -n``,
``--no-$X``), aliases (``git -c alias.x='commit -n' x``), other ways
around hooks (``SKIP=…``, ``git config core.hooksPath …``, ``HUSKY=0``,
``chmod -x .git/hooks/*``), edits made by a shell command (``sed -i``,
``>``), and anything while the hook is not enabled. It is opt-in: see
``.claude/hooks/settings.example.json``.

Each deny or ask is appended to the prevention log with
``recorded_by: "hook"``: the hook reports its own decision. For an "ask"
the log records that the question was put, not what the user answered.

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

# Most the hook reads from stdin (a Write of this size is not expected).
MAX_INPUT_BYTES = 64_000_000

_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Words that may stand before the program name of a simple command.
_PREFIX_WORDS = frozenset(
    {
        "{",
        "}",
        "!",
        "then",
        "else",
        "do",
        "if",
        "while",
        "until",
        "time",
        "command",
        "exec",
        "sudo",
        "env",
        "nohup",
    }
)
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
# git's own options that take their value in the next word.
_GIT_VALUE_OPTIONS = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
)
# Per subcommand: long options whose value is the next word, short options
# whose value is the next word, short options whose value is the rest of
# the same word (``-uno``, ``-S<key>``).
_VALUE_LONG = {
    "commit": frozenset(
        {
            "--message",
            "--file",
            "--author",
            "--date",
            "--template",
            "--reuse-message",
            "--reedit-message",
            "--fixup",
            "--squash",
            "--cleanup",
            "--pathspec-from-file",
            "--trailer",
        }
    ),
    "push": frozenset({"--repo", "--receive-pack", "--exec", "--push-option"}),
    "merge": frozenset(
        {
            "--message",
            "--file",
            "--strategy",
            "--strategy-option",
            "--into-name",
            "--cleanup",
        }
    ),
}
_VALUE_SHORT = {"commit": "mFCct", "push": "o", "merge": "mFsX"}
_ATTACHED_SHORT = {"commit": "Su", "push": "", "merge": "S"}
_NO_VERIFY = "--no-verify"
_SHORTEST_ABBREVIATION = len("--no-veri")  # "--no-ver" could also be --no-verbose


def simple_commands(command: str) -> list[list[str]]:
    """Split a shell command line into simple commands, each a list of words.

    Handles single and double quotes, ``$'...'``, backslashes (including a
    backslash at a line end), ``#`` comments, redirections (the operator
    and its target are dropped) and the separators ``; & | ( )`` and
    newline. It does not expand anything: ``$(...)``, backticks and
    variables stay as text. Unbalanced quotes run to the end of the input.
    Linear in the length of the input.
    """
    commands: list[list[str]] = []
    words: list[str] = []
    cur: list[str] = []
    in_word = False
    drop_next = False  # the next word is the target of a redirection
    i, n = 0, len(command)

    def end_word() -> None:
        nonlocal in_word, drop_next
        if in_word:
            if drop_next:
                drop_next = False
            else:
                words.append("".join(cur))
            cur.clear()
            in_word = False

    def end_command() -> None:
        nonlocal words, drop_next
        end_word()
        drop_next = False
        if words:
            commands.append(words)
            words = []

    while i < n:
        c = command[i]
        if c == "\\":
            if i + 1 < n and command[i + 1] == "\n":
                i += 2
                continue
            if i + 1 < n:
                cur.append(command[i + 1])
            in_word = True
            i += 2
        elif c == "'" or (c == "$" and command[i + 1 : i + 2] == "'"):
            ansi = c == "$"
            start = i + (2 if ansi else 1)
            if not ansi:
                close = command.find("'", start)
                close = n if close < 0 else close
                cur.append(command[start:close])
            else:
                close = start
                while close < n and command[close] != "'":
                    if command[close] == "\\" and close + 1 < n:
                        close += 1
                    cur.append(command[close])
                    close += 1
            in_word = True
            i = close + 1
        elif c == '"':
            j = i + 1
            while j < n and command[j] != '"':
                if command[j] == "\\" and j + 1 < n and command[j + 1] in '"\\$`\n':
                    j += 1
                    if command[j] == "\n":
                        j += 1
                        continue
                cur.append(command[j])
                j += 1
            in_word = True
            i = j + 1
        elif c == "#" and not in_word:
            close = command.find("\n", i)
            i = n if close < 0 else close
        elif c in " \t\r":
            end_word()
            i += 1
        elif c in "<>" or (c == "&" and command[i + 1 : i + 2] == ">"):
            if in_word and "".join(cur).isdigit():
                cur.clear()  # the file-descriptor number of "2>..."
                in_word = False
            end_word()
            i += 1
            while i < n and command[i] in "<>&|-":
                i += 1
            if command[i - 1] == "&" and i < n and command[i].isdigit():
                # ">&1": the target is glued to the operator.
                while i < n and command[i].isdigit():
                    i += 1
            else:
                drop_next = True
        elif c in ";&|()\n":
            end_command()
            i += 1
        else:
            cur.append(c)
            in_word = True
            i += 1
    end_command()
    return commands


def _args_skip_hooks(sub: str, args: list[str]) -> bool:
    """Do the arguments of ``git <sub>`` ask git to skip the hooks?"""
    k = 0
    while k < len(args):
        arg = args[k]
        if arg == "--":
            return False  # only paths follow
        if arg.startswith("--"):
            name = arg.split("=", 1)[0]
            if len(name) >= _SHORTEST_ABBREVIATION and _NO_VERIFY.startswith(name):
                return True
            if "=" not in arg and name in _VALUE_LONG[sub]:
                k += 1  # its value is the next word
        elif arg.startswith("-") and len(arg) > 1:
            flags = arg[1:]
            for position, flag in enumerate(flags):
                if flag == "n" and sub == "commit":
                    return True
                if flag in _ATTACHED_SHORT[sub]:
                    break  # the rest of the word is its value
                if flag in _VALUE_SHORT[sub]:
                    if position == len(flags) - 1:
                        k += 1  # its value is the next word
                    break
        k += 1
    return False


def _skips_hooks(words: list[str], depth: int = 0) -> bool:
    """Is this simple command a git commit / push / merge that skips hooks?"""
    i = 0
    while i < len(words) and (
        _ASSIGNMENT_RE.match(words[i]) or words[i] in _PREFIX_WORDS
    ):
        i += 1
    if i >= len(words):
        return False
    program, rest = os.path.basename(words[i]), words[i + 1 :]

    if depth < 1 and program in _SHELLS:
        for j, word in enumerate(rest[:-1]):
            if word.startswith("-") and not word.startswith("--") and "c" in word:
                return any(
                    _skips_hooks(c, depth + 1) for c in simple_commands(rest[j + 1])
                )
        return False
    if depth < 1 and program == "eval":
        return any(_skips_hooks(c, depth + 1) for c in simple_commands(" ".join(rest)))
    if program != "git":
        return False

    j = 0
    hooks_path_overridden = False
    while j < len(rest) and rest[j].startswith("-"):
        if rest[j] == "-c" and rest[j + 1 : j + 2]:
            # ``git -c core.hooksPath=/dev/null commit`` runs no hook either.
            hooks_path_overridden |= (
                rest[j + 1].casefold().startswith("core.hookspath=")
            )
        j += 2 if rest[j] in _GIT_VALUE_OPTIONS else 1
    if j >= len(rest) or rest[j] not in _VALUE_LONG:
        return False
    return hooks_path_overridden or _args_skip_hooks(rest[j], rest[j + 1 :])


def skips_hooks(command: str) -> bool:
    """True when some simple command of ``command`` skips git hooks."""
    return any(_skips_hooks(words) for words in simple_commands(command))


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


def _relative_to_project(path: str, cwd: str | None, project_dir: Path) -> str | None:
    """``path`` as a lower-case POSIX path relative to the project, or
    ``None`` when it lies outside. ``~``, ``..`` and symlinked folders are
    resolved first. Letter case is ignored on purpose: on a case-folding
    file system (macOS) ``DATA/x`` and ``data/x`` are the same file, and on
    others asking once too often is the cheaper mistake."""
    candidate = Path(os.path.expanduser(path))
    if not candidate.is_absolute():
        candidate = Path(cwd or project_dir) / candidate
    try:
        resolved = os.path.realpath(candidate).casefold()
        root = os.path.realpath(project_dir).casefold().rstrip("/")
    except (OSError, ValueError):
        return None
    if resolved == root:
        return ""
    if not resolved.startswith(root + "/"):
        return None
    return resolved[len(root) + 1 :]


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
        if skips_hooks(command):
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
    except (ValueError, RecursionError):
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
        # The whole input: a Write carries the file's content, which can be
        # large, and a cut-off input is not valid JSON.
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES)
        out = run(
            raw.decode("utf-8", errors="replace"),
            project_dir=Path(project) if project else None,
            log_dir=Path(override) if override else None,
        )
    except Exception:  # noqa: BLE001 - never block every tool call on a bug here
        return 0
    if out:
        sys.stdout.write(out + "\n")
    return 0


__all__ = [
    "Decision",
    "EDIT_TOOLS",
    "OFF_LIMITS",
    "decide",
    "main",
    "run",
    "simple_commands",
    "skips_hooks",
]
