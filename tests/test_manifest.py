"""Unit tests for ``validator/generate_manifest.py``.

The manifest is both a machine-readable index of the KG (for downstream
Tools) and an immutability lock checked in CI. These tests exercise both
roles.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from validator import generate_manifest as gm


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "MANIFEST.json"


# ---------------------------------------------------------------------------
# Core correctness
# ---------------------------------------------------------------------------


def test_generate_manifest_matches_current_corpus() -> None:
    """Rebuilding from data/ must produce ids identical to what's committed.

    If this ever fails, either the corpus changed without a manifest
    regeneration, or the manifest was hand-edited. Both are CI fails.
    """
    built = gm.build_manifest()
    committed = json.loads(MANIFEST_PATH.read_text())

    assert built["counts"] == committed["counts"]
    assert built["ids"] == committed["ids"]


def test_manifest_includes_canonical_urls_for_tools() -> None:
    """Tools entries carry the canonical URL for each tool.

    GitHub-hosted Tools map to ``https://github.com/<owner>/<repo>``;
    non-GitHub Tools fall back to ``documentation_url``; a Tool with
    neither would map to ``None`` (there should be none in the corpus).
    """
    built = gm.build_manifest()
    tools = built["ids"]["tools"]

    # Sanity: every Tool has SOME URL (corpus invariant we also want to
    # preserve going forward).
    for tool_id, url in tools.items():
        assert url is not None, f"tool {tool_id!r} has no canonical or documentation URL"

    # Spot-check the GitHub canonicalization path: aider lives on GitHub.
    assert tools["aider"] == "https://github.com/paul-gauthier/aider"
    # Spot-check the documentation-url fallback: cursor is not on GitHub.
    assert tools["cursor"].startswith("http")
    assert "github.com" not in tools["cursor"]


# ---------------------------------------------------------------------------
# --check CLI mode
# ---------------------------------------------------------------------------


def _run_check() -> subprocess.CompletedProcess:
    """Run ``python -m validator.generate_manifest --check`` from the repo
    root, returning the completed process. ``cwd`` is pinned so the
    subprocess resolves the committed manifest correctly regardless of
    where pytest was invoked from.
    """
    return subprocess.run(
        [sys.executable, "-m", "validator.generate_manifest", "--check"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


def test_manifest_check_exits_zero_when_fresh() -> None:
    """On a clean tree, ``--check`` must succeed."""
    result = _run_check()
    assert result.returncode == 0, (
        f"--check failed on a clean tree\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


def test_manifest_check_exits_one_when_out_of_date(tmp_path: Path) -> None:
    """Tamper with the committed manifest and confirm --check catches it.

    We rewrite the file temporarily, run the CLI, then restore the
    original. This exercises the real CLI (subprocess), not just the
    in-memory build function, so we also cover argparse + the stderr diff
    output.
    """
    original = MANIFEST_PATH.read_text()
    tampered = json.loads(original)
    # Pretend a tool was renamed: drop a known id from the manifest.
    tampered["ids"]["tools"].pop("aider", None)
    tampered["counts"]["tools"] -= 1

    try:
        MANIFEST_PATH.write_text(json.dumps(tampered, indent=2) + "\n")
        result = _run_check()
        assert result.returncode == 1, (
            f"--check should fail when manifest is stale; got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "drift" in result.stderr.lower() or "aider" in result.stderr
    finally:
        MANIFEST_PATH.write_text(original)


# ---------------------------------------------------------------------------
# Stability / determinism
# ---------------------------------------------------------------------------


def test_manifest_preserves_sort_order() -> None:
    """ids must be sorted alphabetically (and tool URLs follow that order).

    Deterministic ordering is what makes the manifest diff-reviewable.
    Without it, every regeneration would shuffle rows.
    """
    built = gm.build_manifest()
    ids = built["ids"]

    # tools: dict keyed by id, but json dumps preserve insertion order.
    tool_ids = list(ids["tools"].keys())
    assert tool_ids == sorted(tool_ids), "tool ids are not sorted"

    for kind in ("failure_modes", "papers", "taxonomies", "crosswalks"):
        assert ids[kind] == sorted(ids[kind]), f"{kind} ids are not sorted"


def test_manifest_format_is_stable() -> None:
    """Two consecutive ``format_manifest`` calls (with the same input) must
    produce byte-identical output. Otherwise ``--check`` becomes flaky.
    """
    manifest = gm.build_manifest()
    first = gm.format_manifest(manifest)
    second = gm.format_manifest(manifest)
    assert first == second


def test_kg_version_is_year_month() -> None:
    """kg_version follows YYYY.MM — the only format Tools downstream parse."""
    import datetime as dt

    now = dt.datetime(2027, 1, 3, tzinfo=dt.timezone.utc)
    m = gm.build_manifest(now=now)
    assert m["kg_version"] == "2027.01"
