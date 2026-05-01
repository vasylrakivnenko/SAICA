"""Tests for :mod:`pipeline.cli.backup`.

The backup CLI wraps ``pg_dump`` via :mod:`subprocess`; we mock the
subprocess runner so tests don't need a live Postgres to exercise argv
shape, path formatting, and confirmation flow. The ``--list`` path is
exercised with real files in a tmp backups dir.
"""

from __future__ import annotations

import datetime as dt
import gzip
import os
import re
from pathlib import Path


from pipeline.cli import backup as backup_cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


DUMMY_DSN = "postgresql://saica:saica_local_dev@db.example.com:6543/saica_kg_test"


class FakeRunner:
    """Recording stub that mimics :func:`subprocess.run`.

    Captures (argv, env, input) from each call and returns a configured
    :class:`subprocess.CompletedProcess`-ish object with ``returncode`` and
    ``stdout`` / ``stderr`` bytes.
    """

    def __init__(
        self, *, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""
    ):
        self.calls: list[dict] = []
        self._rc = returncode
        self._stdout = stdout
        self._stderr = stderr

    def __call__(self, cmd, *, env=None, check=False, capture_output=False, input=None):
        self.calls.append(
            {
                "cmd": list(cmd),
                "env": env,
                "input": input,
            }
        )

        class _Result:
            def __init__(self_inner, rc, stdout, stderr):
                self_inner.returncode = rc
                self_inner.stdout = stdout
                self_inner.stderr = stderr

        return _Result(self._rc, self._stdout, self._stderr)


# ---------------------------------------------------------------------------
# default_backup_path / parse_dsn
# ---------------------------------------------------------------------------


def test_parse_dsn_extracts_all_parts() -> None:
    dsn = backup_cli.parse_dsn(DUMMY_DSN)
    assert dsn.host == "db.example.com"
    assert dsn.port == "6543"
    assert dsn.user == "saica"
    assert dsn.password == "saica_local_dev"
    assert dsn.dbname == "saica_kg_test"


def test_backup_default_path_includes_iso_timestamp(tmp_path: Path) -> None:
    """Default path is `<backups_dir>/<dbname>_<compact-ISO>.sql.gz`."""
    dsn = backup_cli.parse_dsn(DUMMY_DSN)
    fixed = dt.datetime(2026, 4, 22, 15, 30, 12, tzinfo=dt.timezone.utc)
    path = backup_cli.default_backup_path(dsn, now=fixed, backups_dir=tmp_path)
    assert path.parent == tmp_path
    assert path.name == "saica_kg_test_20260422T153012Z.sql.gz"
    # Timestamp is lexicographically sortable and matches the compact-ISO shape.
    assert re.match(r"^saica_kg_test_\d{8}T\d{6}Z\.sql\.gz$", path.name)


# ---------------------------------------------------------------------------
# do_backup -> pg_dump invocation
# ---------------------------------------------------------------------------


def test_backup_invokes_pg_dump_with_dsn_parts(tmp_path: Path) -> None:
    """pg_dump argv carries host/port/user/db from the DSN; password goes
    through PGPASSWORD in env, never on the command line."""
    runner = FakeRunner(stdout=b"-- canned sql dump\nSELECT 1;\n")
    out = tmp_path / "snap.sql.gz"
    rc = backup_cli.do_backup(
        out=out,
        dsn_str=DUMMY_DSN,
        runner=runner,
    )
    assert rc == 0
    # One pg_dump call recorded.
    assert len(runner.calls) == 1
    cmd = runner.calls[0]["cmd"]
    assert cmd[0] == "pg_dump"
    # host/port/user/db all flow through as flags.
    assert "--host" in cmd and cmd[cmd.index("--host") + 1] == "db.example.com"
    assert "--port" in cmd and cmd[cmd.index("--port") + 1] == "6543"
    assert "--username" in cmd and cmd[cmd.index("--username") + 1] == "saica"
    assert cmd[-1] == "saica_kg_test"  # dbname is positional, last
    # Plain format (not -F c); no owner / privileges noise.
    assert "--format" in cmd and cmd[cmd.index("--format") + 1] == "plain"
    assert "--no-owner" in cmd
    assert "--no-privileges" in cmd
    # Password never appears on the command line — only in PGPASSWORD.
    assert "saica_local_dev" not in " ".join(cmd)
    assert runner.calls[0]["env"]["PGPASSWORD"] == "saica_local_dev"
    # The output file was written and is a valid gzip stream.
    assert out.exists()
    with gzip.open(out, "rb") as fh:
        decoded = fh.read()
    assert decoded.startswith(b"-- canned sql dump")


def test_backup_propagates_pg_dump_failure(tmp_path: Path) -> None:
    """A non-zero pg_dump exit bubbles up as a non-zero CLI exit."""
    runner = FakeRunner(returncode=1, stderr=b"pg_dump: connection refused")
    out = tmp_path / "snap.sql.gz"
    rc = backup_cli.do_backup(
        out=out,
        dsn_str=DUMMY_DSN,
        runner=runner,
    )
    assert rc != 0


# ---------------------------------------------------------------------------
# do_restore -> confirmation flow
# ---------------------------------------------------------------------------


def test_restore_requires_confirmation_without_yes_flag(tmp_path: Path) -> None:
    """Without --yes, the restore bails out when the user doesn't type 'yes'."""
    snap = tmp_path / "snap.sql.gz"
    with gzip.open(snap, "wb") as fh:
        fh.write(b"SELECT 1;\n")

    runner = FakeRunner(returncode=0)
    responses = iter(["n"])  # user declines
    rc = backup_cli.do_restore(
        snap,
        assume_yes=False,
        dsn_str=DUMMY_DSN,
        runner=runner,
        reader=lambda _prompt: next(responses),
    )
    assert rc == backup_cli.EXIT_USER_ABORT
    # No psql invocation happened because the user aborted.
    assert runner.calls == []


def test_restore_proceeds_when_user_confirms(tmp_path: Path) -> None:
    """Typing 'yes' runs psql; the snapshot bytes are handed to the runner."""
    snap = tmp_path / "snap.sql.gz"
    with gzip.open(snap, "wb") as fh:
        fh.write(b"SELECT 1;\n")

    runner = FakeRunner(returncode=0)
    rc = backup_cli.do_restore(
        snap,
        assume_yes=False,
        dsn_str=DUMMY_DSN,
        runner=runner,
        reader=lambda _prompt: "yes",
    )
    assert rc == 0
    assert len(runner.calls) == 1
    cmd = runner.calls[0]["cmd"]
    assert cmd[0] == "psql"
    assert "--dbname" in cmd and cmd[cmd.index("--dbname") + 1] == "saica_kg_test"
    assert "ON_ERROR_STOP=1" in cmd  # via --set
    # The snapshot bytes flowed into stdin.
    assert runner.calls[0]["input"] is not None


def test_restore_with_yes_skips_confirmation(tmp_path: Path) -> None:
    """--yes bypasses the prompt entirely."""
    snap = tmp_path / "snap.sql.gz"
    with gzip.open(snap, "wb") as fh:
        fh.write(b"SELECT 1;\n")

    def should_never_prompt(_prompt: str) -> str:
        raise AssertionError("--yes must not prompt the user")

    runner = FakeRunner(returncode=0)
    rc = backup_cli.do_restore(
        snap,
        assume_yes=True,
        dsn_str=DUMMY_DSN,
        runner=runner,
        reader=should_never_prompt,
    )
    assert rc == 0


def test_restore_missing_snapshot_fails_cleanly(tmp_path: Path) -> None:
    """A non-existent path exits with a usage error, not a crash."""
    rc = backup_cli.do_restore(
        tmp_path / "does-not-exist.sql.gz",
        assume_yes=True,
        dsn_str=DUMMY_DSN,
        runner=FakeRunner(),
    )
    assert rc == backup_cli.EXIT_USAGE


# ---------------------------------------------------------------------------
# list_snapshots — real files, sorted by mtime desc
# ---------------------------------------------------------------------------


def test_list_sorts_by_mtime_desc(tmp_path: Path) -> None:
    """Snapshots come back newest-first."""
    # Create three fake snapshots with spaced-out mtimes.
    paths = []
    for i, name in enumerate(["a.sql.gz", "b.sql.gz", "c.sql.gz"]):
        p = tmp_path / name
        p.write_bytes(b"x" * (i + 1))
        # Set mtime so "a" is oldest, "c" is newest.
        os.utime(p, (1_700_000_000 + i * 100, 1_700_000_000 + i * 100))
        paths.append(p)

    snaps = backup_cli.list_snapshots(backups_dir=tmp_path)
    assert [p.name for p in snaps] == ["c.sql.gz", "b.sql.gz", "a.sql.gz"]


def test_list_ignores_non_sql_gz(tmp_path: Path) -> None:
    """Only ``*.sql.gz`` files count as snapshots."""
    (tmp_path / "real.sql.gz").write_bytes(b"x")
    (tmp_path / "README.md").write_bytes(b"x")
    (tmp_path / "raw.sql").write_bytes(b"x")
    snaps = backup_cli.list_snapshots(backups_dir=tmp_path)
    assert [p.name for p in snaps] == ["real.sql.gz"]


def test_list_empty_dir_returns_empty(tmp_path: Path) -> None:
    assert backup_cli.list_snapshots(backups_dir=tmp_path) == []


def test_list_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert backup_cli.list_snapshots(backups_dir=tmp_path / "nope") == []


# ---------------------------------------------------------------------------
# Human size formatter
# ---------------------------------------------------------------------------


def test_human_size_formatting() -> None:
    assert backup_cli._human_size(0) == "0 B"
    assert backup_cli._human_size(512) == "512 B"
    assert backup_cli._human_size(1024) == "1.0 KB"
    assert backup_cli._human_size(1024 * 1024 * 3) == "3.0 MB"
