"""JSONL prevention-event logger.

KG citations (the supervision-on-supervision chain we want auditable):

- ``data/failure_modes/scope_creep.yml`` — events tagged with this FM are
  emitted whenever ``CLAUDE.md`` (plan-first / no-unrelated-edits) blocks
  an action via Claude Code's ``PreToolUse`` hook.
- ``data/failure_modes/security_vulnerability.yml`` — emitted when
  ``detect-private-key`` / ``semgrep`` deny a commit.
- ``data/tools/semgrep.yml`` — control_paradigm: detection, but when wired
  into ``.pre-commit-config.yaml`` it acts as a *prevention* gate (commit
  is blocked before it lands), which is exactly the cell SAICA-KG's own
  self-audit reported as 0/4.
- ``data/tools/dependabot.yml`` — sibling supervisor used as the
  citation-style template for these headers.

Design constraints (from the agent brief):

- stdlib only (no ``pydantic``, no ``requests``)
- one JSON object per line, no header
- atomic-ish append (open mode ``"a"``); idempotent within the same second
  on the (ts, tool_id, mechanism) triple
- log dir defaults to ``<repo_root>/.saica/prevention_log/`` and is
  gitignored — per-developer, never committed
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
        ``"pre-commit" | "claude-code-hook" | "ci" | "manual"``.
    log_dir:
        Override for tests. Defaults to :data:`LOG_DIR_DEFAULT`.

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
    }

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
                        events.append(json.loads(raw))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue

    events.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return events


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _is_duplicate(target: Path, event: dict[str, Any]) -> bool:
    """True if *event* matches the last line of *target* on (ts, tool_id, mechanism)."""

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
        ):
            return True
        # Only check the most recent record — duplicates only matter for
        # events that fire back-to-back within the same second.
        return False
    return False
