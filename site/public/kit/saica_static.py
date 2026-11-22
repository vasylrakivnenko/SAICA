#!/usr/bin/env python3
"""SAICA supervision kit: run a static checker with the SAICA-Bench flag rule.

Runs mypy, pyright, ruff, bandit or semgrep on the files a change touched and
applies the rule SAICA-Bench scored programs with: the change is flagged only
when a finding with one of the counted codes lands on a line the change ADDED.
A checker's own exit code says "this file has a problem somewhere", which is
true for about half of clean changes in a repository that is not already clean
under that checker; that is not the check the benchmark measured.

Prints ONE result line, the last line on stdout:

    flagged: <path>:<line> <code> <message>; ...   exit 1    saica_check.py records `caught`
    ok: <tool> found N finding(s) in M file(s); none with a counted code on an added line
                                                    exit 0    `pass`
    skipped: no changed .py files for <tool>        exit 0    `skipped`
    partial: <what the change did to the check>     exit 127  `error`
    error: <what went wrong>                        exit 127  `error`

``partial``: the tool found nothing that counts, but the change itself makes
the tool say less: it adds a suppression comment (``# noqa``, ``# type:
ignore``, ``# nosec``, ``nosemgrep``, ``# pyright: ...``) to a checked file, or
it edits the tool's own configuration (``ruff.toml``, ``mypy.ini``,
``pyrightconfig.json``, ``.bandit``, the tool's section of ``pyproject.toml`` /
``setup.cfg`` / ``tox.ini``). Such a change is never reported as ``ok``; with a
counted finding it is ``flagged`` and the note is added. A file renamed or
copied into another extension (``payload.txt`` -> ``payload.py``) is new to
the checker: all of its lines count as added.

``error`` covers: the tool is not installed, it failed (a crash, a bad option,
a file it could not parse), its output could not be read, a timeout, a git
failure, bad arguments. A tool failure never looks like ``ok`` or like a
finding. ``--error-exit N`` picks another code for use outside the kit runner.

Python 3.9+, standard library only, no shell: file names reach the tool as
separate arguments, each anchored as ``./name`` and (except for pyright, which
does not take it) after ``--``, so ``-x.py`` is not an option and ``@args.py``
is not an arguments file. Copy to ``.saica/saica_static.py`` and call it from a
``command`` in ``.saica/checks.json``; it works out the changed files itself,
so the command needs no ``{files}``::

    python3 .saica/saica_static.py --tool mypy --tool-arg=--check-untyped-defs \\
        --tool-arg=--follow-imports=silent \\
        --codes name-defined,import-not-found,attr-defined,call-arg,import --added-lines-only

Which change is checked (the same rule as saica_llm_review.py):
  --diff-file PATH   a unified diff file (``-`` = stdin); paths are relative to
                     the repository root
  --staged           ``git diff --cached``. Inside ``saica_check.py run --staged``
                     git is pointed at the snapshot's temporary index, so this is
                     exactly the change being committed.
  --commit REV       REV against its first parent (the empty tree for a root commit)
  (default)          --staged when SAICA_REPO_ROOT is set (saica_check's pre-commit
                     temporary checkout), otherwise --commit HEAD (CI, ``run --commit``,
                     manual runs).

The tool runs in the repository root (the temporary checkout of the staged
tree at pre-commit, the checked-out commit in CI) on the changed files that
still exist there, in batches. Only what the tool says about those files
counts. What each tool is run as (your ``--tool-arg`` values go before the
file names):

  mypy     mypy --show-error-codes --no-error-summary --no-color-output --show-column-numbers
           ``error:`` lines are findings (``note:`` lines are not); the code is
           the text in [brackets]. If mypy cannot check a batch (exit 2, for
           example two files with the same module name) each file is run alone.
  pyright  pyright --outputjson
           code = the diagnostic's rule; severity error / warning / information.
  ruff     ruff check --output-format json
  bandit   bandit -f json -q
           code = test id (B602); severity LOW / MEDIUM / HIGH.
  semgrep  semgrep scan --json --quiet --metrics=off --disable-version-check
           code = the rule id (``--codes`` also matches its last dotted part).
           Give the rules with --tool-arg=--config=...

The checker must see the project's installed packages, or every third-party
import looks like a missing one. ``--python PATH`` names the interpreter whose
packages mypy (--python-executable) and pyright (--pythonpath) resolve imports
against, for example ``--python .venv/bin/python``; a relative PATH is looked up
in the real checkout ($SAICA_REPO_ROOT) first, because a virtualenv is not part
of the temporary checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

EXIT_OK = 0
EXIT_FLAGGED = 1
DEFAULT_ERROR_EXIT = 127
DEFAULT_TIMEOUT_S = 240.0  # keep below the checks.json timeout_s (default 300)
RESULT_MAX = 300
MAX_LISTED = 5
# One command line stays under this many bytes of file names (Windows allows
# 32,767 characters for a whole command line).
BATCH_BYTES = 30000 if os.name == "nt" else 100000
PER_FILE_FALLBACK_MAX = 200  # a failed batch is re-run file by file up to this size
SAME_FAILURE_STOP = 3  # ... until this many runs in a row fail with the same words
ITEM_MAX = 110  # characters of one finding in the result line

_DIFF_ARGS = [
    "-c",
    "core.quotePath=false",
    "diff",
    "-U0",
    "--no-color",
    "--no-ext-diff",
    # A .gitattributes line (`*.py -diff`, a diff driver, a textconv filter)
    # must not be able to hide a change from the check.
    "--no-textconv",
    "--text",
    "--find-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
]


class StaticError(Exception):
    """A failure that is reported as ``error: ...`` with the error exit code."""


class ToolFailure(Exception):
    """The tool ran but did not check the files it was given."""


class Finding(NamedTuple):
    path: str
    line: int
    code: str
    severity: str
    message: str


class ToolSpec(NamedTuple):
    args: Tuple[str, ...]  # options the wrapper always passes
    exts: Tuple[str, ...]  # default file extensions; empty = every changed file
    ok_codes: Tuple[int, ...]  # exit codes of a run that checked its files
    python_flag: Optional[str]  # option that takes the --python interpreter
    per_file_fallback: bool  # re-run a failed batch one file at a time
    dashdash: bool = True  # put "--" before the file names (pyright reads it as a path)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def one_line(text: object, limit: int = RESULT_MAX) -> str:
    s = " ".join(_CONTROL_RE.sub(" ", str(text)).split())
    if len(s) > limit:
        s = s[: limit - 3].rstrip() + "..."
    return s


def say(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def warn(msg: str) -> None:
    sys.stderr.write("saica-static: " + msg + "\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# git and the diff
# ---------------------------------------------------------------------------


def git(args: List[str], check: bool = True) -> str:
    try:
        proc = subprocess.run(
            ["git"] + args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise StaticError("git is not installed or not on PATH")
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")
        name = next((a for a in args if not a.startswith("-") and "=" not in a), "")
        raise StaticError("git %s failed: %s" % (name, one_line(err, 200)))
    return proc.stdout.decode("utf-8", "replace")


def repo_root() -> Optional[str]:
    """Top of the work tree git sees from here, or None outside a repository."""
    try:
        out = git(["rev-parse", "--show-toplevel"], check=False).strip()
    except StaticError:
        return None
    return out or None


def staged_diff() -> str:
    return git(_DIFF_ARGS + ["--cached"])


def commit_diff(rev: str) -> str:
    sha = git(
        ["rev-parse", "--verify", "--quiet", rev + "^{commit}"], check=False
    ).strip()
    if not sha:
        raise StaticError("not a commit: %s" % rev)
    parents = git(["rev-list", "--parents", "-n", "1", sha]).split()
    if len(parents) > 1:
        base = parents[1]
    else:
        shallow = git(["rev-parse", "--git-path", "shallow"], check=False).strip()
        if shallow and os.path.isfile(shallow):
            try:
                with open(shallow, encoding="utf-8", errors="replace") as fh:
                    cut = fh.read().split()
            except OSError:
                cut = []
            if sha in cut:
                raise StaticError(
                    "%s has no parent in this shallow clone; fetch more history "
                    "(actions/checkout: fetch-depth: 0)" % sha[:12]
                )
        # This repository's empty tree (the id depends on its hash algorithm).
        base = git(["hash-object", "-t", "tree", "--stdin"]).strip()
    return git(_DIFF_ARGS + [base, sha])


def obtain_diff(args: argparse.Namespace) -> Tuple[str, str]:
    if args.diff_file:
        if args.diff_file == "-":
            return sys.stdin.read(), "stdin"
        try:
            with open(args.diff_file, encoding="utf-8", errors="replace") as fh:
                return fh.read(), "diff file %s" % args.diff_file
        except OSError as exc:
            raise StaticError(
                "cannot read diff file %s: %s" % (args.diff_file, exc.strerror or exc)
            )
    if args.staged or (args.commit is None and os.environ.get("SAICA_REPO_ROOT")):
        return staged_diff(), "staged changes"
    rev = args.commit or "HEAD"
    return commit_diff(rev), "commit %s" % rev


_HUNK_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_C_ESCAPES = {
    "a": 7,
    "b": 8,
    "t": 9,
    "n": 10,
    "v": 11,
    "f": 12,
    "r": 13,
    '"': 34,
    "\\": 92,
}


def unquote_path(text: str) -> str:
    """A file name as git prints it in a ``---`` / ``+++`` line.

    Names with special characters come in double quotes with C escapes
    (``\\n``, ``\\"``, octal ``\\303\\274``); a name with a space is followed by
    a TAB, and other diff tools put a TAB and a time stamp after the name.
    """
    text = text.rstrip("\r\n")
    if not text.startswith('"'):
        return text.split("\t", 1)[0]
    out = bytearray()
    i, n = 1, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            break
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt in "01234567":
                j = i + 1
                while j < n and j < i + 4 and text[j] in "01234567":
                    j += 1
                out.append(int(text[i + 1 : j], 8) & 0xFF)
                i = j
                continue
            if nxt in _C_ESCAPES:
                out.append(_C_ESCAPES[nxt])
                i += 2
                continue
        out.extend(ch.encode("utf-8", "surrogatepass"))
        i += 1
    return out.decode("utf-8", "replace")


def diff_paths(text: str) -> List[str]:
    """Every path named in the ``diff --git`` lines of a diff (deleted files too)."""
    out: List[str] = []
    for line in text.split("\n"):
        if not line.startswith("diff --git "):
            continue
        rest = line[len("diff --git ") :].rstrip("\r")
        half = (len(rest) - 1) // 2
        if (
            len(rest) % 2 == 1
            and rest[half] == " "
            and rest[2:half] == rest[half + 3 :]
        ):
            out.append(rest[2:half])  # a/<path> b/<path>
        else:
            for part in rest.split(" "):
                if part.startswith(("a/", "b/")):
                    out.append(part[2:])
    return out


def parse_renames(text: str) -> Dict[str, str]:
    """{new path: old path} of the renames and copies in a git diff."""
    out: Dict[str, str] = {}
    old: Optional[str] = None
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            old = None
        elif line.startswith(("rename from ", "copy from ")):
            old = unquote_path(line.split(" from ", 1)[1])
        elif line.startswith(("rename to ", "copy to ")) and old is not None:
            out[unquote_path(line.split(" to ", 1)[1])] = old
    return out


def parse_changes(
    text: str,
) -> Tuple[Dict[str, Dict[int, str]], Dict[str, List[Tuple[int, str]]]]:
    """(added, removed) of a unified diff, by NEW path: added = {line number:
    text}; removed = [(line number in the new file where the removed line was,
    text)]. See parse_added_lines for which files are listed."""
    added: Dict[str, Dict[int, str]] = {}
    removed: Dict[str, List[Tuple[int, str]]] = {}
    cur: Optional[str] = None
    old_name: Optional[str] = None
    old_left = new_left = new_no = 0
    for line in text.split("\n"):
        if old_left > 0 or new_left > 0:  # inside a hunk
            tag = line[:1]
            if tag == "+":
                if cur is not None:
                    added[cur][new_no] = line[1:].rstrip("\r")
                new_no += 1
                new_left -= 1
                continue
            if tag == "-":
                if cur is not None:
                    removed[cur].append((new_no, line[1:].rstrip("\r")))
                old_left -= 1
                continue
            if tag == "\\":  # "\ No newline at end of file"
                continue
            if tag == " " or line == "":
                old_left -= 1
                new_left -= 1
                new_no += 1
                continue
            old_left = new_left = 0  # malformed hunk: resynchronise below
        if line.startswith("diff --git "):
            cur, old_name = None, None
            continue
        if line.startswith("--- "):
            old_name = unquote_path(line[4:])
            cur = None
            continue
        if line.startswith("+++ "):
            new = unquote_path(line[4:])
            cur = None
            if new != "/dev/null":
                if new.startswith("b/") and (
                    old_name is None
                    or old_name == "/dev/null"
                    or old_name.startswith("a/")
                ):
                    new = new[2:]
                if new:
                    cur = new
                    added.setdefault(new, {})
                    removed.setdefault(new, [])
            continue
        m = _HUNK_RE.match(line)
        if m:
            old_left = int(m.group(1)) if m.group(1) is not None else 1
            new_no = int(m.group(2))
            new_left = int(m.group(3)) if m.group(3) is not None else 1
    return added, removed


# Comments that tell a checker to stay quiet. A change that adds one may be
# hiding a finding from this very check.
SUPPRESSIONS = {
    "mypy": re.compile(r"#\s*type:\s*ignore", re.I),
    "pyright": re.compile(r"#\s*(type:\s*ignore|pyright:\s*\w)", re.I),
    "ruff": re.compile(r"#\s*(noqa|ruff:\s*noqa|flake8:\s*noqa)", re.I),
    "bandit": re.compile(r"#\s*(nosec|noqa)", re.I),
    "semgrep": re.compile(r"nosem(grep)?\b", re.I),
}
# The checker's own configuration: files that are only about it, and the
# sections of shared files (a line that starts one of them, as a regex).
CONFIG_FILES = {
    "mypy": ("mypy.ini", ".mypy.ini"),
    "pyright": ("pyrightconfig.json",),
    "ruff": ("ruff.toml", ".ruff.toml"),
    "bandit": (".bandit", "bandit.yaml", "bandit.yml"),
    "semgrep": (".semgrepignore", ".semgrep.yml", ".semgrep.yaml"),
}
CONFIG_SECTIONS = {
    "mypy": r"\[(tool\.)?mypy[\].\-:]|\[mypy\]",
    "pyright": r"\[tool\.(pyright|basedpyright)[\].]",
    "ruff": r"\[tool\.ruff[\].]",
    "bandit": r"\[tool\.bandit[\].]|\[bandit\]",
    "semgrep": r"\[tool\.semgrep[\].]",
}
SHARED_CONFIG = ("pyproject.toml", "setup.cfg", "tox.ini")


def suppressions_added(
    tool: str, files: List[str], added: Dict[str, Dict[int, str]]
) -> List[str]:
    """``path:line`` of every suppression comment the change adds to a checked file."""
    rx = SUPPRESSIONS[tool]
    out = []
    for path in files:
        for no, text in sorted(added.get(path, {}).items()):
            if rx.search(text):
                out.append("%s:%d" % (path, no))
    return out


def config_edits(
    tool: str,
    added: Dict[str, Dict[int, str]],
    removed: Dict[str, List[Tuple[int, str]]],
    renames: Dict[str, str],
    all_changed: List[str],
) -> List[str]:
    """Configuration files of ``tool`` that the change touches."""
    hits: List[str] = []
    head = re.compile(r"^\s*(%s)" % CONFIG_SECTIONS[tool])
    for path in sorted(
        set(all_changed) | set(added) | set(renames) | set(renames.values())
    ):
        base = path.rsplit("/", 1)[-1]
        if base in CONFIG_FILES[tool] or (
            tool == "semgrep" and "/.semgrep/" in "/" + path
        ):
            hits.append(path)
            continue
        if base not in SHARED_CONFIG:
            continue
        add, rem = added.get(path, {}), removed.get(path, [])
        touched = set(add) | {no for no, _t in rem}
        texts = list(add.values()) + [t for _no, t in rem]
        inside: Set[int] = set()
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                current = False
                for no, line in enumerate(fh, 1):
                    if line.lstrip().startswith("["):
                        current = bool(head.match(line))
                    if current:
                        inside.add(no)
        except OSError:
            pass
        if touched & inside or any(head.match(t) for t in texts):
            hits.append(path)
    return hits


def parse_added_lines(text: str) -> Dict[str, Set[int]]:
    """Map each file a unified diff changes (its NEW path) to the line numbers it adds.

    Only files with at least one hunk on the new side are listed; a file whose
    hunks only delete lines maps to an empty set. Pure renames, mode changes,
    deletions and binary files are not listed. Hunk sizes are taken from the
    ``@@`` header, so an added line that itself starts with ``++`` or ``@@`` is
    read as content.
    """
    changed: Dict[str, Set[int]] = {}
    current: Optional[Set[int]] = None
    old_name: Optional[str] = None
    old_left = new_left = new_no = 0
    for line in text.split("\n"):
        if old_left > 0 or new_left > 0:  # inside a hunk
            tag = line[:1]
            if tag == "+":
                if current is not None:
                    current.add(new_no)
                new_no += 1
                new_left -= 1
                continue
            if tag == "-":
                old_left -= 1
                continue
            if tag == "\\":  # "\ No newline at end of file"
                continue
            if tag == " " or line == "":
                # An empty line here is a context line whose single space was
                # stripped by a mail client or an editor.
                old_left -= 1
                new_left -= 1
                new_no += 1
                continue
            old_left = new_left = 0  # malformed hunk: resynchronise below
        if line.startswith("diff --git "):
            current, old_name = None, None
            continue
        if line.startswith("--- "):
            old_name = unquote_path(line[4:])
            current = None
            continue
        if line.startswith("+++ "):
            new = unquote_path(line[4:])
            current = None
            if new != "/dev/null":
                if new.startswith("b/") and (
                    old_name is None
                    or old_name == "/dev/null"
                    or old_name.startswith("a/")
                ):
                    new = new[2:]
                if new:
                    current = changed.setdefault(new, set())
            continue
        m = _HUNK_RE.match(line)
        if m:
            old_left = int(m.group(1)) if m.group(1) is not None else 1
            new_no = int(m.group(2))
            new_left = int(m.group(3)) if m.group(3) is not None else 1
    return changed


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def _safe_relative(path: str) -> bool:
    if not path or os.path.isabs(path):
        return False
    norm = os.path.normpath(path).replace("\\", "/")
    return norm != ".." and not norm.startswith("../")


def select_files(
    changed: Dict[str, Set[int]], exts: Tuple[str, ...], added_only: bool
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """(files to hand to the tool, files that cannot be checked and why)."""
    files: List[str] = []
    refused: List[Tuple[str, str]] = []
    for path in sorted(changed):
        if added_only and not changed[path]:
            continue
        if exts and not path.lower().endswith(exts):
            continue
        if not _safe_relative(path) or not os.path.isfile(path):
            continue  # deleted, a submodule, or not under the repository root
        if _CONTROL_RE.search(path):
            # Line-based tool output cannot name such a file reliably, so a
            # finding in it could be lost: report it instead of passing it.
            refused.append((path, "its name has a control character"))
            continue
        files.append(path)
    return files, refused


def batches(files: List[str], limit: int = BATCH_BYTES) -> List[List[str]]:
    out: List[List[str]] = []
    cur: List[str] = []
    size = 0
    for f in files:
        n = len(f.encode("utf-8", "replace")) + 3  # "./" prefix or separator
        if cur and size + n > limit:
            out.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += n
    if cur:
        out.append(cur)
    return out


def find_path(name: str) -> Optional[str]:
    """Resolve a user-given path: absolute as is; relative against the real
    checkout ($SAICA_REPO_ROOT, set during a pre-commit run) and then the
    current directory. Returns an absolute path or None."""
    p = os.path.expanduser(name)
    if os.path.isabs(p):
        return p if os.path.exists(p) else None
    bases = []
    root = os.environ.get("SAICA_REPO_ROOT")
    if root:
        bases.append(root)
    bases.append(os.getcwd())
    for base in bases:
        cand = os.path.join(base, p)
        if os.path.exists(cand):
            return os.path.abspath(cand)
    return None


# ---------------------------------------------------------------------------
# Tools: how each one is run and how its output is read
# ---------------------------------------------------------------------------

TOOLS: Dict[str, ToolSpec] = {
    "mypy": ToolSpec(
        args=(
            "--show-error-codes",
            "--no-error-summary",
            "--no-color-output",
            "--show-column-numbers",
        ),
        exts=(".py", ".pyi"),
        ok_codes=(0, 1),
        python_flag="--python-executable",
        per_file_fallback=True,
    ),
    "pyright": ToolSpec(
        args=("--outputjson",),
        exts=(".py", ".pyi"),
        ok_codes=(0, 1),
        python_flag="--pythonpath",
        per_file_fallback=False,
        dashdash=False,
    ),
    "ruff": ToolSpec(
        args=("check", "--output-format", "json"),
        exts=(".py", ".pyi"),
        ok_codes=(0, 1),
        python_flag=None,
        per_file_fallback=False,
    ),
    "bandit": ToolSpec(
        args=("-f", "json", "-q"),
        exts=(".py",),
        ok_codes=(0, 1),
        python_flag=None,
        per_file_fallback=False,
    ),
    "semgrep": ToolSpec(
        args=(
            "scan",
            "--json",
            "--quiet",
            "--metrics=off",
            "--disable-version-check",
        ),
        exts=(),
        ok_codes=(0, 1),
        python_flag=None,
        per_file_fallback=False,
    ),
}

Parsed = Tuple[List[Finding], List[Tuple[str, str]]]

_MYPY_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?:\d+:)? (?P<sev>error|warning|note): "
    r"(?P<msg>.*?)(?:  \[(?P<code>[\w-]+)\])?$"
)
_RUFF_SYNTAX = {"syntax", "invalid-syntax", "syntax-error", "e999"}


def _tail(text: str, limit: int = 200) -> str:
    """The lines of a tool's output that say what went wrong, as one line."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    errors = [ln for ln in lines if re.search(r"\berror\b", ln, re.I)]
    return one_line(" | ".join(errors[:2] or lines[-3:]), limit)


def _load_json(stdout: str, want: type, tool: str) -> object:
    """The JSON document a tool printed; tolerates text before or after it."""
    text = stdout.strip()
    opener, closer = ("{", "}") if want is dict else ("[", "]")
    candidates = [text]
    start, end = text.find(opener), text.rfind(closer)
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
        except ValueError:
            continue
        if isinstance(data, want):
            return data
    raise ToolFailure(
        "%s output is not the expected JSON: %s" % (tool, _tail(stdout) or "(empty)")
    )


def _as_int(value: object) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def parse_mypy(stdout: str, stderr: str, rc: int) -> Parsed:
    findings = []
    for line in stdout.splitlines():
        m = _MYPY_RE.match(line.rstrip("\r"))
        if m and m.group("sev") == "error":
            findings.append(
                Finding(
                    m.group("file"),
                    int(m.group("line")),
                    m.group("code") or "error",
                    "error",
                    m.group("msg"),
                )
            )
    if rc == 1 and not findings:
        raise ToolFailure(
            "mypy reported errors (exit 1) but none could be read: %s"
            % (_tail(stdout + "\n" + stderr) or "(no output)")
        )
    return findings, []


def parse_pyright(stdout: str, stderr: str, rc: int) -> Parsed:
    data = _load_json(stdout, dict, "pyright")
    assert isinstance(data, dict)
    diags = data.get("generalDiagnostics")
    if not isinstance(diags, list):
        raise ToolFailure("pyright output has no generalDiagnostics list")
    findings: List[Finding] = []
    unparsed: List[Tuple[str, str]] = []
    for d in diags:
        if not isinstance(d, dict):
            continue
        path = d.get("file")
        rng = d.get("range")
        start = rng.get("start") if isinstance(rng, dict) else None
        line = _as_int(start.get("line")) if isinstance(start, dict) else None
        if not isinstance(path, str) or line is None:
            continue
        severity = str(d.get("severity") or "error")
        rule = d.get("rule")
        message = str(d.get("message") or "")
        findings.append(
            Finding(
                path,
                line + 1,
                rule if isinstance(rule, str) and rule else severity,
                severity,
                message,
            )
        )
        if severity == "error" and not rule:
            # Errors without a rule are parser errors: the file is not valid
            # Python, so the rules were not really applied to it.
            unparsed.append((path, "line %d: %s" % (line + 1, message)))
    return findings, unparsed


def parse_ruff(stdout: str, stderr: str, rc: int) -> Parsed:
    data = _load_json(stdout, list, "ruff")
    assert isinstance(data, list)
    findings: List[Finding] = []
    unparsed: List[Tuple[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        path = item.get("filename")
        loc = item.get("location")
        line = _as_int(loc.get("row")) if isinstance(loc, dict) else None
        if not isinstance(path, str) or line is None:
            continue
        code = item.get("code")
        code = code if isinstance(code, str) and code else "syntax"
        message = str(item.get("message") or "")
        findings.append(
            Finding(path, line, code, str(item.get("severity") or "error"), message)
        )
        if code.lower() in _RUFF_SYNTAX:
            unparsed.append((path, "line %d: %s" % (line, message)))
    if rc == 1 and not findings:
        raise ToolFailure("ruff reported findings (exit 1) but its JSON list is empty")
    return findings, unparsed


def parse_bandit(stdout: str, stderr: str, rc: int) -> Parsed:
    data = _load_json(stdout, dict, "bandit")
    assert isinstance(data, dict)
    results = data.get("results")
    if not isinstance(results, list):
        raise ToolFailure("bandit output has no results list")
    findings: List[Finding] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        path = item.get("filename")
        line = _as_int(item.get("line_number"))
        if not isinstance(path, str) or line is None:
            continue
        findings.append(
            Finding(
                path,
                line,
                str(item.get("test_id") or "bandit"),
                str(item.get("issue_severity") or ""),
                str(item.get("issue_text") or ""),
            )
        )
    unparsed: List[Tuple[str, str]] = []
    errors = data.get("errors")
    for err in errors if isinstance(errors, list) else []:
        if isinstance(err, dict):  # bandit exits 0 for a file it could not parse
            unparsed.append(
                (str(err.get("filename") or ""), str(err.get("reason") or "error"))
            )
    return findings, unparsed


def parse_semgrep(stdout: str, stderr: str, rc: int) -> Parsed:
    data = _load_json(stdout, dict, "semgrep")
    assert isinstance(data, dict)
    results = data.get("results")
    if not isinstance(results, list):
        raise ToolFailure("semgrep output has no results list")
    findings: List[Finding] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        start = item.get("start")
        line = _as_int(start.get("line")) if isinstance(start, dict) else None
        if not isinstance(path, str) or line is None:
            continue
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        findings.append(
            Finding(
                path,
                line,
                str(item.get("check_id") or "semgrep"),
                str(extra.get("severity") or ""),
                str(extra.get("message") or ""),
            )
        )
    unparsed: List[Tuple[str, str]] = []
    errors = data.get("errors")
    for err in errors if isinstance(errors, list) else []:
        if not isinstance(err, dict) or str(err.get("level")).lower() != "error":
            continue  # warnings (partial parsing) do not stop the rules
        message = str(err.get("message") or err.get("type") or "error")
        path = err.get("path")
        if isinstance(path, str) and path:
            unparsed.append((path, message))
        else:  # a rule or the configuration failed: nothing was checked as asked
            raise ToolFailure("semgrep: %s" % one_line(message, 200))
    return findings, unparsed


PARSERS = {
    "mypy": parse_mypy,
    "pyright": parse_pyright,
    "ruff": parse_ruff,
    "bandit": parse_bandit,
    "semgrep": parse_semgrep,
}


def failure_text(tool: str, stdout: str, stderr: str, rc: int) -> str:
    """Why a run with a failing exit code failed, in one line."""
    detail = ""
    if tool == "semgrep":  # semgrep explains its exit code in the JSON it prints
        try:
            data = json.loads(stdout)
            errors = data.get("errors") if isinstance(data, dict) else None
            msgs = [
                str(e.get("message"))
                for e in (errors if isinstance(errors, list) else [])
                if isinstance(e, dict) and e.get("message")
            ]
            detail = one_line(" | ".join(msgs), 200)
        except ValueError:
            detail = ""
    if not detail:
        detail = _tail(stderr) or _tail(stdout) or "(no output)"
    if rc < 0:
        return "%s was killed by signal %d: %s" % (tool, -rc, detail)
    return "%s failed (exit %d): %s" % (tool, rc, detail)


# ---------------------------------------------------------------------------
# Running the tool
# ---------------------------------------------------------------------------


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def run_command(cmd: List[str], timeout: float) -> Tuple[int, str, str]:
    """Run without a shell; on timeout kill the tool and its children."""
    kwargs = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True  # its own process group
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except BaseException:  # timeout, Ctrl-C: never leave the tool running
        _kill(proc)
        try:
            proc.communicate(timeout=10)
        except Exception:  # noqa: BLE001 - best effort: the tool is already killed
            pass
        raise
    return (
        proc.returncode,
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
    )


class Timeout(ToolFailure):
    """The time budget is used up: no further run is started."""


class Runner:
    """Runs the tool over the files in batches and collects what it says.

    ``run_failures`` holds (files, reason) for runs that did not check their
    files; ``file_failures`` holds (file, reason) for single files the tool
    reported it could not read. Both mean "not checked", never "clean".
    """

    def __init__(
        self, tool: str, binary: str, extra: List[str], timeout: float, verbose: bool
    ) -> None:
        self.tool = tool
        self.spec = TOOLS[tool]
        self.base = [binary] + list(self.spec.args) + list(extra)
        self.timeout = timeout
        self.deadline = time.monotonic() + timeout
        self.verbose = verbose
        self.findings: List[Finding] = []
        self.run_failures: List[Tuple[List[str], str]] = []
        self.file_failures: List[Tuple[str, str]] = []

    def _once(self, files: List[str]) -> Parsed:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise Timeout("%s timed out after %gs" % (self.tool, self.timeout))
        # Every name is anchored to the cwd ("./name") and, where the tool takes
        # it, comes after "--": a file called "-x.py" is not an option and
        # "@args.py" is not an arguments file (mypy reads "@file" that way).
        argv = (
            self.base
            + (["--"] if self.spec.dashdash else [])
            + [f if os.path.isabs(f) else "./" + f for f in files]
        )
        if self.verbose:
            warn("running %s on %d file(s)" % (" ".join(self.base), len(files)))
        try:
            rc, out, err = run_command(argv, remaining)
        except subprocess.TimeoutExpired:
            raise Timeout("%s timed out after %gs" % (self.tool, self.timeout))
        except FileNotFoundError:
            raise StaticError(
                "%s is not installed or not on PATH (tried to run %r)"
                % (self.tool, self.base[0])
            )
        except OSError as exc:
            raise StaticError(
                "could not start %s (%r): %s"
                % (self.tool, self.base[0], exc.strerror or exc)
            )
        if self.verbose:
            warn("%s exit %d" % (self.tool, rc))
        if rc not in self.spec.ok_codes:
            raise ToolFailure(failure_text(self.tool, out, err, rc))
        return PARSERS[self.tool](out, err, rc)

    def _keep(self, parsed: Parsed) -> None:
        self.findings.extend(parsed[0])
        self.file_failures.extend(parsed[1])

    def check(self, files: List[str]) -> None:
        todo = batches(files)
        for i, batch in enumerate(todo):
            try:
                self._keep(self._once(batch))
                continue
            except Timeout as exc:
                rest = [f for b in todo[i:] for f in b]
                self.run_failures.append((rest, str(exc)))
                return
            except ToolFailure as exc:
                alone = (
                    self.spec.per_file_fallback
                    and 1 < len(batch) <= PER_FILE_FALLBACK_MAX
                )
                if not alone:
                    self.run_failures.append((batch, str(exc)))
                    continue
                if self.verbose:
                    warn("%s; running each file alone" % exc)
            same = 0  # runs in a row that failed with the same words
            last = ""
            for j, name in enumerate(batch):
                try:
                    self._keep(self._once([name]))
                    same, last = 0, ""
                except Timeout as exc:
                    rest = batch[j:] + [f for b in todo[i + 1 :] for f in b]
                    self.run_failures.append((rest, str(exc)))
                    return
                except ToolFailure as exc:
                    same = same + 1 if str(exc) == last else 1
                    last = str(exc)
                    if same < SAME_FAILURE_STOP:
                        self.run_failures.append(([name], last))
                        continue
                    # Not about one file (a bad option, a broken install):
                    # the rest of the batch would fail the same way.
                    self.run_failures.append((batch[j:], last))
                    break


# ---------------------------------------------------------------------------
# The flag rule
# ---------------------------------------------------------------------------


def rel_path(path: str, roots: List[str]) -> str:
    """A path from tool output as git names it: relative to the root, with ``/``."""
    p = path
    if os.path.isabs(p):
        cands = [p]
        try:
            cands.append(os.path.realpath(p))
        except OSError:
            pass
        done = False
        for cand in cands:
            for root in roots:
                try:
                    rel = os.path.relpath(cand, root)
                except ValueError:  # another drive on Windows
                    continue
                if rel != ".." and not rel.startswith(".." + os.sep):
                    p, done = rel, True
                    break
            if done:
                break
    return os.path.normpath(p).replace(os.sep, "/")


def split_list(values: List[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        out.extend(x for x in re.split(r"[,\s]+", value) if x)
    return out


def code_matches(code: str, wanted: List[str], tool: str) -> bool:
    names = [code.lower()]
    if tool == "semgrep" and "." in code:
        names.append(code.lower().rsplit(".", 1)[1])
    for item in wanted:
        w = item.lower()
        for name in names:
            if (w.endswith("*") and name.startswith(w[:-1])) or name == w:
                return True
    return False


def count_findings(
    findings: List[Finding],
    files: List[str],
    added: Dict[str, Set[int]],
    codes: List[str],
    severities: List[str],
    added_only: bool,
    tool: str,
    roots: List[str],
) -> Tuple[List[Finding], int]:
    """(findings that flag the change, findings in the checked files)."""
    checked = set(files)
    sev = {s.lower() for s in severities}
    counted: List[Finding] = []
    seen: Set[Tuple[str, int, str, str]] = set()
    total = 0
    for f in findings:
        path = rel_path(f.path, roots)
        key = (path, f.line, f.code, f.message)
        if path not in checked or key in seen:
            continue
        seen.add(key)
        total += 1
        if codes and not code_matches(f.code, codes, tool):
            continue
        if sev and f.severity.lower() not in sev:
            continue
        if added_only and f.line not in added.get(path, set()):
            continue
        counted.append(Finding(path, f.line, f.code, f.severity, f.message))
    counted.sort(key=lambda x: (x.path, x.line, x.code))
    return counted, total


def short_code(tool: str, code: str) -> str:
    """A rule id short enough for the result line (semgrep ids carry their path)."""
    if tool == "semgrep" and len(code) > 40 and "." in code:
        return code.rsplit(".", 1)[1]
    return code


def flagged_line(counted: List[Finding], unchecked: int, tool: str) -> str:
    """The ``flagged:`` line: findings in full while they fit, then a count."""
    note = ""
    if unchecked:
        note = " [%s could not check %d other file(s)]" % (tool, unchecked)
    shown: List[str] = []
    for f in counted[:MAX_LISTED]:
        item = one_line(
            "%s:%d %s %s" % (f.path, f.line, short_code(tool, f.code), f.message),
            ITEM_MAX,
        )
        more = " (+%d more)" % (len(counted) - len(shown) - 1)
        used = len("flagged: ") + sum(len(x) + 2 for x in shown) + len(item)
        if shown and used + len(more) + len(note) > RESULT_MAX:
            break
        shown.append(item)
    rest = len(counted) - len(shown)
    tail = (" (+%d more)" % rest if rest else "") + note
    return "flagged: " + one_line("; ".join(shown), RESULT_MAX - 9 - len(tail)) + tail


def ok_line(
    tool: str,
    total: int,
    n_files: int,
    codes: List[str],
    severities: List[str],
    added_only: bool,
) -> str:
    if not total:
        return "ok: %s found no findings in %d file(s)" % (tool, n_files)
    what = []
    if codes:
        what.append("with a counted code")
    if severities:
        what.append("of severity %s" % "/".join(severities))
    if added_only:
        what.append("on an added line")
    return "ok: %s found %d finding(s) in %d file(s); none %s" % (
        tool,
        total,
        n_files,
        " ".join(what) if what else "counted",
    )


def failed_text(
    tool: str,
    run_failures: List[Tuple[List[str], str]],
    file_failures: List[Tuple[str, str]],
    n_files: int,
) -> str:
    """One line for files that were not checked: how many, then why."""
    unchecked: Set[str] = set()
    reasons: List[str] = []
    for files, reason in run_failures:
        unchecked.update(files)
        if reason not in reasons:
            reasons.append(reason)
    for path, reason in file_failures:
        if path in unchecked:
            continue  # one reason per file is enough
        unchecked.add(path)
        reasons.append("%s could not check %s: %s" % (tool, path, reason))
    more = " (+%d more)" % (len(reasons) - 2) if len(reasons) > 2 else ""
    return one_line(
        "%d of %d file(s) not checked: %s%s"
        % (len(unchecked), n_files, "; ".join(reasons[:2]), more)
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    error_exit = DEFAULT_ERROR_EXIT

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        say("error: bad arguments: %s" % one_line(message, 200))
        sys.exit(self.error_exit)


def _prescan_error_exit(argv: List[str]) -> int:
    for i, a in enumerate(argv):
        val = None
        if a == "--error-exit" and i + 1 < len(argv):
            val = argv[i + 1]
        elif a.startswith("--error-exit="):
            val = a.split("=", 1)[1]
        if val is not None:
            try:
                n = int(val)
            except ValueError:
                return DEFAULT_ERROR_EXIT
            return n if 0 <= n <= 255 and n != EXIT_FLAGGED else DEFAULT_ERROR_EXIT
    return DEFAULT_ERROR_EXIT


def build_parser() -> _Parser:
    p = _Parser(
        prog="saica_static.py",
        description=(
            "Run a static checker on the changed files and apply the SAICA-Bench "
            "flag rule: counted codes on added lines. Prints one line: "
            "'flagged: ...' (exit 1), 'ok: ...' or 'skipped: ...' (exit 0), or "
            "'error: ...' (exit 127, which saica_check.py records as 'error')."
        ),
    )
    p.add_argument(
        "--tool",
        required=True,
        choices=sorted(TOOLS),
        help="the checker to run",
    )
    p.add_argument(
        "--codes",
        action="append",
        default=[],
        metavar="C1,C2",
        help="counted rule codes, comma-separated (repeatable); an item ending "
        "in * matches by prefix, e.g. NPY*. Default: every finding counts",
    )
    p.add_argument(
        "--severity",
        action="append",
        default=[],
        metavar="LEVEL",
        help="count only findings of this severity, e.g. error (pyright: error / "
        "warning / information; bandit: LOW / MEDIUM / HIGH). Default: any",
    )
    p.add_argument(
        "--added-lines-only",
        action="store_true",
        help="count only findings on lines the change added "
        "(default: any line of a changed file)",
    )
    p.add_argument(
        "--tool-arg",
        action="append",
        default=[],
        metavar="ARG",
        help="extra argument for the tool (repeatable); write "
        "--tool-arg=--check-untyped-defs when ARG starts with a dash",
    )
    p.add_argument(
        "--tool-bin",
        metavar="PATH",
        help="executable to run (default: the tool's name, looked up on PATH)",
    )
    p.add_argument(
        "--python",
        metavar="PATH",
        help="interpreter whose installed packages mypy / pyright resolve "
        "imports against, e.g. .venv/bin/python",
    )
    p.add_argument(
        "--ext",
        action="append",
        default=[],
        metavar=".py,.pyi",
        help="extensions of the files handed to the tool; * = every changed "
        "file (default: .py,.pyi for mypy / pyright / ruff, .py for bandit, "
        "every file for semgrep)",
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--diff-file", metavar="PATH", help="check this unified diff (- = stdin)"
    )
    src.add_argument("--staged", action="store_true", help="check git diff --cached")
    src.add_argument(
        "--commit", metavar="REV", help="check REV against its first parent"
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        metavar="S",
        help="total seconds for the tool runs; keep it below the checks.json "
        "timeout_s (default: %g)" % DEFAULT_TIMEOUT_S,
    )
    p.add_argument(
        "--error-exit",
        type=int,
        default=DEFAULT_ERROR_EXIT,
        metavar="N",
        help="exit code for errors (default: 127, recorded as 'error' by "
        "saica_check.py); 1 means flagged and is not allowed",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="report the diff source, the files and each tool run on stderr",
    )
    return p


def _extensions(args: argparse.Namespace) -> Tuple[str, ...]:
    items = split_list(args.ext)
    if not items:
        return TOOLS[args.tool].exts
    if "*" in items:
        return ()
    return tuple(("." + x.lstrip(".")).lower() for x in items if x.strip("."))


def _binary(args: argparse.Namespace) -> str:
    spec = args.tool_bin
    if not spec:
        return shutil.which(args.tool) or args.tool
    if os.sep in spec or (os.altsep and os.altsep in spec) or spec.startswith("~"):
        found = find_path(spec)
        if found is None:
            raise StaticError("--tool-bin not found: %s" % spec)
        return found
    return shutil.which(spec) or spec


def run(p: _Parser, args: argparse.Namespace) -> int:
    if args.timeout <= 0:
        p.error("--timeout must be > 0")
    if not 0 <= args.error_exit <= 255 or args.error_exit == EXIT_FLAGGED:
        p.error("--error-exit must be 0 or 2..255 (1 means flagged)")
    tool = args.tool
    spec = TOOLS[tool]
    codes = split_list(args.codes)
    severities = split_list(args.severity)
    exts = _extensions(args)

    # Resolve user paths before moving to the repository root.
    binary = _binary(args)
    extra: List[str] = []
    if args.python:
        if spec.python_flag is None:
            warn("--python is not used by %s; ignored" % tool)
        else:
            py = find_path(args.python)
            if py is None:
                raise StaticError("--python not found: %s" % args.python)
            extra += [spec.python_flag, py]
    extra += list(args.tool_arg)
    if args.diff_file and args.diff_file != "-":
        found = find_path(args.diff_file)
        if found is None:
            raise StaticError("diff file not found: %s" % args.diff_file)
        args.diff_file = found

    diff, source = obtain_diff(args)
    root = repo_root()
    if root:
        os.chdir(root)  # git names files relative to the top of the work tree
    cwd = os.getcwd()
    roots = [cwd]
    real = os.path.realpath(cwd)
    if real != cwd:
        roots.append(real)

    changed = parse_added_lines(diff)
    added, removed = parse_changes(diff)
    renames = parse_renames(diff)
    for new, old in renames.items():
        # A file renamed or copied into another extension (payload.txt ->
        # payload.py) is new to this checker: every line of it counts as added.
        if os.path.splitext(new)[1].lower() == os.path.splitext(old)[1].lower():
            continue
        if not _safe_relative(new) or not os.path.isfile(new):
            continue
        try:
            with open(new, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().split("\n")
        except OSError:
            continue
        changed[new] = set(range(1, len(lines) + 1))
        added[new] = {i: text for i, text in enumerate(lines, 1)}
    files, refused = select_files(changed, exts, args.added_lines_only)
    ext_text = (", ".join(exts) + " ") if exts else ""
    # Two ways a change can make this check say less than it would have:
    quiet = suppressions_added(tool, files, added)
    edits = config_edits(tool, added, removed, renames, diff_paths(diff))
    hides: List[str] = []
    if quiet:
        hides.append(
            "adds %d suppression comment(s) (%s)"
            % (len(quiet), ", ".join(quiet[:3]) + (", ..." if len(quiet) > 3 else ""))
        )
    if edits:
        hides.append(
            "edits %s's configuration (%s)"
            % (tool, ", ".join(edits[:3]) + (", ..." if len(edits) > 3 else ""))
        )
    if args.verbose:
        warn(
            "%s: %d changed file(s), %d handed to %s"
            % (source, len(changed), len(files), tool)
        )
    if not files and not refused:
        if hides:
            say(
                "partial: %s"
                % one_line(
                    "no file was checked, but the change %s; that can hide findings "
                    "from %s, so a person should look" % (" and ".join(hides), tool)
                )
            )
            return args.error_exit
        if not changed:
            say("skipped: no changes to check (%s)" % source)
        elif args.added_lines_only:
            say(
                "skipped: no changed %sfiles with added lines for %s" % (ext_text, tool)
            )
        else:
            say("skipped: no changed %sfiles for %s" % (ext_text, tool))
        return EXIT_OK

    runner = Runner(tool, binary, extra, args.timeout, args.verbose)
    if files:
        runner.check(files)
    file_failures = refused + [
        (rel_path(path, roots), why) for path, why in runner.file_failures
    ]
    counted, total = count_findings(
        runner.findings,
        files,
        changed,
        codes,
        severities,
        args.added_lines_only,
        tool,
        roots,
    )
    n_files = len(files) + len(refused)
    if counted:
        unchecked = {path for path, _why in file_failures}
        for batch, _why in runner.run_failures:
            unchecked.update(batch)
        unchecked -= {f.path for f in counted}
        line = flagged_line(counted, len(unchecked), tool)
        if hides:
            note = one_line(" [the change also %s]" % " and ".join(hides), 110)
            line = one_line(line, RESULT_MAX - len(note)) + note
        say(line)
        return EXIT_FLAGGED
    if file_failures or runner.run_failures:
        raise StaticError(
            failed_text(tool, runner.run_failures, file_failures, n_files)
        )
    if hides:
        # The tool ran and nothing counted, but the change altered what the tool
        # reports. That is not a clean pass.
        say(
            "partial: %s"
            % one_line(
                "%s found nothing that counts in %d file(s), but the change %s; that can "
                "hide findings from this check, so a person should look"
                % (tool, n_files, " and ".join(hides))
            )
        )
        return args.error_exit
    say(ok_line(tool, total, n_files, codes, severities, args.added_lines_only))
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    error_exit = _prescan_error_exit(argv)
    parser = build_parser()
    parser.error_exit = error_exit
    try:
        args = parser.parse_args(argv)
        if 0 <= args.error_exit <= 255 and args.error_exit != EXIT_FLAGGED:
            error_exit = args.error_exit
        return run(parser, args)
    except StaticError as exc:
        say("error: %s" % one_line(exc))
        return error_exit
    except KeyboardInterrupt:
        say("error: interrupted")
        return error_exit
    except Exception as exc:  # noqa: BLE001 - a crash must not look like a finding
        say("error: internal error: %s: %s" % (type(exc).__name__, one_line(exc, 200)))
        return error_exit


if __name__ == "__main__":
    sys.exit(main())
