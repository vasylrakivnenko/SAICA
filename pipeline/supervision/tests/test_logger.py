"""Tests for the prevention-event JSONL logger.

KG citations (mirrors :mod:`pipeline.supervision.logger`):

- ``data/failure_modes/scope_creep.yml`` — used as the failure-mode tag in
  most fixtures so the round-trip exercises a real KG id.
- ``data/tools/semgrep.yml`` — used as the tool_id in CLI smoke.
- ``data/tools/dependabot.yml`` — citation-style template for headers.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.supervision import logger as logger_mod
from pipeline.supervision.logger import log_prevention, read_events


REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def test_log_then_read_round_trip(tmp_path: Path):
    path = log_prevention(
        tool_id="semgrep",
        failure_mode="security_vulnerability",
        mechanism="blocked-commit-via-pre-commit",
        detail="src/foo.py:14",
        invoked_by="pre-commit",
        log_dir=tmp_path,
    )
    assert path.exists()

    events = read_events(log_dir=tmp_path)
    assert len(events) == 1
    ev = events[0]
    assert ev["tool_id"] == "semgrep"
    assert ev["failure_mode"] == "security_vulnerability"
    assert ev["mechanism"] == "blocked-commit-via-pre-commit"
    assert ev["detail"] == "src/foo.py:14"
    assert ev["invoked_by"] == "pre-commit"
    assert "ts" in ev


def test_read_returns_descending(tmp_path: Path):
    # Two writes in sequence; descending order means newest-first
    log_prevention(
        tool_id="t1",
        failure_mode="scope_creep",
        mechanism="m1",
        log_dir=tmp_path,
    )
    log_prevention(
        tool_id="t2",
        failure_mode="scope_creep",
        mechanism="m2",
        log_dir=tmp_path,
    )
    events = read_events(log_dir=tmp_path)
    assert len(events) == 2
    assert events[0]["ts"] >= events[1]["ts"]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_idempotent_same_second(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Two writes with identical (ts, tool_id, mechanism) collapse to one."""

    fixed = "2026-04-23T12:34:56Z"
    monkeypatch.setattr(logger_mod, "_utcnow_iso", lambda: fixed)

    log_prevention(
        tool_id="semgrep",
        failure_mode="security_vulnerability",
        mechanism="blocked-commit-via-pre-commit",
        detail="src/foo.py:14",
        log_dir=tmp_path,
    )
    log_prevention(
        tool_id="semgrep",
        failure_mode="security_vulnerability",
        mechanism="blocked-commit-via-pre-commit",
        detail="src/foo.py:14",
        log_dir=tmp_path,
    )
    events = read_events(log_dir=tmp_path)
    assert len(events) == 1


def test_not_idempotent_when_mechanism_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixed = "2026-04-23T12:34:56Z"
    monkeypatch.setattr(logger_mod, "_utcnow_iso", lambda: fixed)

    log_prevention(
        tool_id="semgrep", failure_mode="scope_creep", mechanism="m1", log_dir=tmp_path
    )
    log_prevention(
        tool_id="semgrep", failure_mode="scope_creep", mechanism="m2", log_dir=tmp_path
    )
    events = read_events(log_dir=tmp_path)
    assert len(events) == 2


# ---------------------------------------------------------------------------
# Filename / timestamp formats
# ---------------------------------------------------------------------------

def test_date_bucket_filename(tmp_path: Path):
    log_prevention(
        tool_id="x",
        failure_mode="scope_creep",
        mechanism="m",
        log_dir=tmp_path,
    )
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    name = files[0].name
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}\.jsonl", name), name
    # Must match today's UTC date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert name == f"{today}.jsonl"


def test_iso_timestamp_with_z_suffix(tmp_path: Path):
    log_prevention(
        tool_id="x",
        failure_mode="scope_creep",
        mechanism="m",
        log_dir=tmp_path,
    )
    ev = read_events(log_dir=tmp_path)[0]
    ts = ev["ts"]
    assert ts.endswith("Z"), ts
    # No microseconds, no offset — exactly the documented shape.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts), ts


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["tool_id", "failure_mode", "mechanism"])
def test_missing_required_field_raises(tmp_path: Path, missing: str):
    kwargs = dict(
        tool_id="x",
        failure_mode="scope_creep",
        mechanism="m",
        log_dir=tmp_path,
    )
    kwargs[missing] = ""
    with pytest.raises(ValueError):
        log_prevention(**kwargs)  # type: ignore[arg-type]


def test_read_events_missing_dir_returns_empty(tmp_path: Path):
    assert read_events(log_dir=tmp_path / "nope") == []


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

def test_cli_smoke_writes_line(tmp_path: Path):
    """Exec ``python -m pipeline.supervision log ...`` and confirm a line lands."""

    log_dir = tmp_path / "prev"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipeline.supervision",
            "log",
            "--tool-id",
            "test",
            "--failure-mode",
            "scope_creep",
            "--mechanism",
            "unit-test",
            "--detail",
            "demo",
            "--invoked-by",
            "manual",
            "--log-dir",
            str(log_dir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    target_path = Path(proc.stdout.strip())
    assert target_path.exists()
    assert target_path.parent == log_dir

    line = target_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    rec = json.loads(line)
    assert rec["tool_id"] == "test"
    assert rec["failure_mode"] == "scope_creep"
    assert rec["mechanism"] == "unit-test"
    assert rec["detail"] == "demo"
    assert rec["invoked_by"] == "manual"


def test_cli_rejects_missing_required_flags():
    proc = subprocess.run(
        [sys.executable, "-m", "pipeline.supervision", "log", "--tool-id", "x"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
