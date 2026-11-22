"""JSONL prevention-event log.

One JSON object per line under ``<repo>/.saica/prevention_log/<date>.jsonl``
(gitignored, per developer). Fields: ``ts``, ``tool_id``, ``failure_mode``,
``mechanism``, ``detail``, ``invoked_by``, ``recorded_by`` and, for hook
events, ``decision``.

``recorded_by`` says who wrote the line, which decides what the line is
worth as data:

* ``"hook"`` — written by ``.claude/hooks/pretool_guard.py`` at the moment
  it denied a tool call or asked about one. This is an observation.
* ``"cli"`` — typed in through ``python -m pipeline.supervision log`` by a
  person or by an agent following ``CLAUDE.md``. This is a self-report.

Lines written before 2026-11-21 have no ``recorded_by``. All of them came
from the CLI (the hook of that time could not fire: it waited for a
``decision`` field that a PreToolUse input never carries), although twelve
of them say ``invoked_by: claude-code-hook``. :func:`read_events` returns
them with ``recorded_by: "cli"`` and leaves the files untouched.

Design constraints:

- stdlib only (no ``pydantic``, no ``requests``)
- append only; idempotent within the same second on
  (ts, tool_id, mechanism, detail)
- the failure-mode id is not checked against the KG here
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Repo-root detection
# ---------------------------------------------------------------------------

_MARKERS = (".git", "pyproject.toml", "pipeline")


def _find_repo_root(start: Path | None = None) -> Path:
    """Walk upward from *start* (or this file) until a repo marker is found.

    Falls back to the current working directory if nothing matches — which
    keeps the function total and lets tests pass an explicit ``log_dir``.
    """

    here = (start or Path(__file__)).resolve()
    if here.is_file():
        here = here.parent
    for candidate in (here, *here.parents):
        for marker in _MARKERS:
            if (candidate / marker).exists():
                return candidate
    return Path.cwd()


REPO_ROOT = _find_repo_root()
LOG_DIR_DEFAULT = REPO_ROOT / ".saica" / "prevention_log"

# Who may write a line: the hook process itself, or the command line.
RECORDERS = ("hook", "cli")


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp with a literal ``Z`` suffix (no offset)."""

    return (
        datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _date_bucket(ts_iso: str) -> str:
    """Return the ``YYYY-MM-DD`` slice for the date-bucketed filename."""

    return ts_iso.split("T", 1)[0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_prevention(
    *,
    tool_id: str,
    failure_mode: str,
    mechanism: str,
    detail: str = "",
    invoked_by: str = "",
    log_dir: Path | None = None,
    recorded_by: str = "cli",
    decision: str | None = None,
) -> Path:
    """Append a prevention event to the date-bucketed JSONL log.

    Parameters
    ----------
    tool_id:
        SAICA-KG tool identifier (matches a ``data/tools/<id>.yml``) or the
        free-form id of an ad-hoc supervisor (e.g. ``"claude-md"``).
    failure_mode:
        One of the 11 SAICA failure-mode ids (matches
        ``data/failure_modes/<id>.yml``). Not validated against the KG here
        — keeping this module stdlib-only — but the CLI surfaces typos via
        the JSONL itself.
    mechanism:
        Short verb phrase, e.g. ``"blocked-commit-via-pre-commit"``.
    detail:
        Human-readable specifics — file path, line, message.
    invoked_by:
        What the writer says triggered the event:
        ``"claude-code-hook" | "pre-commit" | "ci" | "manual" | "agent-manual"``.
    log_dir:
        Override for tests. Defaults to :data:`LOG_DIR_DEFAULT`.
    recorded_by:
        ``"hook"`` when a hook process writes its own decision, ``"cli"``
        for everything typed in. Only the hook passes ``"hook"``.
    decision:
        For hook events: ``"deny"`` or ``"ask"``.

    Returns
    -------
    pathlib.Path
        The file the event was appended to.
    """

    if not tool_id:
        raise ValueError("tool_id is required")
    if not failure_mode:
        raise ValueError("failure_mode is required")
    if not mechanism:
        raise ValueError("mechanism is required")
    if recorded_by not in RECORDERS:
        raise ValueError(f"recorded_by must be one of {RECORDERS}")

    target_dir = Path(log_dir) if log_dir is not None else LOG_DIR_DEFAULT
    target_dir.mkdir(parents=True, exist_ok=True)

    ts = _utcnow_iso()
    event: dict[str, Any] = {
        "ts": ts,
        "tool_id": tool_id,
        "failure_mode": failure_mode,
        "mechanism": mechanism,
        "detail": detail,
        "invoked_by": invoked_by,
        "recorded_by": recorded_by,
    }
    if decision:
        event["decision"] = decision

    target = target_dir / f"{_date_bucket(ts)}.jsonl"

    if _is_duplicate(target, event):
        return target

    line = json.dumps(event, ensure_ascii=False, sort_keys=True)
    # Open with "a" so the OS-level write is appended atomically for lines
    # under PIPE_BUF on POSIX, which is more than enough for a single JSON
    # object. fsync is overkill for a developer-local log.
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    return target


def read_events(log_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return every event in *log_dir*, sorted by ts descending.

    Every event carries ``recorded_by`` (``"hook"`` or ``"cli"``); see the
    module docstring. Use :func:`observed_events` for hook events only.

    Reads ``*.jsonl`` files and silently skips blank lines and rows that
    fail to parse — the logger is meant to be unobtrusive, never the cause
    of a downstream crash.
    """

    target_dir = Path(log_dir) if log_dir is not None else LOG_DIR_DEFAULT
    if not target_dir.exists():
        return []

    events: list[dict[str, Any]] = []
    for path in sorted(target_dir.glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    # Lines from before the field existed were all typed in.
                    event.setdefault("recorded_by", "cli")
                    events.append(event)
        except OSError:
            continue

    events.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return events


def observed_events(log_dir: Path | None = None) -> list[dict[str, Any]]:
    """Only the events a hook recorded itself (``recorded_by == "hook"``)."""

    return [e for e in read_events(log_dir) if e.get("recorded_by") == "hook"]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _is_duplicate(target: Path, event: dict[str, Any]) -> bool:
    """True if *event* matches the last line of *target* on
    (ts, tool_id, mechanism, detail). Two different events in one second
    are both kept; the same event written twice is kept once."""

    if not target.exists():
        return False
    try:
        # Read only the tail; logs are tiny but this keeps things bounded.
        with target.open("rb") as fh:
            try:
                fh.seek(-4096, os.SEEK_END)
            except OSError:
                fh.seek(0)
            tail = fh.read().decode("utf-8", errors="ignore")
    except OSError:
        return False

    for raw in reversed(tail.splitlines()):
        raw = raw.strip()
        if not raw:
            continue
        try:
            prev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if (
            prev.get("ts") == event["ts"]
            and prev.get("tool_id") == event["tool_id"]
            and prev.get("mechanism") == event["mechanism"]
            and prev.get("detail", "") == event.get("detail", "")
        ):
            return True
        # Only check the most recent record — duplicates only matter for
        # events that fire back-to-back within the same second.
        return False
    return False
