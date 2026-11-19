#!/usr/bin/env python3
"""SAICA supervision kit: per-commit check runner (contract v1).

Runs the supervision tools configured in ``.saica/checks.json`` plus three
cheap built-in diff heuristics against a commit (or the staged changes),
and records one JSON event per (commit, tool, failure mode) in
``.saica/events.jsonl``. See the kit README for the full contract.

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
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
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
)

DETAIL_MAX = 500
DEFAULT_TIMEOUT_S = 300
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
HOOK_MARKER = "saica_check.py"
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


def git(args: List[str], cwd: Path, check: bool = True) -> str:
    """Run ``git`` and return stdout (decoded, errors replaced)."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise SaicaError("git is not installed or not on PATH")
    out = proc.stdout.decode("utf-8", "replace")
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise SaicaError("git %s failed: %s" % (" ".join(args), err))
    return out


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
                "blocking": bool(t.get("blocking", False)),
                "timeout_s": float(timeout),
                "metric": metric,
                "note": t.get("note"),
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
    def __init__(self, files: List[str], diffs: Dict[str, FileDiff]) -> None:
        self.files = files  # existing (added/copied/modified/renamed) paths
        self.diffs = diffs


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _unquote_path(p: str) -> str:
    p = p.strip()
    if p.startswith('"') and p.endswith('"'):
        try:
            p = json.loads(p)
        except ValueError:
            p = p[1:-1]
    return p


def parse_unified_diff(text: str) -> Dict[str, FileDiff]:
    """Parse ``git diff -U0`` output into per-file added/removed lines."""
    diffs: Dict[str, FileDiff] = {}
    current: Optional[FileDiff] = None
    in_header = False
    old_no = new_no = 0
    old_path: Optional[str] = None
    for line in text.splitlines():
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


_DIFF_FLAGS = ["-U0", "--no-color", "--no-ext-diff", "--no-renames"]


def staged_changeset(root: Path) -> ChangeSet:
    names = git(["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"], root)
    files = [n for n in names.split("\0") if n]
    text = git(["diff", "--cached"] + _DIFF_FLAGS, root)
    return ChangeSet(files, parse_unified_diff(text))


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
    base = parents[1] if len(parents) > 1 else EMPTY_TREE
    names = git(["diff", "--name-only", "--diff-filter=ACMR", "-z", base, sha], root)
    files = [n for n in names.split("\0") if n]
    text = git(["diff"] + _DIFF_FLAGS + [base, sha], root)
    return ChangeSet(files, parse_unified_diff(text))


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
    """Local module names and declared dependencies of the repository."""

    def __init__(self, root: Path) -> None:
        self.root = root
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


def run_builtins(cs: ChangeSet, root: Path) -> List[Tuple[str, str, str, str]]:
    """Return [(tool_id, failure_mode, outcome, detail)] for the built-ins."""
    if not cs.diffs and not cs.files:
        return [(tid, fm, "skipped", "no changed files") for tid, fm in BUILTIN_CHECKS]
    results = []
    index = None
    for tid, fm in BUILTIN_CHECKS:
        try:
            if tid == "saica:stub-markers":
                hits = check_stub_markers(cs)
            elif tid == "saica:test-weakening":
                hits = check_test_weakening(cs)
            else:
                if index is None:
                    index = RepoIndex(root)
                hits = check_phantom_imports(cs, index)
        except Exception as exc:  # noqa: BLE001 - a heuristic must never crash a commit
            results.append((tid, fm, "error", _truncate("internal error: %r" % exc)))
            continue
        if hits:
            more = "" if len(hits) <= 5 else " (+%d more)" % (len(hits) - 5)
            results.append((tid, fm, "caught", _truncate("; ".join(hits[:5]) + more)))
        else:
            results.append((tid, fm, "pass", ""))
    return results


# ---------------------------------------------------------------------------
# External tools
# ---------------------------------------------------------------------------


def _summarise_output(out: str) -> str:
    lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
    return _truncate("\n".join(lines[-8:]))


def run_tool(
    tool: dict, files: List[str], root: Path
) -> Tuple[str, str, Optional[float]]:
    """Execute one tool. Returns (outcome, detail, metric)."""
    command = tool["command"] or ""
    if "{files}" in command:
        if not files:
            return "skipped", "no changed files for {files}", None
        command = command.replace("{files}", " ".join(shlex.quote(f) for f in files))
    try:
        proc = subprocess.run(
            command,
            shell=True,  # nosemgrep: subprocess-shell-true -- contract: commands from the repo owner's checks.json run through the shell
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=tool["timeout_s"],
        )
    except subprocess.TimeoutExpired:
        return "error", "timeout after %gs" % tool["timeout_s"], None
    except OSError as exc:
        return "error", _truncate("could not start: %s" % exc), None
    output = proc.stdout.decode("utf-8", "replace")
    metric = None
    if tool.get("metric"):
        m = re.search(tool["metric"]["regex"], output)
        if m:
            try:
                metric = float(m.group(1))
            except (TypeError, ValueError, IndexError):
                metric = None
    rc = proc.returncode
    if rc == 0:
        return "pass", _summarise_output(output) if metric is not None else "", metric
    if rc == 127:
        return (
            "error",
            _truncate("command not found (exit 127): %s" % _summarise_output(output)),
            metric,
        )
    return "caught", _truncate("exit %d: %s" % (rc, _summarise_output(output))), metric


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
    covered: Set[str] = set()
    for t in config["tools"]:
        if t["runs_per_commit"]:
            covered.update(t["failure_modes"])
    if config["builtin"]["enabled"]:
        covered.update(fm for _tid, fm in BUILTIN_CHECKS)
    return covered


def not_covered_events(config: dict, meta: dict, source: str) -> List[dict]:
    covered = covered_failure_modes(config)
    return [
        make_event(
            meta=meta,
            kit=config["kit"],
            source=source,
            tool_id=None,
            failure_mode=fm,
            outcome="not_covered",
            blocking=False,
            detail="no configured runnable tool or built-in covers this failure mode",
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
) -> List[dict]:
    kit = config["kit"]
    events: List[dict] = []
    if config["builtin"]["enabled"]:
        for tid, fm, outcome, detail in run_builtins(cs, root):
            events.append(
                make_event(
                    meta=meta,
                    kit=kit,
                    source=source,
                    tool_id=tid,
                    failure_mode=fm,
                    outcome=outcome,
                    blocking=config["builtin"]["blocking"],
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
            outcome, detail, metric = run_tool(tool, files, root)
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


def blocking_failures(events: List[dict]) -> List[dict]:
    return [e for e in events if e["outcome"] == "caught" and e["blocking"]]


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
        if e["blocking"] and e["outcome"] == "caught":
            line += " [blocking]"
        if e["outcome"] in ("caught", "error") and e["detail"]:
            line += "  " + e["detail"].splitlines()[0][:160]
        print(line, file=sys.stderr)
    gaps = [e["failure_mode"] for e in events if e["outcome"] == "not_covered"]
    if gaps:
        print("  not covered: " + ", ".join(gaps), file=sys.stderr)


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
        self.events_path = self.saica / "events.jsonl"
        self.pending_path = self.saica / "pending.jsonl"

    def config(self) -> dict:
        return load_config(self.config_path)


def cmd_run(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    if args.staged:
        if ctx.pending_path.exists():
            ctx.pending_path.unlink()  # leftovers from an aborted commit
        config = ctx.config()
        source = args.source or "pre-commit"
        cs = staged_changeset(ctx.root)
        events = evaluate(config, cs, ctx.root, {"commit": STAGED}, source)
        append_jsonl(ctx.pending_path, events)
        label = "staged changes"
    else:
        config = ctx.config()
        sha = resolve_commit(ctx.root, args.commit)
        source = args.source or "manual"
        cs = commit_changeset(ctx.root, sha)
        events = evaluate(config, cs, ctx.root, commit_info(ctx.root, sha), source)
        append_jsonl(ctx.events_path, events)
        label = sha[:12]
    print_summary(events, "saica: checks for %s (%s)" % (label, source))
    blockers = blocking_failures(events)
    if blockers and not args.no_block:
        tools = sorted({e["tool_id"] for e in blockers})
        print(
            "saica: BLOCKED by %s. Fix the findings above and try again."
            % ", ".join(tools),
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_stamp(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    if not ctx.pending_path.is_file():
        return 0
    pending = read_jsonl(ctx.pending_path)
    meta = commit_info(ctx.root, resolve_commit(ctx.root, "HEAD"))
    stamped = []
    for ev in pending:
        if ev.get("commit") != STAGED:
            continue
        ev.update(meta)
        stamped.append(ev)
    append_jsonl(ctx.events_path, stamped)
    ctx.pending_path.unlink()
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
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1 && python -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
  PY=python
fi
if [ -z "$PY" ]; then
  warn "python3 not found on PATH."
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
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
fi
if [ -z "$PY" ]; then
  echo "SAICA WARNING: python3 not found; results were not stamped." >&2
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
    return PRE_COMMIT_HOOK if name == "pre-commit" else POST_COMMIT_HOOK


def cmd_install_hooks(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    hooks_dir = Path(git(["rev-parse", "--git-path", "hooks"], ctx.root).strip())
    if not hooks_dir.is_absolute():
        hooks_dir = ctx.root / hooks_dir
    hooks_dir.mkdir(parents=True, exist_ok=True)
    uses_framework = (ctx.root / ".pre-commit-config.yaml").is_file()
    rc = 0
    for name in ("pre-commit", "post-commit"):
        target = hooks_dir / name
        content = _hook_source(name)
        if target.exists():
            existing = target.read_text(encoding="utf-8", errors="replace")
            if HOOK_MARKER not in existing and not args.force:
                print(
                    "saica: refusing to overwrite existing %s (not ours). Use --force."
                    % target,
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
            if HOOK_MARKER not in existing:
                backup = target.with_name(name + ".saica-backup")
                shutil.copy2(str(target), str(backup))
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
        "--config", help="path to checks.json (default: <repo>/.saica/checks.json)"
    )
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")
    sub.required = True

    r = sub.add_parser(
        "run",
        help="check staged changes or a commit",
        description=(
            "Run built-in checks and configured tools. Tools always run against the "
            "current working tree (with {files} = the staged files or the commit's files); "
            "for --commit, check the commit out first if it is not HEAD (saica-ci.yml does)."
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
        "stamp", help="post-commit: move pending events to events.jsonl with HEAD sha"
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
        help="overwrite foreign hooks (a .saica-backup copy is kept)",
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
