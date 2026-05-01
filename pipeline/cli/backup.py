"""CLI: Postgres snapshot + restore for the SAICA-KG pipeline DB.

Wraps ``pg_dump`` / ``psql`` via :mod:`subprocess` so we don't pull a
Postgres driver into this code path — the only Python dependency is
the stdlib. Snapshots are written as **plain SQL + gzip** (not
``pg_dump -F c``): that way a reviewer can ``zless`` them, and a
partial / corrupted dump is still diffable.

Examples::

    python -m pipeline.cli.backup
        # -> research/backups/saica_kg_<ISO>.sql.gz

    python -m pipeline.cli.backup --out path.sql.gz
        # custom destination

    python -m pipeline.cli.backup --restore path.sql.gz
        # psql restore (asks for confirmation unless --yes)

    python -m pipeline.cli.backup --list
        # list snapshots in research/backups/ (newest first)

Reads ``POSTGRES_URL`` for host/port/user/db via :mod:`pipeline.config`.

Snapshots live under ``research/backups/`` and are git-ignored.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

from pipeline.config import REPO_ROOT, load_env_once

DEFAULT_BACKUPS_DIR = REPO_ROOT / "research" / "backups"
DEFAULT_DSN = "postgresql://saica:saica_local_dev@localhost:5433/saica_kg"

# Exit codes
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_PG_DUMP_FAIL = 3
EXIT_USER_ABORT = 4


# ---------------------------------------------------------------------------
# DSN parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DsnParts:
    """Decomposed ``POSTGRES_URL`` used to assemble ``pg_dump`` CLI flags."""

    host: str
    port: str
    user: str
    password: Optional[str]
    dbname: str

    def pg_env(self) -> dict[str, str]:
        """Return an env dict carrying ``PGPASSWORD`` if known.

        We pass the password via env rather than a ``.pgpass`` file or a
        DSN string so no credential appears on the process command line.
        """
        env = os.environ.copy()
        if self.password:
            env["PGPASSWORD"] = self.password
        return env


def _resolve_dsn() -> str:
    load_env_once()
    return os.environ.get("POSTGRES_URL", DEFAULT_DSN)


def parse_dsn(dsn: str) -> DsnParts:
    """Parse a ``postgresql://user:pass@host:port/db`` DSN into parts."""
    parsed = urlparse(dsn)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ValueError(
            f"POSTGRES_URL must use postgresql:// scheme, got {parsed.scheme!r}"
        )
    host = parsed.hostname or "localhost"
    port = str(parsed.port) if parsed.port else "5432"
    user = (
        unquote(parsed.username)
        if parsed.username
        else os.environ.get("USER", "postgres")
    )
    password = unquote(parsed.password) if parsed.password else None
    dbname = parsed.path.lstrip("/") or user
    return DsnParts(host=host, port=port, user=user, password=password, dbname=dbname)


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def default_backup_path(
    dsn: DsnParts,
    *,
    now: Optional[dt.datetime] = None,
    backups_dir: Optional[Path] = None,
) -> Path:
    """Return ``research/backups/<dbname>_<ISO>.sql.gz``.

    The timestamp is UTC, compact ISO 8601 (``20260422T153012Z``), so
    filenames sort lexicographically by age.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    # Compact, filesystem-safe ISO: 20260422T153012Z
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    backups_dir = backups_dir or DEFAULT_BACKUPS_DIR
    return backups_dir / f"{dsn.dbname}_{stamp}.sql.gz"


def _pg_dump_cmd(dsn: DsnParts) -> list[str]:
    """Build a ``pg_dump`` argv — plain SQL, no owner/privileges."""
    return [
        "pg_dump",
        "--host",
        dsn.host,
        "--port",
        dsn.port,
        "--username",
        dsn.user,
        "--no-password",  # never prompt; rely on PGPASSWORD
        "--format",
        "plain",  # human-readable SQL, not -F c
        "--no-owner",
        "--no-privileges",
        dsn.dbname,
    ]


def _psql_restore_cmd(dsn: DsnParts) -> list[str]:
    return [
        "psql",
        "--host",
        dsn.host,
        "--port",
        dsn.port,
        "--username",
        dsn.user,
        "--no-password",
        "--dbname",
        dsn.dbname,
        "--set",
        "ON_ERROR_STOP=1",
    ]


def _run_backup(
    dsn: DsnParts,
    out_path: Path,
    *,
    runner=subprocess.run,
) -> int:
    """Run ``pg_dump ... | gzip > out_path``.

    Implemented as two subprocesses piped in-process so a dump failure
    is not silently swallowed by gzip exiting 0.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    dump_cmd = _pg_dump_cmd(dsn)
    # Spawn pg_dump -> gzip -> out_path. We use two separate Popen calls
    # so we can observe either side's exit code. ``runner`` is only used
    # for tests that want to mock the whole pipeline with a single call.
    if runner is not subprocess.run:
        result = runner(
            dump_cmd,
            env=dsn.pg_env(),
            check=False,
            capture_output=True,
        )
        # Test stubs write the dump payload to stdout; we gzip it ourselves.
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", "replace")
            print(
                f"pg_dump failed (rc={result.returncode}):\n{stderr}", file=sys.stderr
            )
            return EXIT_PG_DUMP_FAIL
        import gzip

        payload = result.stdout or b""
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        with gzip.open(out_path, "wb") as fh:
            fh.write(payload)
        return EXIT_OK

    # Real path: stream pg_dump stdout directly into gzip stdin.
    env = dsn.pg_env()
    with out_path.open("wb") as out_fh:
        # gzip reads pg_dump's stdout on its stdin and writes to our file.
        gzip_proc = subprocess.Popen(
            ["gzip", "-c"],
            stdin=subprocess.PIPE,
            stdout=out_fh,
        )
        dump_proc = subprocess.Popen(
            dump_cmd,
            stdout=gzip_proc.stdin,
            env=env,
        )
        # Close our copy of gzip's stdin so it sees EOF when dump exits.
        if gzip_proc.stdin is not None:
            dump_proc.stdout  # appease linters — Popen manages the pipe
        dump_rc = dump_proc.wait()
        if gzip_proc.stdin is not None:
            gzip_proc.stdin.close()
        gzip_rc = gzip_proc.wait()

    if dump_rc != 0:
        print(f"pg_dump failed (rc={dump_rc})", file=sys.stderr)
        try:
            out_path.unlink()
        except OSError:
            pass
        return EXIT_PG_DUMP_FAIL
    if gzip_rc != 0:
        print(f"gzip failed (rc={gzip_rc})", file=sys.stderr)
        try:
            out_path.unlink()
        except OSError:
            pass
        return EXIT_PG_DUMP_FAIL
    return EXIT_OK


def _run_restore(
    dsn: DsnParts,
    src_path: Path,
    *,
    runner=subprocess.run,
) -> int:
    """Restore a ``.sql.gz`` snapshot via ``gunzip -c <path> | psql ...``."""
    if not src_path.exists():
        print(f"no such snapshot: {src_path}", file=sys.stderr)
        return EXIT_USAGE

    psql_cmd = _psql_restore_cmd(dsn)

    if runner is not subprocess.run:
        # Test path: hand the restore command + source to the stubbed runner.
        result = runner(
            psql_cmd,
            env=dsn.pg_env(),
            check=False,
            capture_output=True,
            input=src_path.read_bytes(),
        )
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", "replace")
            print(
                f"psql restore failed (rc={result.returncode}):\n{stderr}",
                file=sys.stderr,
            )
            return EXIT_PG_DUMP_FAIL
        return EXIT_OK

    env = dsn.pg_env()
    gunzip = subprocess.Popen(
        ["gunzip", "-c", str(src_path)],
        stdout=subprocess.PIPE,
    )
    psql = subprocess.Popen(
        psql_cmd,
        stdin=gunzip.stdout,
        env=env,
    )
    if gunzip.stdout is not None:
        gunzip.stdout.close()  # so psql sees EOF when gunzip exits
    psql_rc = psql.wait()
    gunzip_rc = gunzip.wait()
    if gunzip_rc != 0:
        print(f"gunzip failed (rc={gunzip_rc})", file=sys.stderr)
        return EXIT_PG_DUMP_FAIL
    if psql_rc != 0:
        print(f"psql restore failed (rc={psql_rc})", file=sys.stderr)
        return EXIT_PG_DUMP_FAIL
    return EXIT_OK


# ---------------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------------


def _human_size(num_bytes: int) -> str:
    """Return a short human size string ('12.3 MB', '4.1 KB', '512 B')."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"  # unreachable, but satisfies type-checkers


def _human_mtime(mtime: float, *, now: Optional[dt.datetime] = None) -> str:
    """Return a short human timestamp ('2026-04-22 15:30' local time)."""
    return dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


def list_snapshots(
    backups_dir: Optional[Path] = None,
) -> list[Path]:
    """Return snapshot paths sorted by mtime **descending** (newest first)."""
    backups_dir = backups_dir or DEFAULT_BACKUPS_DIR
    if not backups_dir.exists():
        return []
    snaps = [
        p for p in backups_dir.iterdir() if p.is_file() and p.name.endswith(".sql.gz")
    ]
    snaps.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return snaps


def _print_listing(snaps: list[Path]) -> None:
    if not snaps:
        print(f"no snapshots under {DEFAULT_BACKUPS_DIR}")
        return
    name_w = max(len(p.name) for p in snaps)
    size_w = 10
    for p in snaps:
        st = p.stat()
        name = p.name.ljust(name_w)
        size = _human_size(st.st_size).rjust(size_w)
        when = _human_mtime(st.st_mtime)
        print(f"{name}  {size}  {when}")


# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------


def _confirm_restore(target_path: Path, dbname: str, *, reader=input) -> bool:
    """Interactive yes/no prompt before a destructive restore."""
    print(
        f"About to restore {target_path} into database {dbname!r}. "
        f"This will execute SQL from the snapshot and may overwrite existing data."
    )
    try:
        ans = reader(f"Type 'yes' to confirm restore into {dbname!r}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("yes", "y")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def do_backup(
    *,
    out: Optional[Path],
    dsn_str: Optional[str] = None,
    now: Optional[dt.datetime] = None,
    runner=subprocess.run,
    backups_dir: Optional[Path] = None,
) -> int:
    dsn = parse_dsn(dsn_str or _resolve_dsn())
    target = out or default_backup_path(dsn, now=now, backups_dir=backups_dir)
    rc = _run_backup(dsn, target, runner=runner)
    if rc == EXIT_OK:
        print(f"wrote {target}")
    return rc


def do_restore(
    path: Path,
    *,
    assume_yes: bool,
    dsn_str: Optional[str] = None,
    runner=subprocess.run,
    reader=input,
) -> int:
    dsn = parse_dsn(dsn_str or _resolve_dsn())
    if not assume_yes:
        if not _confirm_restore(path, dsn.dbname, reader=reader):
            print("aborted by user", file=sys.stderr)
            return EXIT_USER_ABORT
    rc = _run_restore(dsn, path, runner=runner)
    if rc == EXIT_OK:
        print(f"restored {path} into {dsn.dbname!r}")
    return rc


def do_list(*, backups_dir: Optional[Path] = None) -> int:
    snaps = list_snapshots(backups_dir=backups_dir)
    _print_listing(snaps)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pipeline.cli.backup",
        description="Snapshot / restore the SAICA-KG Postgres database.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Destination .sql.gz path. Defaults to"
            " research/backups/<dbname>_<ISO>.sql.gz."
        ),
    )
    p.add_argument(
        "--restore",
        type=Path,
        default=None,
        metavar="PATH",
        help="Restore this snapshot instead of creating a new one.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List snapshots under research/backups/ (newest first).",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation on --restore.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Mutually-exclusive modes — enforced here so the default (no flags)
    # is still "snapshot now".
    modes = sum([bool(args.list), bool(args.restore)])
    if modes > 1:
        parser.error("--list and --restore are mutually exclusive")

    if args.list:
        return do_list()
    if args.restore is not None:
        return do_restore(args.restore, assume_yes=args.yes)
    return do_backup(out=args.out)


if __name__ == "__main__":
    sys.exit(main())
