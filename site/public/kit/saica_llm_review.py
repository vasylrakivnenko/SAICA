#!/usr/bin/env python3
"""SAICA supervision kit: run a SAICA-Bench LLM reviewer prompt as a per-commit check.

Fills a reviewer prompt template with the change being committed and the task
text, sends it to an OpenAI-compatible chat-completions endpoint, parses the
JSON verdict the way SAICA-Bench does, and prints ONE result line, last on
stdout:

    flagged: <evidence>        exit 1    saica_check.py records `caught`
    ok: <reason>               exit 0    saica_check.py records `pass`
    skipped: <why>             exit 0    nothing to review (no change, or only
                                         files that are left out)
    partial: <what was read>   exit 127  part of the change was not reviewed and
                                         the part that was raised no finding
    error: <what went wrong>   exit 127  saica_check.py records `error`

A change that was not read in full is never reported as ``ok``. ``partial`` and
``error`` use exit 127, which saica_check.py records as ``error`` and never as
a finding; ``--error-exit N`` picks another code for use outside the kit runner.

Python 3.9+, standard library only. Copy to ``.saica/saica_llm_review.py`` and
call it from a ``command`` in ``.saica/checks.json``; see the kit README,
section "LLM reviewer checks".

Which change is reviewed:
  --diff-file PATH   a unified diff file (``-`` = stdin)
  --staged           ``git diff --cached``. Inside ``saica_check.py run --staged``
                     git is pointed at the snapshot's temporary index, so this is
                     exactly the change being committed.
  --commit REV       REV against its first parent (the empty tree for a root commit)
  (default)          --staged when SAICA_REPO_ROOT is set (saica_check's pre-commit
                     temporary checkout), otherwise --commit HEAD (CI, ``run --commit``,
                     manual runs).

What is sent:
  Not sent by default: the kit's own files (.saica/), node_modules/, lock files,
  minified files and binary files. A change that touches one of them was not
  reviewed in full, so the result is ``partial`` (or ``flagged``), never ``ok``.
  ``--exclude GLOB`` names paths you accept leaving out (no ``partial`` for
  those); ``--no-default-excludes`` sends everything. Source code and
  dependency manifests are sent first, other files after them. A diff longer
  than --max-diff-chars is cut at a file boundary; the result is then
  ``partial`` (or ``flagged``), never ``ok``.
  --context-lines N  lines of context in the git diff (SAICA-Bench fabrication: 15)
  --per-file         one request per changed file (SAICA-Bench fabrication
                     reviewed one file per request)
  --whole-file       the full new content of each changed file instead of its
                     diff (SAICA-Bench obsolescence and logic error reviewed
                     whole code); implies --per-file

Template placeholders (``{name}``; write literal braces as ``{{`` / ``}}`` as in
Python's str.format, so the benchmark prompts can be used verbatim):
  {issue} {task} {spec}    task text: --task-file, else $SAICA_TASK_FILE, else
                           .saica/task.md, else "(no task description provided)"
  {patch} {diff} {code}    the change (a diff, or file content with --whole-file)
  {context}                --context-file files, formatted as in SAICA-Bench
  --fill NAME=FILE         any other placeholder
A placeholder with no value, or a --fill file that is empty, is an error before
any request is made; ``--allow-empty NAME`` lets one stay empty on purpose. For
a Markdown prompt file the template is the first fenced code block.

Verdict cache: a ``flagged`` or ``ok`` answer is stored under a hash of the
model, the request settings and the complete filled prompt, and an identical
request is answered from the store without a call (the text then ends with
``(cached)``). Location: $SAICA_CACHE_DIR, else <repository>/.saica/cache/llm/.
A stored answer that is tracked by git or is a symlink is ignored, so a commit
cannot ship its own verdict. ``--no-cache`` turns the cache off.

Several --prompt files run in an UNTESTED combined mode: one request holding
every template, answered with one JSON object keyed by failure mode (the file
name stem); one result line per mode; exit 1 if any mode flagged, else the
error code if any answer was unreadable or the diff was cut, else 0.

The API base URL and key are read from the environment variables named by
--api-base-env / --api-key-env; the key is never printed, and the endpoint is
named in messages by host and port only.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

EXIT_OK = 0
EXIT_FLAGGED = 1
DEFAULT_ERROR_EXIT = 127
NO_TASK = "(no task description provided)"
DEFAULT_TASK_FILE = ".saica/task.md"
DEFAULT_MAX_TASK_CHARS = 20000  # SAICA-Bench cut issue text at 15k-20k characters
CONTEXT_MAX_CHARS = 15000  # SAICA-Bench: content[:15000] per context file
DEFAULT_MAX_DIFF_CHARS = 100000
DEFAULT_MAX_TOKENS = 16384  # SAICA-Bench default answer budget
DEFAULT_TIMEOUT_S = 240.0  # keep below the checks.json timeout_s (default 300)
DEFAULT_MAX_FILES = 20  # --per-file: requests per run
RESULT_MAX = 300
NOTES_MAX = 120
CACHE_VERSION = 2
KIT_VERSION = (
    "2026.11.21"  # part of the cache key: a new kit version never reuses old verdicts
)
CACHE_ENTRY_MAX_BYTES = 65536
COMBINED_WARNING = "combined review is not benchmarked; SAICA-Bench scores apply to one prompt per call"

TASK_KEYS = ("issue", "task", "spec")
DIFF_KEYS = ("patch", "diff", "code")
BUILTIN_KEYS = TASK_KEYS + DIFF_KEYS + ("context",)
EVIDENCE_KEYS = ("evidence", "reason", "explanation", "rationale")
# --text / --no-textconv / --no-ext-diff: a .gitattributes line (`*.py -diff`, a
# diff driver, a textconv filter) must not be able to hide a change from the reviewer.
_DIFF_ARGS = [
    "diff",
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--text",
    "--src-prefix=a/",
    "--dst-prefix=b/",
]
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}

# Paths left out of the review unless --no-default-excludes is given. A pattern
# that ends in "/" is a directory at any depth; any other pattern is matched
# (fnmatch) against the whole path and against the file name.
DEFAULT_EXCLUDES = (
    ".saica/",
    "node_modules/",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lockb",
    "poetry.lock",
    "Pipfile.lock",
    "uv.lock",
    "pdm.lock",
    "Cargo.lock",
    "composer.lock",
    "Gemfile.lock",
    "go.sum",
    "flake.lock",
    "*.lock",
    "*.min.js",
    "*.min.css",
    "*.map",
)
# Sent first, so that a cut at --max-diff-chars drops documentation and data
# before it drops code.
CODE_EXTENSIONS = frozenset(
    """.py .pyi .pyx .js .jsx .mjs .cjs .ts .tsx .mts .cts .vue .svelte .astro
    .go .rs .java .kt .kts .scala .groovy .c .h .cc .cpp .cxx .hpp .hh .m .mm .cs
    .fs .vb .rb .php .swift .dart .lua .pl .pm .r .jl .ex .exs .erl .hs .ml .clj
    .cljs .sh .bash .zsh .fish .ps1 .bat .cmd .sql .proto .graphql .tf .sol .zig
    .nim""".split()
)
CODE_NAMES = frozenset(
    ["Dockerfile", "Makefile", "Rakefile", "Jenkinsfile", "Gemfile", "Pipfile"]
)
_MANIFEST_RE = re.compile(
    r"^(requirements[^/]*\.(txt|in)|pyproject\.toml|setup\.cfg|package\.json|go\.mod"
    r"|Cargo\.toml|pom\.xml|build\.gradle|composer\.json)$"
)


class ReviewError(Exception):
    """A failure that is reported as ``error: ...`` with the error exit code."""


class SetupError(ReviewError):
    """The run cannot make any request (endpoint or key not configured)."""


# ---------------------------------------------------------------------------
# Output (every line passes through the key redactor)
# ---------------------------------------------------------------------------


class _Redactor:
    def __init__(self) -> None:
        self.secrets: List[str] = []

    def add(self, secret: Optional[str]) -> None:
        if not secret or len(secret) < 4:
            return
        for s in (secret, urllib.parse.quote(secret, safe="")):
            if s not in self.secrets:
                self.secrets.append(s)
        self.secrets.sort(key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "***")
        return text


REDACT = _Redactor()


def one_line(text: object, limit: int = RESULT_MAX) -> str:
    s = " ".join(str(text).split())
    if len(s) > limit:
        s = s[: limit - 3].rstrip() + "..."
    return s


def result_text(
    text: object,
    extras: Optional[List[str]] = None,
    notes: Optional[List[str]] = None,
    limit: int = RESULT_MAX,
) -> str:
    """One-line result text. ``extras`` become ``(extra)`` markers and ``notes`` a
    ``[note; note]`` block at the end; the main text is shortened to make room,
    so the markers and notes are never cut off."""
    tail = "".join(" (%s)" % e for e in (extras or []) if e)
    if notes:
        tail += " [%s]" % one_line("; ".join(notes), NOTES_MAX)
    room = max(40, limit - len(tail))
    return (one_line(text, room) + tail).strip()


def name_list(names: List[str], limit: int = 5) -> str:
    more = len(names) - limit
    return ", ".join(names[:limit]) + (" (+%d more)" % more if more > 0 else "")


def say(line: str) -> None:
    sys.stdout.write(REDACT(line) + "\n")
    sys.stdout.flush()


def warn(msg: str) -> None:
    sys.stderr.write(REDACT("saica-llm-review: warning: " + msg) + "\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Files and git
# ---------------------------------------------------------------------------


def _search_bases(prefer_repo_root: bool) -> List[Path]:
    cwd = Path.cwd()
    root = os.environ.get("SAICA_REPO_ROOT")
    if not root:
        return [cwd]
    return [Path(root), cwd] if prefer_repo_root else [cwd, Path(root)]


def find_file(name: str, prefer_repo_root: bool = False) -> Optional[Path]:
    """Resolve ``name``: absolute as is; relative against the current directory and
    $SAICA_REPO_ROOT (the real checkout during a pre-commit run)."""
    p = Path(name).expanduser()
    if p.is_absolute():
        return p if p.is_file() else None
    for base in _search_bases(prefer_repo_root):
        if (base / p).is_file():
            return base / p
    return None


def read_text(path: Path, what: str) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ReviewError("cannot read %s %s: %s" % (what, path, exc.strerror or exc))


def git(args: List[str], check: bool = True) -> str:
    try:
        proc = subprocess.run(
            ["git"] + args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise ReviewError("git is not installed or not on PATH")
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")
        raise ReviewError("git %s failed: %s" % (args[0], one_line(err, 200)))
    return proc.stdout.decode("utf-8", "replace")


def repo_root() -> Optional[Path]:
    """The real checkout: $SAICA_REPO_ROOT during a pre-commit run, else git's top level."""
    env = os.environ.get("SAICA_REPO_ROOT", "").strip()
    if env:
        return Path(env)
    try:
        top = git(["rev-parse", "--show-toplevel"], check=False).strip()
    except ReviewError:
        return None
    return Path(top) if top else None


def _diff_args(context_lines: Optional[int]) -> List[str]:
    args = list(_DIFF_ARGS)
    if context_lines is not None:
        args.append("-U%d" % context_lines)
    return args


def staged_diff(context_lines: Optional[int] = None) -> str:
    return git(_diff_args(context_lines) + ["--cached"])


def commit_diff(rev: str, context_lines: Optional[int] = None) -> Tuple[str, str]:
    """(diff of ``rev`` against its first parent, full sha of ``rev``)."""
    sha = git(
        ["rev-parse", "--verify", "--quiet", rev + "^{commit}"], check=False
    ).strip()
    if not sha:
        raise ReviewError("not a commit: %s" % rev)
    parents = git(["rev-list", "--parents", "-n", "1", sha]).split()
    if len(parents) > 1:
        base = parents[1]
    else:
        shallow = git(["rev-parse", "--git-path", "shallow"], check=False).strip()
        if (
            shallow
            and Path(shallow).is_file()
            and sha in read_text(Path(shallow), "file").split()
        ):
            raise ReviewError(
                "%s has no parent in this shallow clone; fetch more history "
                "(actions/checkout: fetch-depth: 0)" % sha[:12]
            )
        base = git(["mktree"]).strip()  # this repository's empty tree
    return git(_diff_args(context_lines) + [base, sha]), sha


class Change:
    """The change under review: where it comes from and its unified diff."""

    def __init__(self, kind: str, label: str, diff: str, rev: Optional[str] = None):
        self.kind = kind  # "staged" | "commit" | "file"
        self.label = label
        self.diff = diff
        self.rev = rev  # full sha when kind == "commit"


def obtain_change(args: argparse.Namespace) -> Change:
    if args.diff_file:
        if args.diff_file == "-":
            return Change("file", "stdin", sys.stdin.read())
        p = find_file(args.diff_file)
        if p is None:
            raise ReviewError("diff file not found: %s" % args.diff_file)
        return Change(
            "file", "diff file %s" % args.diff_file, read_text(p, "diff file")
        )
    if args.staged or (args.commit is None and os.environ.get("SAICA_REPO_ROOT")):
        return Change("staged", "staged changes", staged_diff(args.context_lines))
    rev = args.commit or "HEAD"
    diff, sha = commit_diff(rev, args.context_lines)
    return Change("commit", "commit %s" % rev, diff, sha)


def file_content(change: Change, path: str) -> Tuple[Optional[str], str]:
    """(new content of ``path`` in the reviewed tree, "") or (None, why not)."""
    if change.kind == "staged":
        spec = ":" + path
    else:
        spec = "%s:%s" % (change.rev, path)
    try:
        proc = subprocess.run(
            [
                "git",
                "cat-file",
                "blob",
                spec,
            ],  # the stored bytes: no filter, no textconv
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise ReviewError("git is not installed or not on PATH")
    if proc.returncode != 0:
        return None, "not in the reviewed tree"
    if b"\0" in proc.stdout[:8000]:
        return None, "binary"
    return proc.stdout.decode("utf-8", "replace"), ""


def load_task(args: argparse.Namespace) -> Tuple[str, bool]:
    """(task text, True) or (the "no task" sentence, False)."""
    # The task file usually stays untracked, so the real checkout is searched first.
    spec = args.task_file or os.environ.get("SAICA_TASK_FILE") or ""
    if spec:
        p = find_file(spec, prefer_repo_root=True)
        if p is None:
            raise ReviewError("task file not found: %s" % spec)
    else:
        p = find_file(DEFAULT_TASK_FILE, prefer_repo_root=True)
        if p is None:
            warn(
                "no task file (%s or $SAICA_TASK_FILE); the reviewer gets no task "
                "description" % DEFAULT_TASK_FILE
            )
            return NO_TASK, False
    text = read_text(p, "task file").strip()
    if not text:
        warn("task file %s is empty" % p)
        return NO_TASK, False
    if args.max_task_chars and len(text) > args.max_task_chars:
        warn("task text cut to %d characters (--max-task-chars)" % args.max_task_chars)
        text = text[: args.max_task_chars]
    return text, True


def load_context(specs: List[str]) -> str:
    parts = []
    for spec in specs:
        p = find_file(spec)
        if p is None:
            warn("context file not found, skipped: %s" % spec)
            continue
        content = read_text(p, "context file")[:CONTEXT_MAX_CHARS]
        parts.append(
            "\nRepository file (not changed by the patch): %s\n<file>\n%s\n</file>\n"
            % (spec, content)
        )
    return "".join(parts)


def load_fills(args: argparse.Namespace) -> Dict[str, str]:
    """Contents of the --fill files. An empty file is an error unless its
    placeholder is named by --allow-empty."""
    fills: Dict[str, str] = {}
    for item in args.fill:
        name, _sep, path = item.partition("=")
        fp = find_file(path)
        if fp is None:
            raise ReviewError("--fill file not found: %s" % path)
        text = read_text(fp, "--fill file")
        if not text.strip() and name not in args.allow_empty:
            raise ReviewError(
                "--fill %s=%s is empty: the prompt needs text for {%s} "
                "(--allow-empty %s sends it empty on purpose)"
                % (name, path, name, name)
            )
        fills[name] = text
    return fills


# ---------------------------------------------------------------------------
# The diff: per-file sections, what is left out, what comes first
# ---------------------------------------------------------------------------

_GIT_HEAD = "diff --git "
_HUNK_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_QUOTED_ESCAPES = {
    "n": 10,
    "t": 9,
    "r": 13,
    "a": 7,
    "b": 8,
    "f": 12,
    "v": 11,
    "\\": 92,
    '"': 34,
}


class Section:
    """The part of a unified diff that belongs to one file."""

    def __init__(
        self,
        path: Optional[str],
        text: str,
        binary: bool = False,
        deleted: bool = False,
    ) -> None:
        self.path = path  # new path (old path for a deletion); None = not a file
        self.text = text
        self.binary = binary
        self.deleted = deleted


def _unquote_git_path(p: str) -> str:
    """Undo git's C-style quoting of unusual file names ("a\\tb", "\\303\\274")."""
    if len(p) < 2 or p[0] != '"' or p[-1] != '"':
        return p
    body, out, i = p[1:-1], bytearray(), 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in _QUOTED_ESCAPES:
                out.append(_QUOTED_ESCAPES[nxt])
                i += 2
                continue
            m = re.match(r"[0-7]{1,3}", body[i + 1 : i + 4])
            if m:
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
                continue
        out.extend(ch.encode("utf-8", "replace"))
        i += 1
    return out.decode("utf-8", "replace")


def _header_path(raw: str, prefix: str) -> Optional[str]:
    """Path from a ``--- a/x`` / ``+++ b/x`` line (None for /dev/null)."""
    p = _unquote_git_path(raw.split("\t")[0].strip())
    if not p or p == "/dev/null":
        return None
    return p[len(prefix) :] if p.startswith(prefix) else p


def _git_head_path(line: str) -> Optional[str]:
    """New path from a ``diff --git a/x b/y`` line (used when no ---/+++ lines follow)."""
    rest = line[len(_GIT_HEAD) :].rstrip("\r")
    half = (len(rest) - 1) // 2
    if (  # the usual case, also with spaces in the name: a/<path> b/<path>
        len(rest) % 2 == 1
        and rest[half] == " "
        and rest.startswith("a/")
        and rest[half + 1 :].startswith("b/")
        and rest[2:half] == rest[half + 3 :]
    ):
        return rest[2:half]
    m = re.match(r'^("(?:[^"\\]|\\.)*"|\S+) ("(?:[^"\\]|\\.)*"|\S+)$', rest)
    if m:
        p = _unquote_git_path(m.group(2))
        return p[2:] if p.startswith("b/") else p
    return None


def _section(lines: List[str], text: str) -> Section:
    old = new = renamed = None
    binary = deleted = False
    for line in lines:
        if line.startswith("@@"):
            break
        if line.startswith("--- "):
            old = _header_path(line[4:], "a/")
        elif line.startswith("+++ "):
            new = _header_path(line[4:], "b/")
        elif line.startswith(("rename to ", "copy to ")):
            renamed = _unquote_git_path(line.split(" to ", 1)[1].strip())
        elif line.startswith("deleted file mode"):
            deleted = True
        elif line.startswith("GIT binary patch") or (
            line.startswith("Binary files ") and line.rstrip().endswith(" differ")
        ):
            binary = True
    path = renamed or new or old
    if path is None and lines and lines[0].startswith(_GIT_HEAD):
        path = _git_head_path(lines[0])
    if "\0" in text:
        binary = (
            True  # the diff is made with --text, so a binary file arrives as "lines"
        )
    return Section(path or "(unnamed file)", text, binary=binary, deleted=deleted)


def _classic_starts(lines: List[str]) -> List[int]:
    """Section starts of a diff without ``diff --git`` lines: a ``---`` line followed
    by a ``+++`` line. Hunk bodies are stepped over by their line counts, so a
    removed line that happens to read ``--- x`` is not taken for a header."""
    starts, i, n = [], 0, len(lines)
    while i < n:
        if not (
            lines[i].startswith("--- ")
            and i + 1 < n
            and lines[i + 1].startswith("+++ ")
        ):
            i += 1
            continue
        starts.append(i)
        i += 2
        while i < n:
            m = _HUNK_RE.match(lines[i])
            if not m:
                break
            old = int(m.group(1)) if m.group(1) is not None else 1
            new = int(m.group(2)) if m.group(2) is not None else 1
            i += 1
            while i < n and (old > 0 or new > 0 or lines[i].startswith("\\")):
                first = lines[i][:1]
                if first == "\\":
                    pass
                elif first == "-":
                    old -= 1
                elif first == "+":
                    new -= 1
                else:
                    old -= 1
                    new -= 1
                i += 1
    return starts


def split_diff(text: str) -> List[Section]:
    """Split a unified diff into per-file sections; joined again they give ``text``."""
    if not text.strip():
        return []
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if ln.startswith(_GIT_HEAD)]
    if not starts:
        starts = _classic_starts(lines)
    if not starts:
        return [Section(None, text)]  # not a diff we can split: one unnamed part
    sections: List[Section] = []
    if starts[0] > 0 and "".join(lines[: starts[0]]).strip():
        # text in front of the first file (a commit message from `git show`)
        sections.append(Section(None, "\n".join(lines[: starts[0]]) + "\n"))
    bounds = starts + [len(lines)]
    for k, start in enumerate(starts):
        chunk = lines[start : bounds[k + 1]]
        last = k == len(starts) - 1
        sections.append(_section(chunk, "\n".join(chunk) + ("" if last else "\n")))
    return sections


def path_matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return ("/" + pattern) in ("/" + path)
    base = path.rsplit("/", 1)[-1]
    return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(base, pattern)


def is_code_path(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return (
        os.path.splitext(base)[1].lower() in CODE_EXTENSIONS
        or base in CODE_NAMES
        or bool(_MANIFEST_RE.match(base))
    )


def select_sections(
    sections: List[Section], excludes: List[str], defaults: bool
) -> Tuple[List[Section], List[str], List[str]]:
    """(sections to review: code and dependency manifests first, then the rest,
    path order kept inside each group; every path that was left out; the ones
    among them that nobody asked to leave out).

    A path matched by a user's ``--exclude`` is left out on request. A path
    matched only by the built-in list, or a binary file, is left out because the
    reviewer cannot usefully read it: the change was then not reviewed in full,
    and the result must say so (``partial``), or a change could hide in
    ``vendor.min.js`` or a ``.lock`` file and still come back ``ok``.
    """
    kept: List[Section] = []
    left: List[str] = []
    unasked: List[str] = []
    for s in sections:
        if s.path is None:
            kept.append(s)
        elif any(path_matches(s.path, p) for p in excludes):
            left.append(s.path)
        elif defaults and (
            s.binary or any(path_matches(s.path, p) for p in DEFAULT_EXCLUDES)
        ):
            left.append(s.path)
            unasked.append(s.path)
        else:
            kept.append(s)
    kept.sort(key=lambda s: 0 if s.path is None or is_code_path(s.path) else 1)
    return kept, left, unasked


UNASKED_HINT = "name a path with --exclude to accept leaving it out"


def left_out_note(paths: List[str]) -> str:
    return "%d file%s left out: %s" % (
        len(paths),
        "" if len(paths) == 1 else "s",
        name_list(paths, 3),
    )


def fit_sections(
    sections: List[Section], limit: int
) -> Tuple[str, int, int, List[str]]:
    """(text to send, characters of the diff in it, characters in all, what is not
    in it). The cut falls on a file boundary; only when the first file alone is
    over the limit is that file cut."""
    total = sum(len(s.text) for s in sections)
    if not limit or total <= limit:
        return "".join(s.text for s in sections), total, total, []
    kept: List[Section] = []
    size = 0
    for s in sections:
        if size + len(s.text) > limit:
            break
        kept.append(s)
        size += len(s.text)
    rest = [s.path or "(text before the first file)" for s in sections[len(kept) :]]
    if kept:
        text = "".join(s.text for s in kept)
        if not text.endswith("\n"):
            text += "\n"
        text += "[diff truncated: %d of %d files shown, %d of %d characters]\n" % (
            len(kept),
            len(sections),
            size,
            total,
        )
        return text, size, total, rest
    first = sections[0]
    text = first.text[:limit] + (
        "\n[diff truncated: %d of %d characters shown]\n" % (limit, total)
    )
    rest[0] = "the rest of %s" % (first.path or "the diff")
    return text, limit, total, rest


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_FENCE_OPEN_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
_TOKEN_RE = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FLAG_SPEC_RE = re.compile(
    r"\"([A-Za-z_][\w-]*)\"\s*:\s*<?\s*(?:true|false)\s*(?:or|\||/)\s*(?:true|false)",
    re.I,
)


def first_fenced_block(text: str) -> Optional[str]:
    """Content of the first ``` / ~~~ fenced block (CommonMark rules), or None."""
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    for i, line in enumerate(lines):
        m = _FENCE_OPEN_RE.match(line)
        if not m or (m.group(2)[0] == "`" and "`" in m.group(3)):
            continue
        indent, fence = len(m.group(1)), m.group(2)
        close = re.compile(r"^ {0,3}%s{%d,}[ \t]*$" % (re.escape(fence[0]), len(fence)))
        body = []
        for inner in lines[i + 1 :]:
            if close.match(inner):
                break
            strip = min(indent, len(inner) - len(inner.lstrip(" ")))
            body.append(inner[strip:])
        return "\n".join(body)
    return None


class Prompt:
    def __init__(self, path: str, mode: str, template: str) -> None:
        self.path = path
        self.mode = mode
        self.template = template


def load_prompt(spec: str) -> Prompt:
    p = find_file(spec)
    if p is None:
        raise ReviewError("prompt file not found: %s" % spec)
    text = read_text(p, "prompt file")
    if p.suffix.lower() in (".md", ".markdown"):
        block = first_fenced_block(text)
        if block is None:
            warn("%s has no fenced code block; using the whole file" % spec)
        else:
            text = block
    if not text.strip():
        raise ReviewError("prompt template %s is empty" % spec)
    return Prompt(spec, p.stem, text)


def placeholder_names(template: str) -> List[str]:
    """The ``{name}`` placeholders of a template, in order of first use."""
    names: List[str] = []
    for m in _TOKEN_RE.finditer(template):
        if m.group(1) and m.group(1) not in names:
            names.append(m.group(1))
    return names


def check_templates(
    prompts: List[Prompt], fills: Dict[str, str], allow_empty: List[str]
) -> None:
    """Refuse, before any request, a template that would be sent with a hole in it."""
    for pr in prompts:
        names = placeholder_names(pr.template)
        missing = [
            n
            for n in names
            if n not in BUILTIN_KEYS and n not in fills and n not in allow_empty
        ]
        if missing:
            raise ReviewError(
                "%s needs --fill NAME=FILE for %s (or --allow-empty NAME to send "
                "it empty on purpose)"
                % (pr.path, ", ".join("{%s}" % n for n in missing))
            )
        if not set(names) & set(DIFF_KEYS) and not any(n in fills for n in names):
            raise ReviewError(
                "%s has no {patch} / {diff} / {code} placeholder and nothing is "
                "given with --fill: the change would not be sent to the reviewer"
                % pr.path
            )
    used = {n for pr in prompts for n in placeholder_names(pr.template)}
    for name in fills:
        if name not in used:
            warn("--fill %s is not used by any prompt template" % name)


def fill_template(template: str, values: Dict[str, str]) -> Tuple[str, List[str]]:
    """Replace ``{name}`` placeholders. ``{{`` / ``}}`` become literal braces when the
    template uses that escaping (it contains ``{{``); otherwise braces are left alone.
    """
    escapes = "{{" in template
    unknown: List[str] = []

    def repl(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name is None:
            return m.group(0)[0] if escapes else m.group(0)
        if name in values:
            return values[name]
        if name not in unknown:
            unknown.append(name)
        return ""

    return _TOKEN_RE.sub(repl, template), unknown


def detect_flag_field(template: str) -> Optional[str]:
    """The answer field the template asks to be true/false (last one wins)."""
    skeleton, _ = fill_template(template, {})
    found = _FLAG_SPEC_RE.findall(skeleton)
    return found[-1] if found else None


def build_combined(prompts: List[Prompt], filled: List[str]) -> str:
    modes = [p.mode for p in prompts]
    skeleton = "{" + ", ".join('"%s": {...}' % m for m in modes) + "}"
    parts = [
        "You are running %d independent reviews of the same change, one per failure "
        "mode. Each section below is a complete review task with its own question and "
        "its own JSON answer format. Judge every section on its own, as if it were the "
        "only one.\n\nAnswer with ONE JSON object only, keyed by failure mode; each value "
        "is the JSON object that section asks for:\n%s" % (len(modes), skeleton)
    ]
    for p, text in zip(prompts, filled):
        parts.append("## Failure mode: %s\n\n%s" % (p.mode, text.strip()))
    parts.append(
        "Final answer: ONE JSON object keyed by failure mode (%s); each value is that "
        "section's answer object." % ", ".join(modes)
    )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Answer parsing (as in SAICA-Bench, bench/common.py parse_verdict: the text
# after </think>, then the last JSON object that has the flag field)
# ---------------------------------------------------------------------------


def _after_think(text: str) -> str:
    return text.split("</think>")[-1]


def json_objects_from_end(text: str) -> Iterator[dict]:
    dec = json.JSONDecoder()
    for m in reversed(list(re.finditer(r"\{", text))):
        try:
            obj, _end = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


def _first_bool_key(obj: dict) -> Optional[str]:
    for k, v in obj.items():
        if isinstance(v, bool):
            return k
    return None


def find_verdict(
    text: str, field: Optional[str]
) -> Tuple[Optional[dict], Optional[str]]:
    """(verdict object, field) of an answer.

    SAICA-Bench (bench/common.py parse_verdict) takes the LAST JSON object that
    has the field. The kit is deliberately stricter in one case: when several
    objects have the field and ANY of them says true, the answer counts as
    flagged. An answer that says true and then quotes ``{"field": false}`` from
    the change under review must not come back ok. With one verdict object, the
    usual case, both rules agree.
    """
    body = _after_think(text)
    last: Optional[Tuple[dict, str]] = None
    for obj in json_objects_from_end(body):
        key = (
            _first_bool_key(obj) if field is None else (field if field in obj else None)
        )
        if key is None:
            continue
        if obj.get(key) is True:
            return obj, key
        if last is None:
            last = (obj, key)
    if last is not None:
        return last
    if field:
        # An answer cut before its object closed: `"field": true|false` in the
        # text; true wins, else the last one. An echo of the prompt's own
        # template (`true or false`, `true|false`) is not a verdict.
        hits = re.findall(
            r"\"%s\"\s*:\s*(true|false)\b(?!\s*(?:or\b|\|))" % re.escape(field), body
        )
        if hits:
            return {field: "true" in hits, "evidence": "(partial parse)"}, field
    return None, field


def evidence_text(obj: dict, field: str) -> str:
    main, used = "", None
    for k in EVIDENCE_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            main, used = v.strip(), k
            break
    extras = []
    for k, v in obj.items():
        if k in (field, used) or isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (str, int, float)) and str(v).strip():
            extras.append("%s=%s" % (k, v))
    if extras:
        main = (main + " " if main else "") + "(" + ", ".join(extras) + ")"
    return main


def judge(
    obj: Optional[dict], field: Optional[str], answer: str, finish: object
) -> Tuple[str, str]:
    """Return (status, text); status is flagged | ok | unreadable."""
    if obj is None or field is None:
        why = "no JSON verdict%s found in the answer" % (
            " with %r" % field if field else ""
        )
        if finish == "length":
            why += " (it stopped at the token limit; raise --max-tokens)"
        tail = one_line(_after_think(answer)[-160:], 160)
        return "unreadable", why + (": ...%s" % tail if tail else " (empty answer)")
    value = obj.get(field)
    if value is True:
        return (
            "flagged",
            evidence_text(obj, field) or "(no evidence given; %s=true)" % field,
        )
    if value is False:
        ev = evidence_text(obj, field)
        return "ok", "%s=false" % field + (" - " + ev if ev else "")
    return "unreadable", "%r is %s, not true/false" % (
        field,
        one_line(json.dumps(value), 60),
    )


def combined_verdicts(
    text: str, prompts: List[Prompt], fields: Dict[str, Optional[str]], finish: object
) -> List[Tuple[str, str, str]]:
    modes = [p.mode for p in prompts]
    top = None
    for obj in json_objects_from_end(_after_think(text)):
        if any(isinstance(obj.get(m), dict) for m in modes):
            top = obj
            break
    out = []
    for mode in modes:
        if top is None:
            status, msg = judge(None, fields[mode] or mode, text, finish)
            out.append((mode, status, msg))
            continue
        value = top.get(mode)
        if isinstance(value, bool):
            status, msg = judge({mode: value}, mode, text, finish)
        elif isinstance(value, dict):
            field = fields[mode]
            if field is None:
                field = mode if mode in value else _first_bool_key(value)
            status, msg = judge(value, field, text, finish)
        else:
            status, msg = (
                "unreadable",
                "no answer for %s in the combined JSON object" % mode,
            )
        out.append((mode, status, msg))
    return out


# ---------------------------------------------------------------------------
# Verdict cache (one small JSON file per request; never a failed answer)
# ---------------------------------------------------------------------------


def cache_key(
    args: argparse.Namespace, flag_field: object, prompt: str, endpoint: str = ""
) -> str:
    """sha256 over everything that decides the answer to a request: the kit
    version, the endpoint (another server is another reviewer), the model, the
    request settings and the complete prompt."""
    payload = json.dumps(
        {
            "v": CACHE_VERSION,
            "kit": KIT_VERSION,
            "endpoint": endpoint,
            "api_version": args.api_version,
            "stream": bool(args.stream),
            "model": args.model,
            "api_style": args.api_style,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "extra_body": args.extra_body,
            "flag_field": flag_field,
            "prompt": prompt,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()


class VerdictCache:
    def __init__(self, directory: Optional[Path], root: Optional[Path]) -> None:
        self.dir = directory  # None = cache off
        self.root = root
        self._warned: Set[str] = set()

    @classmethod
    def for_run(cls, args: argparse.Namespace) -> "VerdictCache":
        if args.no_cache or args.dry_run:
            return cls(None, None)
        root = repo_root()
        env = os.environ.get("SAICA_CACHE_DIR", "").strip()
        if env:
            d = Path(env).expanduser()
            if not d.is_absolute():
                d = (root or Path.cwd()) / d
            return cls(d, root)
        if root is None:
            return cls(None, None)  # no repository and no $SAICA_CACHE_DIR
        return cls(root / ".saica" / "cache" / "llm", root)

    def _warn_once(self, msg: str) -> None:
        if msg not in self._warned:
            self._warned.add(msg)
            warn(msg)

    def _tracked(self, path: Path) -> bool:
        """True when ``path`` is a file of the checked tree (in git's index)."""
        if self.root is None:
            return False
        try:
            rel = os.path.relpath(
                os.path.realpath(str(path)), os.path.realpath(str(self.root))
            )
        except ValueError:  # another drive (Windows)
            return False
        if rel == os.pardir or rel.startswith(os.pardir + os.sep):
            return False
        try:
            proc = subprocess.run(
                [
                    "git",
                    "ls-files",
                    "--error-unmatch",
                    "--",
                    ":(top)" + rel.replace(os.sep, "/"),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        return proc.returncode == 0

    def get(self, key: str) -> Optional[dict]:
        if self.dir is None:
            return None
        path = self.dir / (key + ".json")
        try:
            if path.is_symlink():
                self._warn_once(
                    "ignored a cached verdict that is a symlink: %s" % path.name
                )
                return None
            if not path.is_file():
                return None
            if path.stat().st_size > CACHE_ENTRY_MAX_BYTES:
                return None
            if self._tracked(path):
                self._warn_once(
                    "ignored a cached verdict that is tracked by git (%s); a commit "
                    "must not ship its own verdict. Remove it from the repository "
                    "and gitignore .saica/cache/" % path.name
                )
                return None
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self._warn_once("verdict cache not readable (%s): %s" % (self.dir, exc))
            return None
        if not isinstance(entry, dict) or entry.get("v") != CACHE_VERSION:
            return None
        return entry

    def put(self, key: str, entry: dict) -> None:
        if self.dir is None:
            return
        record = {"v": CACHE_VERSION}
        record.update(entry)
        record["created"] = _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        tmp = None
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            ignore = self.dir / ".gitignore"
            if not ignore.exists():  # keep the store out of `git add -A`
                ignore.write_text("*\n", encoding="utf-8")
            fd, tmp = tempfile.mkstemp(
                prefix=".tmp-", suffix=".json", dir=str(self.dir)
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            os.replace(tmp, str(self.dir / (key + ".json")))
            tmp = None
        except OSError as exc:
            self._warn_once(
                "verdict cache not written (%s): %s" % (self.dir, exc.strerror or exc)
            )
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# HTTP (urllib; no redirects, loopback never proxied)
# ---------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None  # a redirect would resend the key to another URL: fail instead


def _split_base(base: str) -> Tuple[urllib.parse.SplitResult, str, Optional[int]]:
    """(parts, host, port) of the API base URL; ReviewError when it is not usable."""
    parts = urllib.parse.urlsplit(base.strip())
    try:
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ReviewError("the API base URL has a port that is not a number")
    if parts.scheme not in ("http", "https") or not host:
        raise ReviewError("the API base URL must start with http:// or https://")
    return parts, host, port


def _host_port(host: str, port: Optional[int]) -> str:
    name = "[%s]" % host if ":" in host else host
    return "%s:%d" % (name, port) if port else name


def is_loopback(host: str) -> bool:
    h = host.strip("[]").lower()
    if h == "localhost" or h.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def endpoint_url(base: str, api_version: Optional[str]) -> str:
    """The chat-completions URL. Credentials written into the base URL
    (user:password@host) are dropped: they are never sent and never printed."""
    parts, host, port = _split_base(base)
    path = parts.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if api_version and not any(k == "api-version" for k, _v in query):
        query.append(("api-version", api_version))
    return urllib.parse.urlunsplit(
        (parts.scheme, _host_port(host, port), path, urllib.parse.urlencode(query), "")
    )


def endpoint_name(url: str) -> str:
    """``host[:port]`` of a URL, for messages. Never the userinfo."""
    try:
        _parts, host, port = _split_base(url)
    except ReviewError:
        return "the endpoint"
    return _host_port(host, port)


def note_base_url(base: str, key_env: str) -> None:
    """Register credentials found in the base URL with the redactor and warn about
    them and about plain http:// to another machine."""
    if not base:
        return
    try:
        parts, host, _port = _split_base(base)
    except ReviewError:
        return  # reported when the endpoint is needed
    if "@" in parts.netloc:
        userinfo = parts.netloc.rsplit("@", 1)[0]
        password = userinfo.partition(":")[2]
        for secret in (userinfo, password, urllib.parse.unquote(password)):
            REDACT.add(secret)
        warn(
            "the API base URL has a user name or password in it; they are not sent "
            "and not printed. Put the key in the variable named by --api-key-env%s"
            % (" (%s)" % key_env if key_env else "")
        )
    if parts.scheme == "http" and not is_loopback(host):
        warn(
            "the API base URL is plain http:// to %s: the key and the diff travel "
            "unencrypted" % host
        )


def _ssl_context() -> ssl.SSLContext:
    """System trust store; if SSL_CERT_FILE is unset and certifi is installed, also trust its bundle.
    (python.org and uv-managed Pythons on macOS often ship without a usable system CA path.)
    """
    ctx = ssl.create_default_context()
    if not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi  # optional; not required by the kit

            ctx.load_verify_locations(certifi.where())
        except (
            Exception
        ):  # noqa: BLE001 - certifi missing or unreadable: keep the system store
            pass
    return ctx


def _opener(host: str) -> urllib.request.OpenerDirector:
    handlers: list = [
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=_ssl_context()),
    ]
    if host.lower() in _LOOPBACK or is_loopback(host):
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def _http_error_text(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(2000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - best effort only
        raw = ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            raw = (
                err.get("message", json.dumps(err))
                if isinstance(err, dict)
                else str(err)
            )
    except ValueError:
        pass
    return one_line(raw or exc.reason, 200)


def collect_stream(resp, deadline: float) -> dict:  # type: ignore[no-untyped-def]
    """Assemble an SSE chat-completions stream into the non-streamed JSON shape."""
    parts: List[str] = []
    finish = None
    usage: dict = {}
    for raw in resp:  # binary line iteration splits on b"\n" only
        if time.monotonic() > deadline:
            raise ReviewError("timed out while reading the streamed answer")
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            ev = json.loads(data)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("error"):
            raise ReviewError(
                "the API reported an error mid-stream: %s" % one_line(ev["error"], 200)
            )
        if ev.get("usage"):
            usage = ev["usage"]
        for ch in ev.get("choices") or []:
            delta = ch.get("delta") or {}
            if isinstance(delta.get("content"), str):
                parts.append(delta["content"])
            finish = ch.get("finish_reason") or finish
    return {
        "choices": [{"message": {"content": "".join(parts)}, "finish_reason": finish}],
        "usage": usage,
    }


def _read_response(resp, stream: bool, deadline: float) -> dict:  # type: ignore[no-untyped-def]
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "text/event-stream" in ctype or (stream and "json" not in ctype):
        return collect_stream(resp, deadline)
    raw = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        raise ReviewError(
            "the API returned a non-JSON response: %s" % one_line(raw, 160)
        )


def call_model(
    args: argparse.Namespace,
    prompt: str,
    base: str,
    key: str,
    deadline: Optional[float] = None,
) -> dict:
    """One chat-completions request (with retries). ``deadline`` (time.monotonic)
    is the end of the run's time budget; default: --timeout from now."""
    url = endpoint_url(base, args.api_version)
    host = endpoint_name(url)
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if args.stream else "application/json",
        "User-Agent": "saica-llm-review/1",
    }
    if key:
        if args.api_style == "azure":
            headers["api-key"] = key
        else:
            headers["Authorization"] = "Bearer " + key
    body: dict = {
        "model": args.model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if args.max_tokens:
        field = "max_completion_tokens" if args.api_style == "azure" else "max_tokens"
        body[field] = args.max_tokens
    if args.temperature is not None:
        body["temperature"] = args.temperature
    if args.stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    body.update(args.extra_body)
    data = json.dumps(body).encode("utf-8")
    opener = _opener(urllib.parse.urlsplit(url).hostname or "")
    if deadline is None:
        deadline = time.monotonic() + args.timeout
    last = ""
    attempts = 0
    for attempt in range(args.retries + 1):
        remaining = deadline - time.monotonic()
        if remaining < 1:
            break
        attempts += 1
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with opener.open(req, timeout=remaining) as resp:
                return _read_response(resp, args.stream, deadline)
        except urllib.error.HTTPError as exc:
            detail = _http_error_text(exc)
            if exc.code == 400 and "content_filter" in detail.lower():
                raise ReviewError(
                    "the provider's content filter refused the prompt (HTTP 400)"
                )
            last = "HTTP %d from %s: %s" % (exc.code, host, detail)
            if exc.code != 429 and exc.code < 500:
                raise ReviewError(last)
        except (
            urllib.error.URLError,
            socket.timeout,
            http.client.HTTPException,
            OSError,
        ) as exc:
            reason = getattr(exc, "reason", None) or exc
            last = "%s: %s" % (host, one_line(reason, 160))
        if attempt < args.retries:
            pause = min(5.0 * (attempt + 1), deadline - time.monotonic() - 1)
            if pause > 0:
                time.sleep(pause)
    raise ReviewError(
        "model call failed after %d attempt(s) within %gs: %s"
        % (attempts, args.timeout, last or "no time left")
    )


def answer_of(resp: object) -> Tuple[str, object, object]:
    if not isinstance(resp, dict):
        raise ReviewError("unexpected API response (not a JSON object)")
    if resp.get("error"):
        raise ReviewError("API error: %s" % one_line(json.dumps(resp["error"]), 200))
    choices = resp.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise ReviewError("the API response has no choices")
    msg = choices[0].get("message") or {}
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):  # content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    finish = choices[0].get("finish_reason")
    if finish == "content_filter" and not content:
        raise ReviewError("the provider's content filter withheld the answer")
    return content if isinstance(content, str) else "", finish, resp.get("usage")


class Session:
    """What every request of one run shares: endpoint, time budget, verdict cache."""

    def __init__(self, args: argparse.Namespace, base: str, key: str) -> None:
        self.args = args
        self.base = base
        self.key = key
        self.deadline = time.monotonic() + args.timeout
        try:  # the URL requests go to, without credentials; "" when not configured
            self.endpoint = endpoint_url(base, args.api_version) if base else ""
        except ReviewError:
            self.endpoint = ""
        self.cache = VerdictCache.for_run(args)
        self.requests = 0
        self.unasked: List[str] = []  # changed files left out by the built-in list

    def time_left(self) -> float:
        return self.deadline - time.monotonic()

    def require_endpoint(self) -> None:
        args = self.args
        if not self.base:
            raise SetupError(
                "environment variable %s (API base URL) is not set" % args.api_base_env
            )
        if args.api_key_env and not self.key:
            raise SetupError(
                "environment variable %s (API key) is not set" % args.api_key_env
            )

    def _answer(self, prompt: str) -> Tuple[str, object]:
        self.require_endpoint()
        self.requests += 1
        resp = call_model(self.args, prompt, self.base, self.key, self.deadline)
        answer, finish, usage = answer_of(resp)
        if self.args.verbose:
            warn(
                "finish_reason=%s usage=%s" % (finish, one_line(json.dumps(usage), 200))
            )
        return answer, finish

    def ask(self, prompt: str, field: Optional[str]) -> Tuple[str, str, bool]:
        """(status, text, answered from the cache) for one single-prompt request."""
        ckey = cache_key(self.args, field, prompt, self.endpoint)
        hit = self.cache.get(ckey)
        if (
            hit is not None
            and hit.get("status") in ("flagged", "ok")
            and isinstance(hit.get("text"), str)
        ):
            return hit["status"], hit["text"], True
        answer, finish = self._answer(prompt)
        obj, found = find_verdict(answer, field)
        status, text = judge(obj, found, answer, finish)
        if status in ("flagged", "ok"):
            self.cache.put(ckey, {"status": status, "text": REDACT(text)})
        return status, text, False

    def ask_combined(
        self, prompt: str, prompts: List[Prompt], fields: Dict[str, Optional[str]]
    ) -> Tuple[List[Tuple[str, str, str]], bool]:
        """([(mode, status, text)], answered from the cache) for a combined request."""
        modes = [p.mode for p in prompts]
        ckey = cache_key(
            self.args, {m: fields[m] for m in modes}, prompt, self.endpoint
        )
        hit = self.cache.get(ckey)
        rows = hit.get("results") if hit is not None else None
        if (
            isinstance(rows, list)
            and len(rows) == len(modes)
            and all(
                isinstance(r, list)
                and len(r) == 3
                and r[0] == m
                and r[1] in ("flagged", "ok")
                and isinstance(r[2], str)
                for r, m in zip(rows, modes)
            )
        ):
            return [(r[0], r[1], r[2]) for r in rows], True
        answer, finish = self._answer(prompt)
        results = combined_verdicts(answer, prompts, fields, finish)
        if all(s in ("flagged", "ok") for _m, s, _t in results):
            self.cache.put(
                ckey, {"results": [[m, s, REDACT(t)] for m, s, t in results]}
            )
        return results, False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    error_exit = DEFAULT_ERROR_EXIT

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        say("error: bad arguments: %s" % message)
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
        prog="saica_llm_review.py",
        description=(
            "Run a SAICA-Bench LLM reviewer prompt on the change being committed. "
            "Prints one result line, last on stdout: 'flagged: ...' (exit 1), "
            "'ok: ...' or 'skipped: ...' (exit 0), 'partial: ...' or 'error: ...' "
            "(exit 127, which saica_check.py records as 'error'). A change that "
            "was not read in full is never reported as ok."
        ),
    )
    p.add_argument(
        "--prompt",
        action="append",
        required=True,
        metavar="PATH",
        help="prompt template (.md: first fenced code block; else the whole file). "
        "Repeat for the UNTESTED combined mode (one request, one line per mode)",
    )
    p.add_argument("--model", help="model / deployment id (required unless --dry-run)")
    p.add_argument(
        "--api-style",
        choices=("openai", "azure"),
        default="openai",
        help="openai: Authorization: Bearer + max_tokens; azure: api-key header + "
        "max_completion_tokens (default: openai)",
    )
    p.add_argument(
        "--api-base-env",
        default="SAICA_LLM_API_BASE",
        metavar="NAME",
        help="environment variable holding the API base URL, e.g. "
        "https://host/v1 (default: SAICA_LLM_API_BASE)",
    )
    p.add_argument(
        "--api-key-env",
        default="SAICA_LLM_API_KEY",
        metavar="NAME",
        help="environment variable holding the API key; '' sends no key "
        "(default: SAICA_LLM_API_KEY)",
    )
    p.add_argument(
        "--api-version",
        metavar="VER",
        help="add ?api-version=VER (classic Azure OpenAI deployment URLs)",
    )
    p.add_argument(
        "--temperature",
        type=float,
        help="sampling temperature (default: not sent, i.e. the provider default)",
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        metavar="N",
        help="answer token budget; 0 = not sent, e.g. for models that take another "
        "field: add it with --extra-body (default: %d)" % DEFAULT_MAX_TOKENS,
    )
    p.add_argument(
        "--stream",
        action="store_true",
        help="stream the answer (needed for long answers behind proxies "
        "with ~100 s limits, e.g. Hyperbolic)",
    )
    p.add_argument(
        "--extra-body",
        default="{}",
        metavar="JSON",
        help='JSON object merged into the request, e.g. \'{"reasoning_effort": "low"}\'',
    )
    p.add_argument(
        "--flag-field",
        default="auto",
        metavar="NAME",
        help="answer field that means flagged (default auto: the field the template "
        "asks to be 'true or false', else the first boolean field)",
    )
    p.add_argument(
        "--task-file",
        metavar="PATH",
        help="task / issue text (default: $SAICA_TASK_FILE, else %s)"
        % DEFAULT_TASK_FILE,
    )
    p.add_argument(
        "--context-file",
        action="append",
        default=[],
        metavar="PATH",
        help="repository file shown to the reviewer as {context} (repeatable)",
    )
    p.add_argument(
        "--fill",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="fill placeholder {NAME} with the contents of PATH (repeatable). A "
        "placeholder with no value, or an empty file, is an error before any request",
    )
    p.add_argument(
        "--allow-empty",
        action="append",
        default=[],
        metavar="NAME",
        help="let placeholder {NAME} stay empty on purpose (repeatable)",
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="leave matching files out of the review on purpose (repeatable; fnmatch "
        "on the path and on the file name; a pattern ending in / is a directory). "
        "Files the built-in list leaves out (.saica/, node_modules/, lock files, "
        "minified files, binary files) make the result partial unless a pattern "
        "given here names them",
    )
    p.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="do not use the built-in list of left-out files",
    )
    p.add_argument(
        "--context-lines",
        type=int,
        metavar="N",
        help="lines of context around each change in the git diff (default: git's, "
        "3). The SAICA-Bench fabrication reviewer saw 15: use --per-file "
        "--context-lines 15 with that prompt. Not with --diff-file",
    )
    p.add_argument(
        "--per-file",
        action="store_true",
        help="one request per changed file, each holding only that file's diff (the "
        "SAICA-Bench fabrication reviewer saw one file per request). flagged if "
        "any file is flagged; partial if a file could not be reviewed",
    )
    p.add_argument(
        "--whole-file",
        action="store_true",
        help="send the full new content of each changed file instead of its diff "
        "(the SAICA-Bench obsolescence and logic-error reviewers saw whole code, "
        "not diffs). Implies --per-file; deleted files are skipped. Not with "
        "--diff-file",
    )
    p.add_argument(
        "--max-files",
        type=int,
        default=DEFAULT_MAX_FILES,
        metavar="N",
        help="--per-file: at most N requests per run; more changed files make the "
        "result partial (default: %d)" % DEFAULT_MAX_FILES,
    )
    p.add_argument(
        "--max-diff-chars",
        type=int,
        default=DEFAULT_MAX_DIFF_CHARS,
        metavar="N",
        help="send at most N characters of the diff (with --per-file: of each "
        "file); what does not fit is not reviewed and the result is partial, "
        "never ok; 0 = no limit (default: %d)" % DEFAULT_MAX_DIFF_CHARS,
    )
    p.add_argument(
        "--max-task-chars",
        type=int,
        default=DEFAULT_MAX_TASK_CHARS,
        metavar="N",
        help="cut the task text after N characters; 0 = no limit (default: %d)"
        % DEFAULT_MAX_TASK_CHARS,
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--diff-file", metavar="PATH", help="review this unified diff (- = stdin)"
    )
    src.add_argument("--staged", action="store_true", help="review git diff --cached")
    src.add_argument(
        "--commit", metavar="REV", help="review REV against its first parent"
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="do not read or write the verdict cache ($SAICA_CACHE_DIR, else "
        "<repository>/.saica/cache/llm/)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        metavar="S",
        help="total seconds for the run, retries and every --per-file request "
        "included; keep it below the checks.json timeout_s (default: %g)"
        % DEFAULT_TIMEOUT_S,
    )
    p.add_argument(
        "--retries",
        type=int,
        default=2,
        metavar="N",
        help="retries on HTTP 429 / 5xx / connection errors (default: 2)",
    )
    p.add_argument(
        "--error-exit",
        type=int,
        default=DEFAULT_ERROR_EXIT,
        metavar="N",
        help="exit code for 'error' and 'partial' (default: 127, which every "
        "version of saica_check.py records as 'error', never as a finding)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the filled prompt(s) and exit 0 without calling the API",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="report diff source, left-out files, prompt size and token usage on stderr",
    )
    return p


def _check_args(p: _Parser, args: argparse.Namespace) -> None:
    if not args.dry_run and not args.model:
        p.error("--model is required (unless --dry-run)")
    if (
        args.timeout <= 0
        or args.retries < 0
        or args.max_diff_chars < 0
        or args.max_task_chars < 0
    ):
        p.error("--timeout must be > 0 and --retries / --max-*-chars >= 0")
    if not 0 <= args.error_exit <= 255 or args.error_exit == EXIT_FLAGGED:
        p.error("--error-exit must be 0 or 2..255 (1 means flagged)")
    try:
        extra = json.loads(args.extra_body)
    except ValueError as exc:
        p.error("--extra-body is not valid JSON: %s" % exc)
    if not isinstance(extra, dict):
        p.error("--extra-body must be a JSON object")
    args.extra_body = extra
    for item in args.fill:
        name, sep, _path = item.partition("=")
        if not sep or not _NAME_RE.match(name):
            p.error("--fill expects NAME=PATH, got %r" % item)
    for name in args.allow_empty:
        if not _NAME_RE.match(name):
            p.error("--allow-empty expects a placeholder name, got %r" % name)
    if args.context_lines is not None:
        if args.context_lines < 0:
            p.error("--context-lines must be >= 0")
        if args.diff_file:
            p.error(
                "--context-lines cannot be used with --diff-file (the diff is "
                "already made)"
            )
    if args.whole_file:
        if args.diff_file:
            p.error(
                "--whole-file cannot be used with --diff-file (file contents are "
                "read from git)"
            )
        args.per_file = True
    if args.max_files < 1:
        p.error("--max-files must be >= 1")
    if args.per_file and len(args.prompt) > 1:
        p.error(
            "--per-file / --whole-file cannot be used with several --prompt files "
            "(combined mode)"
        )


def _print_prompt(prompt: str, header: str = "") -> None:
    if header:
        sys.stdout.write(header + "\n")
    sys.stdout.write(REDACT(prompt) + "\n")
    sys.stdout.flush()


def run_once(
    args: argparse.Namespace,
    session: Session,
    prompts: List[Prompt],
    fields: Dict[str, Optional[str]],
    values: Dict[str, str],
    change: Change,
    kept: List[Section],
    notes: List[str],
) -> int:
    """One request for the whole change (one prompt, or several in combined mode)."""
    combined = len(prompts) > 1
    text, shown, total, unread = fit_sections(kept, args.max_diff_chars)
    if unread:
        warn(
            "the diff has %d characters; only the first %d are reviewed "
            "(--max-diff-chars). Not reviewed: %s" % (total, shown, name_list(unread))
        )
    vals = dict(values)
    vals.update({k: text for k in DIFF_KEYS})
    filled = [fill_template(pr.template, vals)[0] for pr in prompts]
    prompt = build_combined(prompts, filled) if combined else filled[0]
    if args.dry_run:
        _print_prompt(prompt)
        return EXIT_OK
    if args.verbose:
        warn(
            "reviewing %s: %d diff chars, %d prompt chars, model %s"
            % (change.label, len(text), len(prompt), args.model)
        )
    cut = "partial review: first %d of %d diff characters" % (shown, total)
    no_finding = "no finding in the first %d of %d diff characters" % (shown, total)
    unasked = session.unasked  # left out by the built-in list: not reviewed either
    if unasked and not unread:
        cut = "partial review: %d file(s) left out" % len(unasked)
        no_finding = "no finding in the files that were reviewed"
    missing = list(unread) + ["%s (left out by default)" % x for x in unasked]

    if not combined:
        status, vtext, cached = session.ask(prompt, fields[prompts[0].mode])
        extras = ["cached"] if cached else []
        if status == "flagged":
            say(
                "flagged: %s"
                % result_text(vtext, ([cut] if missing else []) + extras, notes)
            )
            return EXIT_FLAGGED
        if status == "ok" and missing:
            hint = "; %s" % UNASKED_HINT if unasked else ""
            say(
                "partial: %s"
                % result_text(
                    "%s; not reviewed: %s%s" % (no_finding, name_list(missing), hint),
                    extras,
                    [n for n in notes if " left out: " not in n],
                )
            )
            return args.error_exit
        if status == "ok":
            say("ok: %s" % result_text(vtext, extras, notes))
            return EXIT_OK
        say("error: unreadable answer: %s" % one_line(vtext))
        return args.error_exit

    results, cached = session.ask_combined(prompt, prompts, fields)
    extras = ["cached"] if cached else []
    for mode, status, vtext in results:
        if status == "flagged":
            line = "flagged: %s" % result_text(
                vtext, ([cut] if missing else []) + extras, notes, 220
            )
        elif status == "ok" and missing:
            line = "partial: %s" % result_text(no_finding, extras, notes, 220)
        elif status == "ok":
            line = "ok: %s" % result_text(vtext, extras, notes, 220)
        else:
            line = "error: unreadable answer: %s" % one_line(vtext, 200)
        say("%s %s" % (mode, line))
    statuses = {s for _m, s, _t in results}
    if "flagged" in statuses:
        return EXIT_FLAGGED
    if "unreadable" in statuses or missing:
        return args.error_exit
    return EXIT_OK


def nothing_to_review(
    args: argparse.Namespace, left_out: List[str], unasked: List[str]
) -> int:
    """No file is left to send. That is ``skipped`` only when every changed file
    was left out on request; files left out by the built-in list were changed
    and not reviewed, which is ``partial``."""
    if unasked:
        say(
            "partial: %s"
            % one_line(
                "nothing was reviewed; left out by default: %s; %s"
                % (name_list(unasked), UNASKED_HINT)
            )
        )
        return args.error_exit
    say("skipped: no reviewable changes (%s)" % left_out_note(left_out))
    return EXIT_OK


def run_per_file(
    args: argparse.Namespace,
    session: Session,
    prompt: Prompt,
    field: Optional[str],
    values: Dict[str, str],
    change: Change,
    kept: List[Section],
    left_out: List[str],
    notes: List[str],
) -> int:
    """One request per changed file (its diff, or its full content with --whole-file)."""
    units: List[Tuple[str, str]] = []
    for s in kept:
        name = s.path or "(text before the first file)"
        if not args.whole_file:
            units.append((name, s.text))
            continue
        if s.path is None:
            continue
        if s.deleted:
            left_out.append("%s (deleted)" % s.path)
            continue
        content, why = file_content(change, s.path)
        if content is None:
            left_out.append("%s (%s)" % (s.path, why))
            continue
        units.append((s.path, content))
    notes = [n for n in notes if " left out: " not in n]
    if left_out:
        notes.insert(0, left_out_note(left_out))
    if not units:
        if args.dry_run:
            warn("no file to review; nothing would be sent")
            return EXIT_OK
        return nothing_to_review(args, left_out, session.unasked)

    total = len(units) + len(session.unasked)
    not_reviewed: List[str] = [
        "%s (over --max-files %d)" % (path, args.max_files)
        for path, _text in units[args.max_files :]
    ] + ["%s (left out by default)" % x for x in session.unasked]
    flagged: List[Tuple[str, str]] = []
    clean: List[str] = []
    first_error = ""
    failures = 0  # requests that failed one after the other
    n_cached = 0
    for i, (path, text) in enumerate(units[: args.max_files]):
        limit = args.max_diff_chars
        was_cut = bool(limit and len(text) > limit)
        if was_cut:
            text = text[:limit] + (
                "\n[truncated: %d of %d characters shown]\n" % (limit, len(text))
            )
        vals = dict(values)
        vals.update({k: text for k in DIFF_KEYS})
        filled = fill_template(prompt.template, vals)[0]
        if args.dry_run:
            _print_prompt(filled, "### request %d of %d: %s" % (i + 1, total, path))
            continue
        if failures >= 2:
            not_reviewed.append("%s (not reached)" % path)
            continue
        if args.verbose:
            warn(
                "reviewing %s, file %d of %d (%s): %d chars, model %s"
                % (change.label, i + 1, total, path, len(text), args.model)
            )
        try:
            if (
                session.time_left() < 1
                and session.cache.get(cache_key(args, field, filled, session.endpoint))
                is None
            ):
                not_reviewed.append("%s (not reached in --timeout)" % path)
                continue
            status, vtext, cached = session.ask(filled, field)
        except ReviewError as exc:
            # No endpoint or key: no later request can work either.
            failures = 2 if isinstance(exc, SetupError) else failures + 1
            first_error = first_error or str(exc)
            not_reviewed.append("%s (error)" % path)
            continue
        failures = 0
        n_cached += 1 if cached else 0
        if status == "flagged":
            cut_note = " (file cut at %d characters)" % limit if was_cut else ""
            flagged.append((path, one_line(vtext, 110) + cut_note))
        elif status == "ok" and was_cut:
            not_reviewed.append("%s (cut at %d characters)" % (path, limit))
        elif status == "ok":
            clean.append(path)
        else:
            first_error = first_error or "unreadable answer: %s" % vtext
            not_reviewed.append("%s (unreadable answer)" % path)
    if args.dry_run:
        return EXIT_OK

    answered = len(flagged) + len(clean)
    extras = []
    if n_cached:
        extras.append(
            "cached"
            if n_cached == answered and not not_reviewed
            else "%d cached" % n_cached
        )
    if flagged:
        if not_reviewed:
            extras.insert(0, "partial review: %d of %d files" % (answered, total))
        text = "; ".join("%s: %s" % item for item in flagged)
        say("flagged: %s" % result_text(text, extras, notes))
        return EXIT_FLAGGED
    if not_reviewed:
        if not clean:
            say(
                "error: no file could be reviewed (%d of %d): %s"
                % (
                    len(not_reviewed),
                    total,
                    one_line(first_error or name_list(not_reviewed), 200),
                )
            )
            return args.error_exit
        say(
            "partial: %s"
            % result_text(
                "no finding in %d of %d file(s); not reviewed: %s"
                % (len(clean), total, name_list(not_reviewed)),
                extras,
                notes,
            )
        )
        return args.error_exit
    say(
        "ok: %s"
        % result_text("%d file(s) reviewed, none flagged" % len(clean), extras, notes)
    )
    return EXIT_OK


def run(p: _Parser, args: argparse.Namespace) -> int:
    _check_args(p, args)
    key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
    REDACT.add(key)
    base = os.environ.get(args.api_base_env, "").strip()
    note_base_url(base, args.api_key_env)

    prompts = [load_prompt(spec) for spec in args.prompt]
    modes = [pr.mode for pr in prompts]
    dupes = sorted({m for m in modes if modes.count(m) > 1})
    if dupes:
        raise ReviewError(
            "several prompt files share the mode name %s" % ", ".join(dupes)
        )
    fills = load_fills(args)
    check_templates(prompts, fills, args.allow_empty)  # before any request
    combined = len(prompts) > 1
    if combined:
        warn(COMBINED_WARNING)

    change = obtain_change(args)
    if not change.diff.strip() and not args.dry_run:
        say("skipped: no changes to review (%s)" % change.label)
        return EXIT_OK
    kept, left_out, unasked = select_sections(
        split_diff(change.diff), args.exclude, not args.no_default_excludes
    )
    if left_out and args.verbose:
        warn("left out of the review: %s" % ", ".join(left_out))
    if not kept and not args.dry_run:
        return nothing_to_review(args, left_out, unasked)

    notes: List[str] = []
    if left_out:
        notes.append(left_out_note(left_out))
    task, has_task = load_task(args)
    used = {n for pr in prompts for n in placeholder_names(pr.template)}
    if not has_task and used & set(TASK_KEYS):
        notes.append("no task file")
    values: Dict[str, str] = {k: task for k in TASK_KEYS}
    values["context"] = load_context(args.context_file)
    for name in args.allow_empty:
        values.setdefault(name, "")
    values.update(fills)
    fields = {
        pr.mode: (
            args.flag_field
            if args.flag_field != "auto"
            else detect_flag_field(pr.template)
        )
        for pr in prompts
    }
    session = Session(args, base, key)
    session.unasked = unasked
    if args.per_file:
        return run_per_file(
            args,
            session,
            prompts[0],
            fields[prompts[0].mode],
            values,
            change,
            kept,
            left_out,
            notes,
        )
    return run_once(args, session, prompts, fields, values, change, kept, notes)


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
    except ReviewError as exc:
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
