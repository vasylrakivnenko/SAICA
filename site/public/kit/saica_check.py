#!/usr/bin/env python3
"""SAICA supervision kit: per-commit check runner (contract v1).

Runs the supervision tools configured in ``.saica/checks.json`` plus four
cheap built-in diff heuristics against a commit (or the staged changes),
and records one JSON event per (commit, tool, failure mode) in
``.saica/events.jsonl``. See the kit README for the full contract.

How a tool's exit code is read: 0 = ``pass``; a code listed in the tool's
``caught_exit_codes`` (default: 1) = ``caught``; every other exit code, a
timeout or a command that cannot start = ``error`` (a tool failure, never a
finding, never blocking). The built-in heuristics are not benchmarked and do
not count as coverage of a failure mode.

Python 3.9+, standard library only. Copy this file to
``.saica/saica_check.py`` in your repository.

Subcommands::

    run --staged [--source pre-commit] [--no-block]
        Check the staged changes (git pre-commit hook). Writes
        .saica/pending.jsonl; exits 1 if a blocking check caught something.
    run --commit SHA [--source ci|manual] [--no-block]
        Check an existing commit. Appends to .saica/events.jsonl directly.
    stamp
        (git post-commit hook) Move pending events to events.jsonl, stamped
        with the HEAD commit sha, timestamp, subject and detected agent.
    replay --last N [--with-tools]
        Run the built-in checks over the last N commits.
    dashboard [--template PATH] [--out PATH]
        Write .saica/dashboard.html with all events embedded.
    install-hooks [--force]
        Install the pre-commit / post-commit hooks into the repo.

Exit codes: 0 ok, 1 a blocking check caught something (run only),
2 usage / configuration / git error.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

CONTRACT_VERSION = 1

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

OUTCOMES = ("pass", "caught", "error", "skipped", "not_runnable", "not_covered")
SOURCES = ("pre-commit", "ci", "replay", "manual")

BUILTIN_CHECKS = (
    ("saica:stub-markers", "incomplete_execution"),
    ("saica:test-weakening", "test_manipulation"),
    ("saica:phantom-import", "fabrication"),
    ("saica:kit-tamper", "test_manipulation"),
)
# The built-ins are diff heuristics. None of them was scored on SAICA-Bench, so
# they are reported as such and never count as coverage of a failure mode.
BUILTIN_NOTE = "heuristic, not benchmarked"
TAMPER_CHECK = "saica:kit-tamper"

DETAIL_MAX = 500
DEFAULT_TIMEOUT_S = 300
DEFAULT_CAUGHT_EXIT_CODES = (1,)
# The whole command is one argument of ``sh -c``; Linux limits one argument to 128 KiB.
MAX_COMMAND_BYTES = 120000
STAGED = "staged"


class SaicaError(Exception):
    """A user-facing error (bad config, not a git repo, ...). Exit code 2."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch_to_iso(epoch: str) -> Optional[str]:
    try:
        ts = _dt.datetime.fromtimestamp(int(epoch), _dt.timezone.utc)
    except (TypeError, ValueError):
        return None
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _truncate(text: str, limit: int = DETAIL_MAX) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _warn(msg: str) -> None:
    print("saica: " + msg, file=sys.stderr)


def git(
    args: List[str],
    cwd: Path,
    check: bool = True,
    env: Optional[Dict[str, str]] = None,
) -> str:
    """Run ``git`` and return stdout (decoded, errors replaced)."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        raise SaicaError("git is not installed or not on PATH")
    out = proc.stdout.decode("utf-8", "replace")
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise SaicaError("git %s failed: %s" % (" ".join(args), err))
    return out


def git_ok(args: List[str], cwd: Path) -> bool:
    """True when ``git`` exits 0 (output discarded)."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return proc.returncode == 0


def find_repo_root(start: Optional[Path] = None) -> Path:
    cwd = start or Path.cwd()
    try:
        out = git(["rev-parse", "--show-toplevel"], cwd)
    except SaicaError:
        raise SaicaError(
            "not inside a git repository (git rev-parse --show-toplevel failed)"
        )
    return Path(out.strip())


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config(path: Path) -> dict:
    """Load and validate ``checks.json``. Returns a normalised dict."""
    if not path.is_file():
        raise SaicaError(
            "config not found: %s (copy checks.example.json to .saica/checks.json)"
            % path
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SaicaError("config %s is not valid JSON: %s" % (path, exc))
    return parse_config(raw, str(path))


def parse_config(raw: object, where: str = "checks.json") -> dict:
    if not isinstance(raw, dict):
        raise SaicaError("%s: top level must be a JSON object" % where)
    version = raw.get("version", CONTRACT_VERSION)
    if version != CONTRACT_VERSION:
        raise SaicaError(
            "%s: unsupported version %r (this runner speaks v%d)"
            % (where, version, CONTRACT_VERSION)
        )
    kit = raw.get("kit")
    if kit is not None and not isinstance(kit, str):
        raise SaicaError("%s: 'kit' must be a string" % where)

    builtin_raw = raw.get("builtin", {})
    if not isinstance(builtin_raw, dict):
        raise SaicaError("%s: 'builtin' must be an object" % where)
    builtin = {
        "enabled": bool(builtin_raw.get("enabled", True)),
        "blocking": bool(builtin_raw.get("blocking", False)),
        # A change to the kit's own files stops the commit unless this is false.
        "tamper_blocking": bool(builtin_raw.get("tamper_blocking", True)),
    }

    tools_raw = raw.get("tools", [])
    if not isinstance(tools_raw, list):
        raise SaicaError("%s: 'tools' must be a list" % where)
    tools = []
    seen: Set[str] = set()
    for i, t in enumerate(tools_raw):
        label = "%s: tools[%d]" % (where, i)
        if not isinstance(t, dict):
            raise SaicaError("%s must be an object" % label)
        tid = t.get("id")
        if not isinstance(tid, str) or not tid.strip():
            raise SaicaError("%s: 'id' must be a non-empty string" % label)
        if tid.startswith("saica:"):
            raise SaicaError("%s: id prefix 'saica:' is reserved for built-ins" % label)
        if tid in seen:
            raise SaicaError("%s: duplicate tool id %r" % (label, tid))
        seen.add(tid)
        fms = t.get("failure_modes")
        if not isinstance(fms, list) or not fms:
            raise SaicaError(
                "%s (%s): 'failure_modes' must be a non-empty list" % (label, tid)
            )
        for fm in fms:
            if fm not in FAILURE_MODES:
                raise SaicaError(
                    "%s (%s): unknown failure mode %r; expected one of: %s"
                    % (label, tid, fm, ", ".join(FAILURE_MODES))
                )
        runs = bool(t.get("runs_per_commit", True))
        command = t.get("command")
        if runs:
            if not isinstance(command, str) or not command.strip():
                raise SaicaError(
                    "%s (%s): 'command' is required when runs_per_commit is true"
                    % (label, tid)
                )
        timeout = t.get("timeout_s", DEFAULT_TIMEOUT_S)
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout <= 0
        ):
            raise SaicaError(
                "%s (%s): 'timeout_s' must be a positive number" % (label, tid)
            )
        codes = t.get("caught_exit_codes", list(DEFAULT_CAUGHT_EXIT_CODES))
        if (
            not isinstance(codes, list)
            or not codes
            or any(
                isinstance(c, bool)
                or not isinstance(c, int)
                or not 1 <= c <= 255
                or c == 127
                for c in codes
            )
        ):
            raise SaicaError(
                "%s (%s): 'caught_exit_codes' must be a non-empty list of exit codes "
                "from 1 to 255, without 127 (127 always means the command could not run)"
                % (label, tid)
            )
        blocking = bool(t.get("blocking", False))
        # What a check that could not run on the change does: a blocking check
        # blocks (it did not vouch for the change) unless on_error says "pass".
        on_error = t.get("on_error", "block" if blocking else "pass")
        if on_error not in ("block", "pass"):
            raise SaicaError(
                '%s (%s): \'on_error\' must be "block" or "pass"' % (label, tid)
            )
        note = t.get("note")
        if note is not None and not isinstance(note, str):
            raise SaicaError("%s (%s): 'note' must be a string" % (label, tid))
        metric = t.get("metric")
        if metric is not None:
            if (
                not isinstance(metric, dict)
                or not isinstance(metric.get("name"), str)
                or not isinstance(metric.get("regex"), str)
            ):
                raise SaicaError(
                    '%s (%s): \'metric\' must be {"name": str, "regex": str}'
                    % (label, tid)
                )
            try:
                compiled = re.compile(metric["regex"])
            except re.error as exc:
                raise SaicaError("%s (%s): bad metric regex: %s" % (label, tid, exc))
            if compiled.groups < 1:
                raise SaicaError(
                    "%s (%s): metric regex needs a capture group" % (label, tid)
                )
        tools.append(
            {
                "id": tid,
                "failure_modes": list(dict.fromkeys(fms)),
                "runs_per_commit": runs,
                "command": command if isinstance(command, str) else None,
                "blocking": blocking,
                "on_error": on_error,
                "timeout_s": float(timeout),
                "caught_exit_codes": sorted(set(codes)),
                "metric": metric,
                "note": note,
            }
        )
    return {"version": CONTRACT_VERSION, "kit": kit, "builtin": builtin, "tools": tools}


# ---------------------------------------------------------------------------
# Diffs
# ---------------------------------------------------------------------------


class FileDiff:
    """Added / removed lines of one file. Lines are (line_no, text)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.added: List[Tuple[int, str]] = []
        self.removed: List[Tuple[int, str]] = []


class ChangeSet:
    def __init__(
        self,
        files: List[str],
        diffs: Dict[str, FileDiff],
        touched: Optional[List[str]] = None,
        base: Optional[str] = None,
    ) -> None:
        self.files = files  # existing (added/copied/modified/renamed) paths
        self.diffs = diffs
        # Every path the change adds, modifies, deletes or renames (old and new name).
        self.touched = (
            list(touched) if touched is not None else sorted(set(files) | set(diffs))
        )
        self.base = base  # tree-ish the change is compared with (None: not known)


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13}


def _unquote_path(p: str) -> str:
    """Undo git's C-style quoting of a path in a diff header (``"a\\tb\\303\\274.py"``)."""
    p = p.strip()
    if not (len(p) >= 2 and p.startswith('"') and p.endswith('"')):
        return p
    body = p[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\" or i + 1 >= len(body):
            out.extend(ch.encode("utf-8", "replace"))
            i += 1
            continue
        nxt = body[i + 1]
        if nxt in "01234567":
            j = i + 1
            while j < len(body) and j < i + 4 and body[j] in "01234567":
                j += 1
            out.append(int(body[i + 1 : j], 8) & 0xFF)
            i = j
            continue
        if nxt in _C_ESCAPES:
            out.append(_C_ESCAPES[nxt])
        else:  # an escaped quote or backslash, or anything unknown: the character itself
            out.extend(nxt.encode("utf-8", "replace"))
        i += 2
    return out.decode("utf-8", "replace")


def parse_unified_diff(text: str) -> Dict[str, FileDiff]:
    """Parse ``git diff -U0`` output into per-file added/removed lines."""
    diffs: Dict[str, FileDiff] = {}
    current: Optional[FileDiff] = None
    in_header = False
    old_no = new_no = 0
    old_path: Optional[str] = None
    # Split on "\n" only: str.splitlines() would also break lines at form feeds
    # and other separators that can occur inside source code.
    for line in text.split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        if line.startswith("diff --git "):
            current = None
            in_header = True
            old_path = None
            continue
        if in_header:
            if line.startswith("--- "):
                old_path = _unquote_path(line[4:])
                continue
            if line.startswith("+++ "):
                new = _unquote_path(line[4:])
                if new == "/dev/null":
                    path = (
                        old_path[2:]
                        if old_path and old_path.startswith("a/")
                        else old_path
                    )
                else:
                    path = new[2:] if new.startswith("b/") else new
                if path:
                    current = diffs.setdefault(path, FileDiff(path))
                continue
            if line.startswith("@@"):
                in_header = False
            else:
                continue  # index / mode / rename / Binary lines
        m = _HUNK_RE.match(line)
        if m:
            old_no, new_no = int(m.group(1)), int(m.group(2))
            continue
        if current is None:
            continue
        if line.startswith("+"):
            current.added.append((new_no, line[1:]))
            new_no += 1
        elif line.startswith("-"):
            current.removed.append((old_no, line[1:]))
            old_no += 1
        elif line.startswith(" "):
            old_no += 1
            new_no += 1
    return diffs


# Renames are detected, so the lines of a file that was only moved are not "added".
# --text / --no-textconv / --no-ext-diff: a .gitattributes line (`*.py -diff`, a
# diff driver, a textconv filter) must not be able to hide a change from the checks.
_DIFF_FLAGS = [
    "-U0",
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--text",
    "--find-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
]
# Paths in diff headers are not octal-escaped (non-ASCII names stay readable).
_QUOTE_OFF = ["-c", "core.quotePath=false"]


def _changeset(root: Path, base: str, tree: str) -> ChangeSet:
    """The change from ``base`` to ``tree`` (two tree-ish names)."""
    names = git(
        [
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            "--find-renames",
            "-z",
            base,
            tree,
        ],
        root,
    )
    files = [n for n in names.split("\0") if n]
    every = git(["diff", "--name-only", "--no-renames", "-z", base, tree], root)
    touched = [n for n in every.split("\0") if n]
    text = git(_QUOTE_OFF + ["diff"] + _DIFF_FLAGS + [base, tree], root)
    diffs = parse_unified_diff(text)
    for fd in diffs.values():
        # With --text a binary file comes through as lines too: not for the heuristics.
        if any("\0" in t for _no, t in fd.added) or any(
            "\0" in t for _no, t in fd.removed
        ):
            fd.added, fd.removed = [], []
    return ChangeSet(files, diffs, touched=touched, base=base)


def head_commit(root: Path) -> Optional[str]:
    """Full sha of HEAD, or None on an unborn branch (before the first commit)."""
    out = git(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], root, check=False)
    return out.strip() or None


def staged_snapshot(root: Path) -> Tuple[str, Optional[str]]:
    """Freeze the index as a tree object. Returns (tree sha, HEAD sha or None).

    Everything a staged run looks at is derived from this immutable tree, so
    a concurrent ``git add`` cannot make the diff, the dependency manifests and
    the tool checkout disagree with each other.
    """
    head = head_commit(root)
    try:
        tree = git(["write-tree"], root).strip()
    except SaicaError as exc:
        raise SaicaError(
            "cannot snapshot the index (unresolved merge conflicts?): %s" % exc
        )
    if not tree:
        raise SaicaError("cannot snapshot the index: git write-tree printed nothing")
    return tree, head


def staged_changeset(
    root: Path, snapshot: Optional[Tuple[str, Optional[str]]] = None
) -> ChangeSet:
    """Diff of the staged snapshot against HEAD (or the empty tree)."""
    tree, head = snapshot if snapshot is not None else staged_snapshot(root)
    # ``git mktree`` with empty input yields the repo's own empty-tree id.
    base = head or git(["mktree"], root).strip()
    return _changeset(root, base, tree)


def overlay_kit(root: Path, treeish: str, work: Path, scratch: Path) -> None:
    """Replace ``work/.saica`` with the ``.saica`` folder of ``treeish``.

    Tools run in a checkout of the staged tree, but the helper scripts and
    prompts they call must be the committed ones: a staged edit to a helper
    would otherwise run as the checker of the very change that carries it.
    """
    sub = git(
        ["rev-parse", "--verify", "--quiet", "%s:.saica" % treeish], root, check=False
    ).strip()
    if not sub:
        return
    target = work / ".saica"
    shutil.rmtree(str(target), ignore_errors=True)
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = str(scratch / "index-kit")
    git(["read-tree", sub], root, env=env)
    git(
        ["checkout-index", "--all", "--force", "--prefix=" + target.as_posix() + "/"],
        root,
        env=env,
    )


def checkout_tree(root: Path, tree: str) -> Tuple[Path, Path, Dict[str, str]]:
    """Materialise ``tree`` in a temp directory, leaving the real index alone.

    Returns (temp base to delete afterwards, checkout dir, environment for
    tools). The environment points git at the temp index and checkout, so a
    tool that calls git sees the snapshot rather than the working tree.
    """
    base = Path(tempfile.mkdtemp(prefix="saica-staged-"))
    try:
        index_file = base / "index"
        work = base / "tree"
        work.mkdir()
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(index_file)
        git(["read-tree", tree], root, env=env)
        git(
            ["checkout-index", "--all", "--force", "--prefix=" + work.as_posix() + "/"],
            root,
            env=env,
        )
        tool_env = dict(env)
        tool_env["GIT_DIR"] = git(["rev-parse", "--absolute-git-dir"], root).strip()
        tool_env["GIT_WORK_TREE"] = str(work)
        tool_env.pop("GIT_PREFIX", None)
        tool_env["SAICA_REPO_ROOT"] = str(root)
    except BaseException:
        shutil.rmtree(str(base), ignore_errors=True)
        raise
    return base, work, tool_env


def resolve_commit(root: Path, ref: str) -> str:
    try:
        return git(
            ["rev-parse", "--verify", "--quiet", ref + "^{commit}"], root
        ).strip()
    except SaicaError:
        raise SaicaError("not a commit: %s" % ref)


def commit_changeset(root: Path, sha: str) -> ChangeSet:
    """Diff of a commit against its first parent (or the empty tree)."""
    parents = git(["rev-list", "--parents", "-n", "1", sha], root).split()
    base = parents[1] if len(parents) > 1 else git(["mktree"], root).strip()
    return _changeset(root, base, sha)


def commit_info(root: Path, sha: str) -> dict:
    fmt = "%H%x00%ct%x00%s%x00%an%x00%ae%x00%B"
    out = git(["log", "-1", "--format=" + fmt, sha], root)
    parts = out.split("\0", 5)
    while len(parts) < 6:
        parts.append("")
    full, ct, subject, an, ae, body = parts
    return {
        "commit": full.strip(),
        "commit_ts": _epoch_to_iso(ct.strip()),
        "subject": subject,
        "agent": detect_agent(an, ae, body),
    }


# ---------------------------------------------------------------------------
# Agent detection (identities are inspected, never recorded)
# ---------------------------------------------------------------------------

_COAUTHOR_RE = re.compile(r"^\s*co-authored-by:\s*(.*?)\s*<([^>]*)>\s*$", re.I | re.M)

_AGENT_PATTERNS = (
    (
        "claude",
        re.compile(
            r"anthropic\.com|\bclaude[\s_-]*(code|opus|sonnet|haiku|ai|agent)\b|claude\[bot\]",
            re.I,
        ),
    ),
    ("copilot", re.compile(r"copilot", re.I)),
    ("cursor", re.compile(r"cursor(agent|\.com|\.sh|\[bot\]|\s+agent)", re.I)),
    ("devin", re.compile(r"devin(-ai|\.ai|\[bot\])", re.I)),
    ("codex", re.compile(r"codex", re.I)),
    ("aider", re.compile(r"\baider\b", re.I)),
)
_BOT_RE = re.compile(r"\[bot\]|\bbot\b", re.I)


def detect_agent(author_name: str, author_email: str, body: str = "") -> Optional[str]:
    """Map author + Co-Authored-By trailers to an agent label (or None)."""
    identities = ["%s <%s>" % (author_name or "", author_email or "")]
    for name, email in _COAUTHOR_RE.findall(body or ""):
        identities.append("%s <%s>" % (name, email))
    for ident in identities:
        for label, pat in _AGENT_PATTERNS:
            if pat.search(ident):
                return label
    for ident in identities:
        if _BOT_RE.search(ident):
            return "bot"
    return None


# ---------------------------------------------------------------------------
# Built-in checks
# ---------------------------------------------------------------------------

_SKIP_EXT = {".md", ".markdown", ".rst", ".txt", ".lock", ".svg", ".csv", ".jsonl"}


def _skip_for_builtins(path: str) -> bool:
    p = path.replace("\\", "/")
    if (
        p.startswith(".saica/")
        or "/node_modules/" in p
        or p.startswith("node_modules/")
    ):
        return True
    return os.path.splitext(p)[1].lower() in _SKIP_EXT


# A marker counts only when it sits in a comment (conservative).
_MARKER_RE = re.compile(
    r"(?:#|//|/\*|<!--|^\s*\*|^\s*--|^\s*;|^\s*%)[^\n]*?\b(TODO|FIXME|XXX)\b"
)
_NOT_IMPL_RE = re.compile(r"\braise\s+NotImplemented(Error)?\b")
_DEF_RE = re.compile(r"^\s*(async\s+)?def\s+\w+\s*\(.*:\s*(#.*)?$")
_ABSTRACT_RE = re.compile(r"^\s*@(\w+\.)*(abstractmethod|overload|abstractproperty)\b")


def check_stub_markers(cs: ChangeSet) -> List[str]:
    hits: List[str] = []
    for path, fd in sorted(cs.diffs.items()):
        if _skip_for_builtins(path):
            continue
        is_py = path.endswith(".py")
        prev: List[str] = []  # previous non-blank added lines (consecutive)
        prev_no = None
        for no, text in fd.added:
            if prev_no is not None and no != prev_no + 1:
                prev = []
            prev_no = no
            m = _MARKER_RE.search(text)
            if m:
                hits.append("%s:%d %s" % (path, no, m.group(1)))
            elif _NOT_IMPL_RE.search(text):
                hits.append("%s:%d raise NotImplemented" % (path, no))
            elif (
                is_py
                and text.strip() in ("pass", "...")
                and prev
                and _DEF_RE.match(prev[-1])
            ):
                decorated = len(prev) >= 2 and _ABSTRACT_RE.match(prev[-2])
                if not decorated:
                    hits.append("%s:%d body-only %s" % (path, no, text.strip()))
            if text.strip():
                prev.append(text)
                prev = prev[-3:]
    return hits


_TEST_NAME_RE = re.compile(
    r"(^test_.*\.py$|_test\.py$|^conftest\.py$|_test\.go$|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|Tests?\.(java|kt|cs)$|_spec\.rb$|_test\.rb$)"
)
_TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs"}


def is_test_file(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    if _TEST_NAME_RE.search(parts[-1]):
        return True
    return any(p in _TEST_DIRS for p in parts[:-1])


_ASSERT_RE = re.compile(
    r"\bassert\w*\b|\bexpect\s*\(|\.should\b|\bt\.(Errorf?|Fatalf?|Fail(Now)?)\s*\(|\bverify\s*\("
)
_SKIP_MARK_RE = re.compile(
    r"(@pytest\.mark\.(skip|xfail)\b|\bpytest\.(skip|xfail)\s*\(|@unittest\.(skip|expectedFailure)\b"
    r"|\.skip\s*\(|\b(it|describe|test|context)\.only\s*\(|\bx(it|describe|test)\s*\("
    r"|\bt\.Skip(f|Now)?\s*\(|@Disabled\b|@Ignore\b)"
)


def check_test_weakening(cs: ChangeSet) -> List[str]:
    hits: List[str] = []
    added_asserts = removed_asserts = 0
    for path, fd in sorted(cs.diffs.items()):
        if _skip_for_builtins(path) or not is_test_file(path):
            continue
        for _no, text in fd.removed:
            if _ASSERT_RE.search(text):
                removed_asserts += 1
        for no, text in fd.added:
            if _ASSERT_RE.search(text):
                added_asserts += 1
            m = _SKIP_MARK_RE.search(text)
            if m:
                hits.append("%s:%d %s" % (path, no, m.group(1).strip()))
    if removed_asserts > added_asserts:
        hits.insert(
            0,
            "assertions removed (%d) > added (%d) in test files"
            % (removed_asserts, added_asserts),
        )
    return hits


_STDLIB_FALLBACK = set(
    """__future__ _thread abc aifc argparse array ast asynchat asyncio asyncore atexit
    audioop base64 bdb binascii bisect builtins bz2 calendar cgi cgitb chunk cmath cmd
    code codecs codeop collections colorsys compileall concurrent configparser contextlib
    contextvars copy copyreg cProfile crypt csv ctypes curses dataclasses datetime dbm
    decimal difflib dis distutils doctest email encodings ensurepip enum errno faulthandler
    fcntl filecmp fileinput fnmatch fractions ftplib functools gc getopt getpass gettext
    glob graphlib grp gzip hashlib heapq hmac html http idlelib imaplib imghdr imp importlib
    inspect io ipaddress itertools json keyword lib2to3 linecache locale logging lzma
    mailbox mailcap marshal math mimetypes mmap modulefinder msilib msvcrt multiprocessing
    netrc nis nntplib ntpath numbers opcode operator optparse os ossaudiodev pathlib pdb
    pickle pickletools pipes pkgutil platform plistlib poplib posix posixpath pprint
    profile pstats pty pwd py_compile pyclbr pydoc queue quopri random re readline reprlib
    resource rlcompleter runpy sched secrets select selectors shelve shlex shutil signal
    site smtpd smtplib sndhdr socket socketserver spwd sqlite3 sre_compile sre_constants
    sre_parse ssl stat statistics string stringprep struct subprocess sunau symtable sys
    sysconfig syslog tabnanny tarfile telnetlib tempfile termios textwrap threading time
    timeit tkinter token tokenize tomllib trace traceback tracemalloc tty turtle turtledemo
    types typing unicodedata unittest urllib uu uuid venv warnings wave weakref webbrowser
    winreg winsound wsgiref xdrlib xml xmlrpc zipapp zipfile zipimport zlib zoneinfo""".split()
)


def python_stdlib() -> Set[str]:
    names = set(_STDLIB_FALLBACK)
    names.update(getattr(sys, "stdlib_module_names", ()))
    names.update(sys.builtin_module_names)
    return names


NODE_BUILTINS = set(
    """assert async_hooks buffer child_process cluster console constants crypto dgram
    diagnostics_channel dns domain events fs http http2 https inspector module net os path
    perf_hooks process punycode querystring readline repl stream string_decoder sys timers
    tls trace_events tty url util v8 vm wasi worker_threads zlib test sqlite""".split()
)

# Distribution name -> import names, for the common mismatches.
_DIST_ALIASES = {
    "pyyaml": ["yaml"],
    "beautifulsoup4": ["bs4"],
    "pillow": ["PIL"],
    "scikit_learn": ["sklearn"],
    "scikit_image": ["skimage"],
    "python_dateutil": ["dateutil"],
    "opencv_python": ["cv2"],
    "opencv_python_headless": ["cv2"],
    "protobuf": ["google"],
    "attrs": ["attr", "attrs"],
    "python_dotenv": ["dotenv"],
    "pyjwt": ["jwt"],
    "psycopg2_binary": ["psycopg2"],
    "psycopg_binary": ["psycopg"],
    "pymupdf": ["fitz"],
    "pyserial": ["serial"],
    "pyzmq": ["zmq"],
    "pycryptodome": ["Crypto"],
    "msgpack_python": ["msgpack"],
    "google_api_python_client": ["googleapiclient"],
    "mysqlclient": ["MySQLdb"],
    "pywin32": ["win32api", "win32con", "pywintypes"],
    "setuptools": ["setuptools", "pkg_resources"],
    "typing_extensions": ["typing_extensions"],
    "faiss_cpu": ["faiss"],
    "sentence_transformers": ["sentence_transformers"],
    "python_multipart": ["multipart"],
    "pyopenssl": ["OpenSSL"],
    "ruamel.yaml": ["ruamel"],
}

_REQ_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _declared_import_names(dist_names: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    for dist in dist_names:
        n = _norm(dist)
        out.add(n)
        for alias in _DIST_ALIASES.get(n, []):
            out.add(_norm(alias))
        for prefix in ("python_", "py_"):
            if n.startswith(prefix):
                out.add(n[len(prefix) :])
        for suffix in ("_binary", "_headless", "_python"):
            if n.endswith(suffix):
                out.add(n[: -len(suffix)])
        # Many dists are "<import>-<suffix>" (umap-learn -> umap, google-cloud-x
        # -> google). Accept the leading segment too: slightly over-inclusive,
        # but it keeps phantom-import quiet on real, declared packages.
        if "_" in n:
            out.add(n.split("_", 1)[0])
    return out


def _parse_requirements(text: str) -> Set[str]:
    names: Set[str] = set()
    for line in text.splitlines():
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        egg = re.search(r"#egg=([A-Za-z0-9._-]+)", line)
        if egg:
            names.add(egg.group(1))
            continue
        if line.startswith("-"):
            continue
        m = _REQ_NAME_RE.match(line)
        if m:
            names.add(m.group(1))
    return names


def _parse_pyproject_like(text: str) -> Set[str]:
    """Over-inclusive scan of pyproject.toml / setup.cfg / setup.py / Pipfile."""
    names: Set[str] = set()
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped.lower()
            continue
        for quoted in re.findall(r"[\"']([^\"'\n]+)[\"']", line):
            m = _REQ_NAME_RE.match(quoted)
            if m:
                names.add(m.group(1))
        if "depend" in section or "packages" in section or "requires" in section:
            m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*[=<>~!]", line)
            if m:
                names.add(m.group(1))
            elif section.startswith("[options") and stripped and "=" not in stripped:
                m = _REQ_NAME_RE.match(stripped)  # setup.cfg continuation lines
                if m:
                    names.add(m.group(1))
    return names


def _parse_package_json(text: str) -> Set[str]:
    try:
        data = json.loads(text)
    except ValueError:
        return set()
    if not isinstance(data, dict):
        return set()
    names: Set[str] = set()
    if isinstance(data.get("name"), str):
        names.add(data["name"])
    for key in (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
        "bundledDependencies",
    ):
        deps = data.get(key)
        if isinstance(deps, dict):
            names.update(k for k in deps if isinstance(k, str))
        elif isinstance(deps, list):
            names.update(k for k in deps if isinstance(k, str))
    return names


class RepoIndex:
    """Local module names and declared dependencies of the repository.

    With ``tree`` (a tree or commit sha) the tracked paths and the manifest
    contents are read from that Git object; without it they come from the
    index listing and the working-tree files.
    """

    def __init__(self, root: Path, tree: Optional[str] = None) -> None:
        self.root = root
        self.tree = tree
        if tree:
            listed = git(
                ["ls-tree", "-r", "-z", "--name-only", "--full-tree", tree], root
            )
        else:
            try:
                listed = git(["ls-files", "-z", "--cached"], root)
            except SaicaError:
                listed = ""
        self.paths = [p for p in listed.split("\0") if p]
        self.local: Set[str] = set()
        py_manifests: List[str] = []
        js_manifests: List[str] = []
        for p in self.paths:
            parts = p.split("/")
            for d in parts[:-1]:
                self.local.add(d)
            base = parts[-1]
            stem, ext = os.path.splitext(base)
            if ext in (
                ".py",
                ".pyi",
                ".js",
                ".jsx",
                ".ts",
                ".tsx",
                ".mjs",
                ".cjs",
                ".so",
                ".pyd",
            ):
                self.local.add(stem.split(".")[0])
            if "node_modules" in parts:
                continue
            low = base.lower()
            if (
                (low.startswith("requirements") and low.endswith((".txt", ".in")))
                or (parts[:-1] and parts[-2] == "requirements" and low.endswith(".txt"))
                or low in ("pyproject.toml", "setup.cfg", "setup.py", "pipfile")
            ):
                py_manifests.append(p)
            elif low == "package.json":
                js_manifests.append(p)
        self.has_py_manifest = bool(py_manifests)
        self.has_js_manifest = bool(js_manifests)
        py_dists: Set[str] = set()
        for p in py_manifests:
            text = self._read(p)
            if p.lower().endswith((".txt", ".in")):
                py_dists |= _parse_requirements(text)
            else:
                py_dists |= _parse_pyproject_like(text)
        self.py_declared = _declared_import_names(py_dists)
        self.js_declared: Set[str] = set()
        for p in js_manifests:
            self.js_declared |= _parse_package_json(self._read(p))
        self.local_norm = {_norm(n) for n in self.local}
        self._pkg_dists = None

    def _read(self, rel: str) -> str:
        if self.tree:
            try:
                return git(["cat-file", "blob", "%s:%s" % (self.tree, rel)], self.root)
            except SaicaError:
                return ""
        try:
            return (self.root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def python_import_declared(self, top: str) -> bool:
        n = _norm(top)
        if n in self.py_declared:
            return True
        # Installed-distribution mapping (3.10+): import name -> dist names.
        if self._pkg_dists is None:
            try:
                from importlib.metadata import packages_distributions  # type: ignore

                self._pkg_dists = packages_distributions()
            except Exception:  # noqa: BLE001 - optional nicety only
                self._pkg_dists = {}
        for dist in self._pkg_dists.get(top, []):
            if _norm(dist) in self.py_declared:
                return True
        return False


_PY_IMPORT_RE = re.compile(
    r"^\s*import\s+([\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*)\s*(#.*)?$"
)
_PY_FROM_RE = re.compile(r"^\s*from\s+(\.*[\w.]*)\s+import\b")
_JS_IMPORT_RES = (
    re.compile(
        r"^\s*import\s+(?:type\s+)?(?:[\w*{}\s,$]+\s+from\s+)?[\"']([^\"']+)[\"']"
    ),
    re.compile(r"^\s*export\s+(?:type\s+)?[\w*{}\s,$]+\s+from\s+[\"']([^\"']+)[\"']"),
    re.compile(r"\brequire\s*\(\s*[\"']([^\"']+)[\"']\s*\)"),
    re.compile(r"\bimport\s*\(\s*[\"']([^\"']+)[\"']\s*\)"),
)
_JS_EXT = (
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".mts",
    ".cts",
    ".vue",
    ".svelte",
)


def _python_imports(text: str) -> List[str]:
    m = _PY_FROM_RE.match(text)
    if m:
        mod = m.group(1)
        if mod.startswith(".") or not mod:
            return []
        return [mod.split(".")[0]]
    m = _PY_IMPORT_RE.match(text)
    if m:
        out = []
        for part in m.group(1).split(","):
            name = part.strip().split()[0]
            out.append(name.split(".")[0])
        return out
    return []


def _js_package(spec: str) -> Optional[str]:
    if not spec or spec.startswith((".", "/", "~", "#", "@/", "$")):
        return None
    if spec.startswith("node:") or spec.startswith("bun:"):
        return None
    if ":" in spec:  # URLs, virtual modules, etc.
        return None
    parts = spec.split("/")
    if spec.startswith("@"):
        return "/".join(parts[:2]) if len(parts) >= 2 else None
    return parts[0]


def check_phantom_imports(cs: ChangeSet, index: RepoIndex) -> List[str]:
    hits: List[str] = []
    stdlib = python_stdlib()
    for path, fd in sorted(cs.diffs.items()):
        if _skip_for_builtins(path):
            continue
        siblings = set()
        dirname = os.path.dirname(path)
        for p in index.paths:
            if os.path.dirname(p) == dirname:
                siblings.add(os.path.splitext(os.path.basename(p))[0])
        if path.endswith((".py", ".pyi")):
            if not index.has_py_manifest:
                continue  # nothing to compare against; stay quiet
            for no, text in fd.added:
                for top in _python_imports(text):
                    if (
                        top in stdlib
                        or top in siblings
                        or top in index.local
                        or _norm(top) in index.local_norm
                        or index.python_import_declared(top)
                    ):
                        continue
                    hits.append("%s:%d import %s (not declared)" % (path, no, top))
        elif path.endswith(_JS_EXT):
            if not index.has_js_manifest:
                continue
            for no, text in fd.added:
                for rx in _JS_IMPORT_RES:
                    for spec in rx.findall(text):
                        pkg = _js_package(spec)
                        if not pkg or pkg in NODE_BUILTINS:
                            continue
                        if (
                            pkg in index.js_declared
                            or pkg in index.local
                            or pkg in siblings
                        ):
                            continue
                        msg = "%s:%d import %s (not declared)" % (path, no, pkg)
                        if msg not in hits:
                            hits.append(msg)
    return hits


# Files under .saica/ that hold results or inputs, not the kit itself.
# Files under .saica/ that are inputs or a rendered page, not the kit itself.
# The event log is NOT in this list: a commit that tracks .saica/events.jsonl or
# .saica/pending.jsonl could replace the record of its own checks.
_KIT_DATA_FILES = {
    ".saica/dashboard.html",
    ".saica/task.md",
    ".saica/session.txt",
    ".saica/final_message.txt",
}
_KIT_WORKFLOWS = {"saica-ci.yml", "saica-ci.yaml"}
# Files that can wire or unwire the hooks; they count only when a changed line names the kit.
_HOOK_CONFIG_RE = re.compile(
    r"(^|/)(\.pre-commit-config\.ya?ml|\.?lefthook(-local)?\.ya?ml)$|^\.(husky|githooks)/"
)
KIT_FILES = (".saica/saica_check.py", ".saica/checks.json")
ALLOW_KIT_CHANGE_ENV = "SAICA_KIT_CHANGE_OK"


def is_kit_path(path: str, hooks_dir: Optional[str] = None) -> bool:
    """True for a file that decides how changes are checked or recorded: the
    runner, its config, helper scripts, prompts, hooks, the event log (everything
    under ``.saica/`` except input files and the rendered dashboard), the kit's CI
    workflow, and files in ``hooks_dir`` (a hooks directory inside the work tree
    that ``core.hooksPath`` points at)."""
    p = path.replace("\\", "/")
    if p.startswith(".saica/"):
        return p not in _KIT_DATA_FILES
    if hooks_dir and p.startswith(hooks_dir.rstrip("/") + "/"):
        return True
    return p.startswith(".github/workflows/") and p.rsplit("/", 1)[-1] in _KIT_WORKFLOWS


def tracked_hooks_dir(root: Path) -> Optional[str]:
    """``core.hooksPath`` when it names a directory inside the work tree, as a
    repository-relative path; else None."""
    try:
        raw = git(["config", "--get", "core.hooksPath"], root, check=False).strip()
    except SaicaError:
        return None
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        rel = path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    rel_s = rel.as_posix()
    return (
        None
        if rel_s in ("", ".") or rel_s.startswith(".git/") or rel_s == ".git"
        else rel_s
    )


def check_kit_tamper(cs: ChangeSet, hooks_dir: Optional[str] = None) -> List[str]:
    """Paths of the supervision kit that the change adds, edits, deletes or renames."""
    hits = {p for p in cs.touched if is_kit_path(p, hooks_dir)}
    for path, fd in cs.diffs.items():
        if path in hits or not _HOOK_CONFIG_RE.search(path.replace("\\", "/")):
            continue
        if any("saica" in text.lower() for _no, text in fd.added + fd.removed):
            hits.add(path)
    return sorted(hits)


def kit_present(root: Path, treeish: Optional[str]) -> bool:
    """True when ``treeish`` already holds the runner or its config."""
    if not treeish:
        return True  # not known: assume the kit was there (the stricter reading)
    return any(
        git_ok(["cat-file", "-e", "%s:%s" % (treeish, p)], root) for p in KIT_FILES
    )


def base_builtin_config(root: Path, treeish: Optional[str]) -> Optional[dict]:
    """The ``builtin`` settings of ``.saica/checks.json`` in ``treeish``, or None."""
    if not treeish:
        return None
    try:
        raw = json.loads(
            git(["cat-file", "blob", "%s:.saica/checks.json" % treeish], root)
        )
        b = raw.get("builtin", {})
        return {
            "enabled": bool(b.get("enabled", True)),
            "blocking": bool(b.get("blocking", False)),
            "tamper_blocking": bool(b.get("tamper_blocking", True)),
        }
    except (SaicaError, ValueError, AttributeError):
        return None


def _hit_list(hits: List[str], sep: str = "; ") -> str:
    more = "" if len(hits) <= 5 else " (+%d more)" % (len(hits) - 5)
    return sep.join(hits[:5]) + more


def run_builtins(
    cs: ChangeSet,
    root: Path,
    tree: Optional[str] = None,
    only: Optional[Set[str]] = None,
) -> List[Tuple[str, str, str, str]]:
    """Return [(tool_id, failure_mode, outcome, detail)] for the built-ins.

    ``tree`` selects the Git tree the dependency lookups read from (see RepoIndex).
    ``only`` limits the run to these tool ids.
    """
    checks = [c for c in BUILTIN_CHECKS if only is None or c[0] in only]
    if not cs.diffs and not cs.files and not cs.touched:
        return [(tid, fm, "skipped", "no changed files") for tid, fm in checks]
    results = []
    index = None
    for tid, fm in checks:
        try:
            if tid == "saica:stub-markers":
                hits = check_stub_markers(cs)
            elif tid == "saica:test-weakening":
                hits = check_test_weakening(cs)
            elif tid == TAMPER_CHECK:
                hits = check_kit_tamper(cs, tracked_hooks_dir(root))
                if hits and not kit_present(root, cs.base):
                    # Nothing was supervising before this change, so nothing was weakened.
                    detail = "kit files added where there was no kit before: "
                    results.append(
                        (tid, fm, "pass", _truncate(detail + _hit_list(hits, ", ")))
                    )
                    continue
                if hits:
                    hits = [
                        "the change edits the supervision kit itself; a person should "
                        "review it: " + _hit_list(hits, ", ")
                    ]
            else:
                if index is None:
                    index = RepoIndex(root, tree)
                hits = check_phantom_imports(cs, index)
        except Exception as exc:  # noqa: BLE001 - a heuristic must never crash a commit
            results.append((tid, fm, "error", _truncate("internal error: %r" % exc)))
            continue
        if hits:
            results.append((tid, fm, "caught", _truncate(_hit_list(hits))))
        else:
            results.append((tid, fm, "pass", ""))
    return results


# ---------------------------------------------------------------------------
# External tools
# ---------------------------------------------------------------------------


def _summarise_output(out: str) -> str:
    lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
    return _truncate("\n".join(lines[-8:]))


def _last_line(out: str) -> str:
    for ln in reversed(out.splitlines()):
        if ln.strip():
            return ln.strip()
    return ""


FILE_TOKENS = ("{files}", "{files_from}")
_CONTEXT_WORDS = {
    "single": "single quotes",
    "double": "double quotes",
    "comment": "a # comment",
    "heredoc": "a command that uses a here-document (<<)",
    "substitution": "a command substitution (backticks or $(...))",
}


def shell_contexts(command: str, token: str) -> List[str]:
    """Where each ``token`` sits in a POSIX shell command: ``plain`` (a word of
    its own), ``single`` / ``double`` (inside quotes), ``comment``, ``heredoc`` or
    ``substitution`` (inside backticks or ``$(...)``).

    Shell quoting of file names only works in the ``plain`` position: inside a
    comment a newline in a name starts a new command, and inside quotes or a
    here-document the name's own quotes end up as text or close the quoting.
    """
    found: List[str] = []
    state = "plain"
    word_start = True
    heredoc = False
    backtick = False  # inside `...`: the shell looks for the closing backtick before it reads quotes
    depth = 0  # nesting of $( ... )
    i, n = 0, len(command)
    while i < n:
        if command.startswith(token, i):
            found.append(
                "substitution" if (backtick or depth) and state == "plain" else state
            )
            i += len(token)
            word_start = False
            continue
        ch = command[i]
        if ch == "`" and state in ("plain", "double"):
            backtick = not backtick
            word_start = False
        elif state == "plain" and command.startswith("$(", i):
            depth += 1
            i += 1
            word_start = True
        elif state == "plain" and ch == ")" and depth:
            depth -= 1
            word_start = True
        elif state == "comment":
            if ch == "\n":
                state, word_start = "plain", True
        elif state == "single":
            if ch == "'":
                state = "plain"
        elif state == "double":
            if ch == "\\" and i + 1 < n:
                i += 1
            elif ch == '"':
                state = "plain"
        elif ch == "\\" and i + 1 < n:
            i += 1
            word_start = False
        elif ch == "'":
            state, word_start = "single", False
        elif ch == '"':
            state, word_start = "double", False
        elif ch == "#" and word_start:
            state = "comment"
        elif ch in " \t\n;&|()<>":
            if command.startswith("<<", i):
                heredoc = True
            word_start = True
        else:
            word_start = False
        i += 1
    if heredoc:
        return ["heredoc" for _ in found]
    return found


def placeholder_problem(command: str) -> Optional[str]:
    """Why ``{files}`` / ``{files_from}`` cannot be filled in safely, or None."""
    for token in FILE_TOKENS:
        for ctx in shell_contexts(command, token):
            if ctx != "plain":
                return (
                    "configuration error: %s must be a word of its own in the command, "
                    "but it is inside %s, where a file name could run as a command. "
                    'Move it out; put explanations in this tool\'s "note"'
                    % (token, _CONTEXT_WORDS[ctx])
                )
    return None


def _kill_group(proc: "subprocess.Popen[bytes]") -> None:
    """Stop the tool and, on POSIX, everything it started (its process group)."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def _run_process(
    command: object, cwd: Path, timeout: float, env: Optional[Dict[str, str]]
) -> Tuple[Optional[int], str, str]:
    """Run ``command``: a string goes through the shell, a list is run directly.
    Returns (exit code or None, output, failure)."""
    kwargs: dict = {}
    if os.name == "posix":
        # Its own session and process group: a timeout can stop the tool's
        # children too, and the tool cannot read the terminal.
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            command,  # type: ignore[arg-type]
            shell=isinstance(
                command, str
            ),  # nosemgrep: subprocess-shell-true -- contract: commands from the repo owner's checks.json may need the shell
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            **kwargs,
        )
    except FileNotFoundError:
        name = command if isinstance(command, str) else command[0]  # type: ignore[index]
        return None, "", "command not found: %s" % name
    except OSError as exc:
        return None, "", "could not start: %s" % exc
    try:
        out, _err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            proc.communicate(timeout=10)
        except (
            Exception
        ):  # noqa: BLE001 - best effort; the timeout is what gets reported
            pass
        return None, "", "timeout after %gs" % timeout
    except BaseException:
        _kill_group(proc)
        raise
    return proc.returncode, out.decode("utf-8", "replace"), ""


_SHELL_CHARS = "|&;<>()$`\\*?[]#~!{}\n"


def plain_argv(command: str) -> Optional[List[str]]:
    """The command as an argument list when it needs no shell, else None.

    A command made of plain words (quotes allowed) is run directly: no shell
    reads the file names, so no quoting can go wrong. Anything with a shell
    operator, a variable, a glob, a ``NAME=value`` prefix or a ``{files}`` glued
    to other text keeps the shell path and its checks.
    """
    if placeholder_problem(command):
        return None  # reported by the shell path
    probe = command
    for t in FILE_TOKENS:
        probe = probe.replace(t, "FILES")
    quote = ""
    for ch in probe:
        if quote == "'":
            if ch == "'":
                quote = ""
        elif quote == '"':
            if ch == '"':
                quote = ""
            elif ch in "$`\\":
                return None
        elif ch in "'\"":
            quote = ch
        elif ch in _SHELL_CHARS:
            return None
    if quote:
        return None
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv or "=" in argv[0]:
        return None
    if any("{files}" in a and a != "{files}" for a in argv):
        return None
    return argv


_NO_MODULE_LINE_RE = re.compile(r"(?:.*[/\\])?python[\w.]*: No module named ([\w.]+)")
_DASH_M_RE = re.compile(r"(?:^|\s)-m\s+([\w.]+)")


def module_missing(command: str, output: str) -> bool:
    """True when ``python -m <tool>`` could not start because the tool is not
    installed: the interpreter's one-line message is the WHOLE output and names
    the module the command asked for. A line like that inside a tool's findings
    (for example a matched source line) is not this."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    if len(lines) != 1:
        return False
    said = _NO_MODULE_LINE_RE.fullmatch(lines[0])
    asked = _DASH_M_RE.search(command)
    return bool(
        said and asked and asked.group(1).split(".")[0] == said.group(1).split(".")[0]
    )


_KEY_ENV_RE = re.compile(r"--api-key-env[=\s]+([A-Za-z_][A-Za-z0-9_]*)")
DEFAULT_KEY_ENV = "SAICA_LLM_API_KEY"


def tool_environment(
    tool: dict, config: dict, env: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """The environment one tool runs with: everything except the model API keys
    of other tools. A key variable (named with ``--api-key-env`` in some command,
    or SAICA_LLM_API_KEY) is passed only to a command that names it, or, for the
    default name, to the reviewer helper."""
    out = dict(os.environ if env is None else env)
    keys = {DEFAULT_KEY_ENV}
    for t in config.get("tools", []):
        keys.update(_KEY_ENV_RE.findall(t.get("command") or ""))
    command = tool.get("command") or ""
    for name in keys:
        named = re.search(
            r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(name), command
        )
        default_user = (
            name == DEFAULT_KEY_ENV
            and "saica_llm_review" in command
            and not _KEY_ENV_RE.search(command)  # it reads the default name
        )
        if not named and not default_user:
            out.pop(name, None)
    return out


def run_tool(
    tool: dict, files: List[str], root: Path, env: Optional[Dict[str, str]] = None
) -> Tuple[str, str, Optional[float]]:
    """Execute one tool in ``root``. Returns (outcome, detail, metric).

    Exit 0 is ``pass`` (``skipped`` when the tool's last line starts with
    ``skipped:``); an exit code in ``caught_exit_codes`` is ``caught``; anything
    else is ``error``: a tool that failed is not a finding.
    """
    command = tool["command"] or ""
    used = [t for t in FILE_TOKENS if t in command]
    argv = plain_argv(command) if os.name == "posix" else None
    if argv is not None and os.sep not in argv[0]:
        search = (os.environ if env is None else env).get("PATH")
        if shutil.which(argv[0], path=search) is None:
            argv = None  # a shell built-in (exit, cd ...) or not installed: the shell decides
    list_dir: Optional[str] = None
    if used and argv is None:
        if os.name == "nt":
            # shlex.quote produces POSIX quoting, which cmd.exe does not honour.
            return (
                "error",
                "configuration error: %s is not supported on native Windows "
                "(file names cannot be quoted safely for cmd.exe); remove it "
                "from this tool's command or run the kit under WSL or another POSIX shell"
                % used[0],
                None,
            )
        problem = placeholder_problem(command)
        if problem:
            return "error", problem, None
    if used and not files:
        return "skipped", "no changed files for %s" % used[0], None
    names = ["./" + f if f.startswith("-") else f for f in files]
    too_long = (
        "too many changed files for {files}: %d paths make a command line of "
        "%d bytes (limit %d), so nothing was checked. Use {files_from}, a file "
        "holding the NUL-separated list, for example: xargs -0 <tool> < {files_from}"
    )
    try:
        if "{files_from}" in command:
            list_dir = tempfile.mkdtemp(prefix="saica-files-")
            list_path = os.path.join(list_dir, "files")
            with open(list_path, "wb") as fh:
                for name in names:
                    fh.write(name.encode("utf-8", "surrogateescape") + b"\0")
        if argv is not None:
            # No shell: every file name is one argument, whatever characters it has.
            run: object = []
            for a in argv:
                if a == "{files}":
                    run.extend(names)  # type: ignore[attr-defined]
                elif list_dir is not None:
                    run.append(a.replace("{files_from}", list_path))  # type: ignore[attr-defined]
                else:
                    run.append(a)  # type: ignore[attr-defined]
            size = sum(len(a.encode("utf-8", "replace")) + 1 for a in run)  # type: ignore[attr-defined]
            if "{files}" in command and size > MAX_COMMAND_BYTES:
                return "error", too_long % (len(files), size, MAX_COMMAND_BYTES), None
        else:
            if "{files}" in command:
                bad = [f for f in files if any(c in f for c in "\n\r\0")]
                if bad:
                    return (
                        "error",
                        "refused: %d changed path(s) contain a newline, carriage return or NUL "
                        "character and cannot be passed through {files} safely in a shell "
                        "command; rename them or use {files_from} (a file holding the "
                        "NUL-separated list)" % len(bad),
                        None,
                    )
                command = command.replace(
                    "{files}", " ".join(shlex.quote(name) for name in names)
                )
                size = len(command.encode("utf-8", "replace"))
                if size > MAX_COMMAND_BYTES:
                    return (
                        "error",
                        too_long % (len(files), size, MAX_COMMAND_BYTES),
                        None,
                    )
            if list_dir is not None:
                command = command.replace("{files_from}", shlex.quote(list_path))
            run = command
        rc, output, failure = _run_process(run, root, tool["timeout_s"], env)
    finally:
        if list_dir is not None:
            shutil.rmtree(list_dir, ignore_errors=True)
    if rc is None:
        return "error", _truncate(failure), None
    metric = None
    if tool.get("metric"):
        m = re.search(tool["metric"]["regex"], output)
        if m:
            try:
                metric = float(m.group(1))
            except (TypeError, ValueError, IndexError):
                metric = None
    last = _last_line(output)
    if rc == 0:
        if last.startswith("skipped:"):
            return "skipped", _truncate(last), metric
        if last.startswith("ok:"):
            return "pass", _truncate(last), metric
        return "pass", _summarise_output(output) if metric is not None else "", metric
    caught_codes = tool.get("caught_exit_codes") or list(DEFAULT_CAUGHT_EXIT_CODES)
    if rc == 1 and module_missing(tool["command"] or "", output):
        # Not a finding: the tool is not installed for this interpreter.
        return "error", _truncate("the command could not run: %s" % last), metric
    if rc in caught_codes:
        if last.startswith("flagged:"):
            return "caught", _truncate(last), metric
        return (
            "caught",
            _truncate("exit %d: %s" % (rc, _summarise_output(output))),
            metric,
        )
    if last.startswith(("error:", "partial:")):  # a kit helper's own result line
        return "error", _truncate(last), metric
    if rc == 127:
        why = "command not found (exit 127)"
    elif rc < 0:
        why = "stopped by signal %d" % -rc
    else:
        why = (
            "exit %d, which is not a finding for this tool (caught_exit_codes: %s), "
            "so it is recorded as a tool failure"
            % (rc, ", ".join(str(c) for c in caught_codes))
        )
    return "error", _truncate("%s: %s" % (why, _summarise_output(output))), metric


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def make_event(
    *,
    meta: dict,
    kit: Optional[str],
    source: str,
    tool_id: Optional[str],
    failure_mode: str,
    outcome: str,
    blocking: bool,
    detail: str = "",
    metric: Optional[float] = None,
    metric_name: Optional[str] = None,
) -> dict:
    return {
        "v": CONTRACT_VERSION,
        "ts": _now(),
        "commit": meta.get("commit", STAGED),
        "commit_ts": meta.get("commit_ts"),
        "subject": meta.get("subject"),
        "agent": meta.get("agent"),
        "kit": kit,
        "source": source,
        "tool_id": tool_id,
        "failure_mode": failure_mode,
        "outcome": outcome,
        "blocking": bool(blocking),
        "detail": _truncate(detail or ""),
        "metric": metric,
        "metric_name": metric_name,
    }


def covered_failure_modes(config: dict) -> Set[str]:
    """Failure modes that a configured tool checks on every commit.

    The built-in heuristics do not count: none of them was scored on
    SAICA-Bench, so a mode they alone watch is still reported as not covered.
    """
    covered: Set[str] = set()
    for t in config["tools"]:
        if t["runs_per_commit"]:
            covered.update(t["failure_modes"])
    return covered


def not_covered_events(config: dict, meta: dict, source: str) -> List[dict]:
    covered = covered_failure_modes(config)
    heuristic = (
        {fm for _tid, fm in BUILTIN_CHECKS} if config["builtin"]["enabled"] else set()
    )
    return [
        make_event(
            meta=meta,
            kit=config["kit"],
            source=source,
            tool_id=None,
            failure_mode=fm,
            outcome="not_covered",
            blocking=False,
            detail="no configured runnable tool covers this failure mode"
            + (
                " (a built-in heuristic watches it; heuristics are not benchmarked "
                "and do not count as coverage)"
                if fm in heuristic
                else ""
            ),
        )
        for fm in FAILURE_MODES
        if fm not in covered
    ]


def evaluate(
    config: dict,
    cs: ChangeSet,
    root: Path,
    meta: dict,
    source: str,
    run_tools: bool = True,
    files_for_tools: Optional[List[str]] = None,
    verbose: bool = True,
    tree: Optional[str] = None,
    tool_root: Optional[Path] = None,
    tool_env: Optional[Dict[str, str]] = None,
) -> List[dict]:
    """Run built-ins and tools for one change set.

    ``tree`` is the Git tree the built-in dependency lookups read from
    (default: index listing + working-tree files). ``tool_root`` / ``tool_env``
    are where and how external tools run (default: ``root``, inherited env).
    """
    kit = config["kit"]
    events: List[dict] = []
    builtin = config["builtin"]
    # A change must not be able to switch off the check that watches the kit:
    # the tamper check also runs when the built-ins were on before this change.
    before = base_builtin_config(root, cs.base)
    only: Optional[Set[str]] = None
    run_builtin = builtin["enabled"]
    if not run_builtin and before and before["enabled"]:
        run_builtin, only = True, {TAMPER_CHECK}
    if run_builtin:
        for tid, fm, outcome, detail in run_builtins(cs, root, tree, only=only):
            blocking = builtin["blocking"] and builtin["enabled"]
            if tid == TAMPER_CHECK:
                # A change to the kit itself stops the commit by default
                # (builtin.tamper_blocking), by the settings in force before the change too.
                blocking = blocking or (
                    builtin["enabled"] and builtin.get("tamper_blocking", True)
                )
                if before and before["enabled"]:
                    blocking = (
                        blocking or before["blocking"] or before["tamper_blocking"]
                    )
                if outcome == "caught" and os.environ.get(ALLOW_KIT_CHANGE_ENV) == "1":
                    blocking = False
                    detail = (
                        _truncate(detail, DETAIL_MAX - 60)
                        + " (allowed by %s=1)" % ALLOW_KIT_CHANGE_ENV
                    )
            events.append(
                make_event(
                    meta=meta,
                    kit=kit,
                    source=source,
                    tool_id=tid,
                    failure_mode=fm,
                    outcome=outcome,
                    blocking=blocking,
                    detail=detail,
                )
            )
    files = cs.files if files_for_tools is None else files_for_tools
    for tool in config["tools"]:
        metric_name = tool["metric"]["name"] if tool.get("metric") else None
        if not tool["runs_per_commit"]:
            outcome, detail, metric = (
                "not_runnable",
                tool.get("note") or "runs_per_commit: false",
                None,
            )
        elif not run_tools:
            outcome, detail, metric = (
                "skipped",
                "replay: tools not run (use --with-tools)",
                None,
            )
        else:
            if verbose:
                print("saica: running %s ..." % tool["id"], file=sys.stderr)
            outcome, detail, metric = run_tool(
                tool,
                files,
                tool_root or root,
                env=tool_environment(tool, config, tool_env),
            )
        for fm in tool["failure_modes"]:
            events.append(
                make_event(
                    meta=meta,
                    kit=kit,
                    source=source,
                    tool_id=tool["id"],
                    failure_mode=fm,
                    outcome=outcome,
                    blocking=tool["blocking"],
                    detail=detail,
                    metric=metric,
                    metric_name=metric_name,
                )
            )
    events.extend(not_covered_events(config, meta, source))
    return events


def append_jsonl(path: Path, events: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False, sort_keys=False) + "\n")


def read_jsonl(path: Path) -> List[dict]:
    if not path.is_file():
        return []
    events = []
    for i, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            _warn("%s:%d: skipping malformed line" % (path, i))
            continue
        if isinstance(ev, dict):
            events.append(ev)
    return events


def blocking_failures(events: List[dict], config: Optional[dict] = None) -> List[dict]:
    """Events that stop a commit: a blocking check that caught something, and a
    check that could not run on the change (``error``) when its ``on_error`` is
    ``block`` (the default for a blocking check): it did not vouch for the change."""
    on_error = {
        t["id"]: t.get("on_error", "pass") for t in (config or {}).get("tools", [])
    }
    return [
        e
        for e in events
        if (e["outcome"] == "caught" and e["blocking"])
        or (e["outcome"] == "error" and on_error.get(e["tool_id"]) == "block")
    ]


def print_summary(events: List[dict], header: str) -> None:
    print(header, file=sys.stderr)
    seen = set()
    for e in events:
        if e["outcome"] == "not_covered":
            continue
        key = (e["tool_id"], e["outcome"])
        if key in seen:
            continue
        seen.add(key)
        flag = {"caught": "CAUGHT", "error": "ERROR"}.get(e["outcome"], e["outcome"])
        line = "  %-22s %-12s" % (e["tool_id"], flag)
        if e["blocking"] and e["outcome"] in ("caught", "error"):
            line += " [blocking]"
        if str(e["tool_id"]).startswith("saica:"):
            line += " (%s)" % BUILTIN_NOTE
        if e["outcome"] in ("caught", "error") and e["detail"]:
            line += "  " + e["detail"].splitlines()[0][:160]
        print(line, file=sys.stderr)
    gaps = [e["failure_mode"] for e in events if e["outcome"] == "not_covered"]
    if gaps:
        print("  no configured tool covers: " + ", ".join(gaps), file=sys.stderr)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


class Ctx:
    def __init__(self, args: argparse.Namespace) -> None:
        self.root = find_repo_root()
        self.saica = self.root / ".saica"
        self.config_path = (
            Path(args.config)
            if getattr(args, "config", None)
            else self.saica / "checks.json"
        )
        if not self.config_path.is_absolute():
            self.config_path = Path.cwd() / self.config_path
        self.config_explicit = bool(getattr(args, "config", None))
        self.events_explicit = bool(getattr(args, "events", None))
        self.events_path = (
            Path(args.events) if self.events_explicit else self.saica / "events.jsonl"
        )
        if not self.events_path.is_absolute():
            self.events_path = Path.cwd() / self.events_path
        self.pending_path = self.saica / "pending.jsonl"

    def config(self) -> dict:
        return load_config(self.config_path)

    def staged_config(self, head: Optional[str]) -> dict:
        """The config a staged change is judged by: the committed one (HEAD), so
        that neither an unstaged edit nor the change itself can weaken its own
        checks. Before the kit's first commit: the staged file, then the
        working-tree file. ``--config`` always wins."""
        if self.config_explicit:
            return self.config()
        for treeish, where in ((head, "HEAD"), ("", "the index")):
            if treeish is None:
                continue
            spec = "%s:.saica/checks.json" % treeish
            if not git_ok(["cat-file", "-e", spec], self.root):
                continue
            label = ".saica/checks.json in %s" % where
            try:
                raw = json.loads(git(["cat-file", "blob", spec], self.root))
            except ValueError as exc:
                raise SaicaError("%s is not valid JSON: %s" % (label, exc))
            return parse_config(raw, label)
        return self.config()

    def check_log(self, path: Path, explicit: bool = False) -> None:
        """Refuse an event log a commit could forge or throw away: a symbolic
        link, a file tracked by git, or (for the default place) a path that leads
        out of the repository."""
        if path.is_symlink():
            raise SaicaError(
                "%s is a symbolic link; the event log must be a regular file, or the "
                "record of the checks could be sent anywhere. Remove the link" % path
            )
        try:
            rel = (path.parent.resolve() / path.name).relative_to(self.root.resolve())
        except (ValueError, OSError):
            if explicit:
                return  # e.g. a CI temp folder named with --events
            raise SaicaError(
                "%s leads outside the repository (is .saica a symbolic link?); the event "
                "log must be a regular file inside it" % path
            )
        if git_ok(["ls-files", "--error-unmatch", "--", rel.as_posix()], self.root):
            raise SaicaError(
                "%s is tracked by git, so a commit could replace the record of its own "
                "checks. Run `git rm --cached %s` and add it to .gitignore"
                % (rel.as_posix(), rel.as_posix())
            )

    def pending_meta_path(self) -> Path:
        """Sidecar for pending.jsonl (snapshot tree + old HEAD), kept in the git dir.

        It lives outside the work tree so it needs no .gitignore entry, and
        outside pending.jsonl so pending lines stay plain contract events.
        """
        p = Path(git(["rev-parse", "--git-path", PENDING_META_NAME], self.root).strip())
        return p if p.is_absolute() else self.root / p


PENDING_META_NAME = "saica-pending.json"


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def cmd_run(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    if args.staged:
        meta_path = ctx.pending_meta_path()
        ctx.check_log(ctx.pending_path)
        ctx.check_log(ctx.events_path, ctx.events_explicit)
        _discard(ctx.pending_path)  # leftovers from an aborted commit
        _discard(meta_path)
        source = args.source or "pre-commit"
        snapshot = staged_snapshot(ctx.root)
        tree, old_head = snapshot
        config = ctx.staged_config(
            old_head
        )  # the committed config, not the change's own
        cs = staged_changeset(ctx.root, snapshot)
        tmp_base: Optional[Path] = None
        tool_root: Optional[Path] = None
        tool_env: Optional[Dict[str, str]] = None
        try:
            if any(t["runs_per_commit"] for t in config["tools"]):
                tmp_base, tool_root, tool_env = checkout_tree(ctx.root, tree)
                if (
                    not ctx.config_explicit
                    and old_head
                    and kit_present(ctx.root, old_head)
                ):
                    # helper scripts and prompts: the committed ones too
                    overlay_kit(ctx.root, old_head, tool_root, tmp_base)
            events = evaluate(
                config,
                cs,
                ctx.root,
                {"commit": STAGED},
                source,
                tree=tree,
                tool_root=tool_root,
                tool_env=tool_env,
            )
        finally:
            if tmp_base is not None:
                shutil.rmtree(str(tmp_base), ignore_errors=True)
        if staged_snapshot(ctx.root) != snapshot:
            raise SaicaError(
                "the index or HEAD changed while the checks were running; "
                "results were discarded. Run the checks again."
            )
        append_jsonl(ctx.pending_path, events)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(
                {
                    "v": CONTRACT_VERSION,
                    "tree": tree,
                    "head": old_head or "",
                    "pending_sha256": _file_digest(ctx.pending_path),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        label = "staged changes"
    else:
        config = ctx.config()
        ctx.check_log(ctx.events_path, ctx.events_explicit)
        sha = resolve_commit(ctx.root, args.commit)
        source = args.source or "manual"
        cs = commit_changeset(ctx.root, sha)
        events = evaluate(
            config, cs, ctx.root, commit_info(ctx.root, sha), source, tree=sha
        )
        append_jsonl(ctx.events_path, events)
        label = sha[:12]
    print_summary(events, "saica: checks for %s (%s)" % (label, source))
    blockers = blocking_failures(events, config)
    if blockers and not args.no_block:
        caught = sorted({e["tool_id"] for e in blockers if e["outcome"] == "caught"})
        failed = sorted({e["tool_id"] for e in blockers if e["outcome"] == "error"})
        if caught:
            print(
                "saica: BLOCKED by %s. Fix the findings above and try again."
                % ", ".join(caught),
                file=sys.stderr,
            )
        if failed:
            print(
                "saica: BLOCKED: %s could not run on this change (see ERROR above), and a "
                "blocking check that did not run does not let a commit through. Fix the cause, "
                'or set "on_error": "pass" for that check in .saica/checks.json.'
                % ", ".join(failed),
                file=sys.stderr,
            )
        if TAMPER_CHECK in caught:
            print(
                "saica: this change edits the supervision kit itself. If that is intended, "
                "commit it on its own with %s=1 (it is still recorded)."
                % ALLOW_KIT_CHANGE_ENV,
                file=sys.stderr,
            )
        return 1
    return 0


def cmd_stamp(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    if not ctx.pending_path.is_file() and not ctx.pending_path.is_symlink():
        return 0
    ctx.check_log(ctx.pending_path)
    ctx.check_log(ctx.events_path, ctx.events_explicit)
    meta_path = ctx.pending_meta_path()
    reason = None
    snap: object = None
    try:
        snap = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reason = "no staged snapshot was recorded for them"
    if reason is None and not (
        isinstance(snap, dict)
        and isinstance(snap.get("tree"), str)
        and snap["tree"]
        and isinstance(snap.get("head"), str)
    ):
        reason = "the recorded staged snapshot is malformed"
    head = resolve_commit(ctx.root, "HEAD")
    if reason is None:
        assert isinstance(snap, dict)
        parents = git(["rev-list", "--parents", "-n", "1", head], ctx.root).split()
        first_parent = parents[1] if len(parents) > 1 else ""  # "" = root commit
        commit_tree = git(["rev-parse", "--verify", head + "^{tree}"], ctx.root).strip()
        if snap.get("pending_sha256") != _file_digest(ctx.pending_path):
            reason = "pending.jsonl does not belong to the recorded staged snapshot"
        elif snap["tree"] != commit_tree:
            reason = "HEAD's tree is not the tree that was checked"
        elif snap["head"] != first_parent:
            reason = "HEAD's first parent is not the commit the check was based on"
    if reason is not None:
        # Results for some other change set must never be attributed to HEAD.
        _discard(ctx.pending_path)
        _discard(meta_path)
        _warn(
            "pending events NOT stamped with %s: %s; they were discarded"
            % (head[:12], reason)
        )
        return 0
    pending = read_jsonl(ctx.pending_path)
    meta = commit_info(ctx.root, head)
    stamped = []
    for ev in pending:
        if ev.get("commit") != STAGED:
            continue
        ev.update(meta)
        stamped.append(ev)
    append_jsonl(ctx.events_path, stamped)
    _discard(ctx.pending_path)
    _discard(meta_path)
    print(
        "saica: stamped %d events with %s" % (len(stamped), meta["commit"][:12]),
        file=sys.stderr,
    )
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    config = ctx.config()
    if args.last < 1:
        raise SaicaError("--last must be >= 1")
    ctx.check_log(ctx.events_path, ctx.events_explicit)
    shas = git(["rev-list", "--max-count=%d" % args.last, "HEAD"], ctx.root).split()
    done = {
        e.get("commit")
        for e in read_jsonl(ctx.events_path)
        if e.get("source") == "replay"
    }
    total = 0
    for sha in reversed(shas):
        if sha in done:
            print("saica: %s already replayed, skipping" % sha[:12], file=sys.stderr)
            continue
        cs = commit_changeset(ctx.root, sha)
        files_now = [f for f in cs.files if (ctx.root / f).exists()]
        events = evaluate(
            config,
            cs,
            ctx.root,
            commit_info(ctx.root, sha),
            "replay",
            run_tools=args.with_tools,
            files_for_tools=files_now,
            verbose=False,
            tree=sha,
        )
        append_jsonl(ctx.events_path, events)
        caught = sum(1 for e in events if e["outcome"] == "caught")
        print("saica: replayed %s  caught=%d" % (sha[:12], caught), file=sys.stderr)
        total += len(events)
    print("saica: wrote %d events to %s" % (total, ctx.events_path), file=sys.stderr)
    return 0


_EVENTS_TAG_RE = re.compile(
    r"(<script\b[^>]*\bid=[\"']saica-events[\"'][^>]*>)(.*?)(</script>)", re.S | re.I
)


def embed_events(template: str, events: List[dict]) -> str:
    payload = json.dumps(events, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/").replace("<!--", "\\u003c!--")
    if not _EVENTS_TAG_RE.search(template):
        raise SaicaError(
            'dashboard template has no <script id="saica-events" type="application/json"> tag'
        )
    return _EVENTS_TAG_RE.sub(
        lambda m: m.group(1) + payload + m.group(3), template, count=1
    )


def find_template(explicit: Optional[str]) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise SaicaError("template not found: %s" % p)
        return p
    here = Path(__file__).resolve().parent
    for cand in (here / "dashboard.template.html", here / "dashboard.html"):
        if cand.is_file():
            return cand
    raise SaicaError(
        "dashboard template not found next to %s (expected dashboard.template.html)"
        % Path(__file__).name
    )


def cmd_dashboard(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    template_path = find_template(args.template)
    events = read_jsonl(ctx.events_path)
    html = embed_events(template_path.read_text(encoding="utf-8"), events)
    out = Path(args.out) if args.out else ctx.saica / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print("saica: wrote %s (%d events)" % (out, len(events)), file=sys.stderr)
    return 0


PRE_COMMIT_HOOK = r"""#!/bin/sh
# SAICA supervision kit: pre-commit hook (runs .saica/saica_check.py).
# Installed by: python3 .saica/saica_check.py install-hooks
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0
runner=".saica/saica_check.py"
warn() {
  echo "" >&2
  echo "##################################################################" >&2
  echo "## SAICA WARNING: $1" >&2
  echo "## This commit was NOT checked by the SAICA supervision kit." >&2
  echo "##################################################################" >&2
  echo "" >&2
}
if [ ! -f "$runner" ]; then
  warn "$runner is missing."
  exit 0
fi
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY=$cand
    break
  fi
done
if [ -z "$PY" ]; then
  warn "no Python 3.9 or newer found on PATH (tried python3, python)."
  exit 0
fi
exec "$PY" "$runner" run --staged --source pre-commit
"""

POST_COMMIT_HOOK = r"""#!/bin/sh
# SAICA supervision kit: post-commit hook (stamps pending results with the new sha).
# Installed by: python3 .saica/saica_check.py install-hooks
# Never fails: the commit already exists.
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0
runner=".saica/saica_check.py"
[ -f "$runner" ] || exit 0
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY=$cand
    break
  fi
done
if [ -z "$PY" ]; then
  echo "SAICA WARNING: no Python 3.9 or newer found; results were not stamped." >&2
  exit 0
fi
"$PY" "$runner" stamp || echo "SAICA WARNING: stamp failed; see message above." >&2
exit 0
"""


def _hook_source(name: str) -> str:
    here = Path(__file__).resolve().parent
    candidate = here / "hooks" / name
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return _builtin_hook(name)


def _builtin_hook(name: str) -> str:
    return PRE_COMMIT_HOOK if name == "pre-commit" else POST_COMMIT_HOOK


# sha256 of hook files that earlier versions of the kit installed (LF line
# endings). They are replaced without --force, like the current ones.
EARLIER_KIT_HOOKS = {
    "765120e7e5b238eedf2f12cb1342637f9345af17b82563b73d0265dff074738d",  # pre-commit, 2026-11-19
    "6754127dd9f73a86b8915c0a7ba8aeaf7a4ff048e59057e274e35f6e71140080",  # post-commit, 2026-11-19
}


def _is_exact_hook(existing: bytes, candidates: List[str]) -> bool:
    """True only if the file is byte-for-byte a kit hook (LF or CRLF line endings)."""
    for text in candidates:
        lf = text.replace("\r\n", "\n").encode("utf-8")
        if existing == lf or existing == lf.replace(b"\n", b"\r\n"):
            return True
    return False


def _is_earlier_kit_hook(existing: bytes) -> bool:
    lf = existing.replace(b"\r\n", b"\n")
    return hashlib.sha256(lf).hexdigest() in EARLIER_KIT_HOOKS


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


def _backup_hook(target: Path, name: str, data: bytes) -> Path:
    """Save the hook being replaced under a new name; never overwrites an earlier backup."""
    n = 0
    while True:
        suffix = ".saica-backup" if n == 0 else ".saica-backup.%d" % n
        backup = target.with_name(name + suffix)
        try:
            with open(str(backup), "xb") as fh:  # exclusive create
                fh.write(data)
        except FileExistsError:
            n += 1
            continue
        try:
            shutil.copymode(str(target), str(backup))
        except OSError:
            pass
        return backup


def cmd_install_hooks(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    hooks_dir = Path(git(["rev-parse", "--git-path", "hooks"], ctx.root).strip())
    if not hooks_dir.is_absolute():
        hooks_dir = ctx.root / hooks_dir
    git_dir = Path(git(["rev-parse", "--git-common-dir"], ctx.root).strip())
    if not git_dir.is_absolute():
        git_dir = ctx.root / git_dir
    if not (_is_inside(hooks_dir, git_dir) or _is_inside(hooks_dir, ctx.root)):
        # core.hooksPath set globally (or to a shared folder): hooks written
        # there would run in every repository that uses the same folder.
        print(
            "saica: refusing to install: this repository's hooks directory is\n"
            "  %s\n"
            "which is outside the repository (core.hooksPath points there). Hooks "
            "installed there would run in every repository that shares it.\n"
            "Give this repository its own hooks directory and run install-hooks again:\n"
            "  git config --local core.hooksPath .git/hooks\n"
            "or add these calls to the shared hooks yourself:\n"
            "  pre-commit:   python3 .saica/saica_check.py run --staged --source pre-commit\n"
            "  post-commit:  python3 .saica/saica_check.py stamp" % hooks_dir,
            file=sys.stderr,
        )
        return 1
    hooks_dir.mkdir(parents=True, exist_ok=True)
    uses_framework = (ctx.root / ".pre-commit-config.yaml").is_file()
    rc = 0
    for name in ("pre-commit", "post-commit"):
        target = hooks_dir / name
        content = _hook_source(name)
        if target.exists():
            existing_bytes = target.read_bytes()
            existing = existing_bytes.decode("utf-8", "replace")
            identical = _is_exact_hook(existing_bytes, [content])
            is_kit = _is_exact_hook(
                existing_bytes, [content, _builtin_hook(name)]
            ) or _is_earlier_kit_hook(existing_bytes)
            if not is_kit and not args.force:
                print(
                    "saica: refusing to overwrite existing %s (not an exact kit hook). "
                    "Use --force (a backup copy is kept)." % target,
                    file=sys.stderr,
                )
                if uses_framework and "pre-commit" in existing:
                    print(
                        "saica: this repo uses the pre-commit framework; add a `local` hook instead:\n"
                        "  - repo: local\n    hooks:\n      - id: saica\n        name: saica checks\n"
                        "        entry: python3 .saica/saica_check.py run --staged\n"
                        "        language: system\n        pass_filenames: false\n"
                        "      - id: saica-stamp\n        name: saica stamp\n"
                        "        entry: python3 .saica/saica_check.py stamp\n"
                        "        language: system\n        pass_filenames: false\n"
                        "        always_run: true\n        stages: [post-commit]",
                        file=sys.stderr,
                    )
                rc = 1
                continue
            if args.force and not identical:
                backup = _backup_hook(target, name, existing_bytes)
                print("saica: backed up %s -> %s" % (target, backup), file=sys.stderr)
        target.write_text(content, encoding="utf-8")
        mode = target.stat().st_mode
        target.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print("saica: installed %s" % target, file=sys.stderr)
    if not (ctx.saica / "saica_check.py").is_file():
        _warn(
            "hooks call .saica/saica_check.py, which does not exist yet; copy the runner there"
        )
    return rc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="saica_check.py",
        description="SAICA supervision kit: run per-commit checks and log events (contract v1).",
    )
    p.add_argument(
        "--config",
        help="path to checks.json (default: <repo>/.saica/checks.json; for run --staged "
        "the committed version of that file)",
    )
    p.add_argument(
        "--events",
        metavar="PATH",
        help="event log to write and read (default: <repo>/.saica/events.jsonl). CI "
        "writes it outside the checkout so that a commit cannot replace it",
    )
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")
    sub.required = True

    r = sub.add_parser(
        "run",
        help="check staged changes or a commit",
        description=(
            "Run built-in checks and configured tools. With --staged, tools run in a "
            "temporary checkout of the index (unstaged and untracked files are not there; "
            "SAICA_REPO_ROOT points at the real repository) with {files} = the staged files. "
            "With --commit, tools run against the current working tree with {files} = the "
            "commit's files; check the commit out first if it is not HEAD (saica-ci.yml does). "
            "Built-in dependency lookups always read the checked tree itself."
        ),
    )
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--staged",
        action="store_true",
        help="check the index (pre-commit); writes pending.jsonl",
    )
    g.add_argument(
        "--commit", metavar="SHA", help="check an existing commit; writes events.jsonl"
    )
    r.add_argument(
        "--source",
        choices=SOURCES,
        help="event source (default: pre-commit for --staged, manual for --commit)",
    )
    r.add_argument(
        "--no-block",
        action="store_true",
        help="always exit 0 even if a blocking check caught",
    )
    r.set_defaults(func=cmd_run)

    s = sub.add_parser(
        "stamp",
        help="post-commit: move pending events to events.jsonl with HEAD sha",
        description=(
            "Stamp pending events with HEAD, but only if HEAD's tree is the staged tree "
            "that was checked and HEAD's first parent is the commit it was checked against "
            "(none for a root commit). Otherwise the pending events are discarded with a warning."
        ),
    )
    s.set_defaults(func=cmd_stamp)

    rp = sub.add_parser(
        "replay",
        help="run built-in checks over recent history",
        description=(
            "Run the built-in checks over the last N commits (oldest first), computing each "
            "commit's diff against its first parent. Configured tools are recorded as 'skipped' "
            "unless --with-tools is given. LIMITATION: --with-tools runs each tool command "
            "against the CURRENT working tree, substituting that commit's changed files "
            "(those that still exist) for {files}; it does not check out historical trees, so "
            "tool results only approximate what the tool would have said at the time. "
            "Commits that already have replay events are skipped."
        ),
    )
    rp.add_argument(
        "--last",
        type=int,
        default=30,
        metavar="N",
        help="number of commits (default 30)",
    )
    rp.add_argument(
        "--with-tools",
        action="store_true",
        help="also run tools (against the current tree; see above)",
    )
    rp.set_defaults(func=cmd_replay)

    d = sub.add_parser(
        "dashboard", help="write .saica/dashboard.html with events embedded"
    )
    d.add_argument(
        "--template",
        help="template path (default: dashboard.template.html, then dashboard.html, next to this script)",
    )
    d.add_argument("--out", help="output path (default: <repo>/.saica/dashboard.html)")
    d.set_defaults(func=cmd_dashboard)

    ih = sub.add_parser(
        "install-hooks", help="install pre-commit and post-commit git hooks"
    )
    ih.add_argument(
        "--force",
        action="store_true",
        help="overwrite hooks that are not exact kit hooks (a new .saica-backup copy is kept)",
    )
    ih.set_defaults(func=cmd_install_hooks)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SaicaError as exc:
        print("saica: error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
