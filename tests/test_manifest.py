"""Unit tests for ``validator/generate_manifest.py``.

The manifest is both a machine-readable index of the KG (for downstream
Tools) and an immutability lock checked in CI. These tests exercise both
roles.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

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
        assert (
            url is not None
        ), f"tool {tool_id!r} has no canonical or documentation URL"

    # Spot-check the GitHub canonicalization path: semgrep lives on GitHub.
    assert tools["semgrep"] == "https://github.com/semgrep/semgrep"
    # Spot-check the documentation-url fallback: modal is not on GitHub.
    assert tools["modal"].startswith("http")
    assert "github.com" not in tools["modal"]


# ---------------------------------------------------------------------------
# --check CLI mode
# ---------------------------------------------------------------------------


def _run(*args: str) -> subprocess.CompletedProcess:
    """Run ``python -m validator.generate_manifest <args>`` from the repo
    root, returning the completed process. ``cwd`` is pinned so the
    subprocess resolves the committed manifest correctly regardless of
    where pytest was invoked from.
    """
    return subprocess.run(
        [sys.executable, "-m", "validator.generate_manifest", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


def _run_check(*args: str) -> subprocess.CompletedProcess:
    return _run("--check", *args)


def test_manifest_check_exits_zero_when_fresh() -> None:
    """On a clean tree, ``--check`` must succeed."""
    result = _run_check()
    assert result.returncode == 0, (
        f"--check failed on a clean tree\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


def test_manifest_check_exits_one_when_out_of_date(tmp_path: Path) -> None:
    """Tamper with a copy of the manifest and confirm --check catches it.

    The copy lives in ``tmp_path`` and is passed with ``--manifest``; the
    tracked ``data/MANIFEST.json`` is never written by a test. This
    exercises the real CLI (subprocess), not just the in-memory build
    function, so we also cover argparse + the stderr diff output.
    """
    tracked_before = MANIFEST_PATH.read_bytes()
    fresh = tmp_path / "MANIFEST.json"
    assert _run("--manifest", str(fresh)).returncode == 0
    assert _run_check("--manifest", str(fresh)).returncode == 0

    tampered = json.loads(fresh.read_text())
    # Pretend a tool was renamed: drop a known id from the manifest.
    tampered["ids"]["tools"].pop("semgrep", None)
    tampered["counts"]["tools"] -= 1
    fresh.write_text(json.dumps(tampered, indent=2) + "\n")

    result = _run_check("--manifest", str(fresh))
    assert result.returncode == 1, (
        f"--check should fail when manifest is stale; got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "drift" in result.stderr.lower() and "semgrep" in result.stderr
    assert MANIFEST_PATH.read_bytes() == tracked_before


def _copy_of_data(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    shutil.copytree(
        REPO_ROOT / "data", data, ignore=shutil.ignore_patterns("saica_index")
    )
    return data


def test_write_refuses_to_drop_an_id_without_a_tombstone(tmp_path: Path) -> None:
    """Rewriting the manifest is not a way around the id lock."""
    data = _copy_of_data(tmp_path)
    manifest = data / "MANIFEST.json"
    manifest.unlink(missing_ok=True)
    assert _run("--data-dir", str(data)).returncode == 0
    victim = sorted((data / "incidents").glob("*.yml"))[0]
    victim.unlink()

    refused = _run("--data-dir", str(data))
    assert refused.returncode == 1
    assert victim.stem in refused.stderr and "TOMBSTONES.yml" in refused.stderr
    assert victim.stem in json.loads(manifest.read_text())["ids"]["incidents"]

    tombstones = data / "TOMBSTONES.yml"
    doc = yaml.safe_load(tombstones.read_text()) if tombstones.exists() else {}
    doc.setdefault("tombstones", []).append(
        {
            "id": victim.stem,
            "kind": "incident",
            "removed_on": "2026-11-21",
            "reason": "test",
        }
    )
    tombstones.write_text(yaml.safe_dump(doc))
    allowed = _run("--data-dir", str(data))
    assert allowed.returncode == 0, allowed.stderr
    assert victim.stem not in json.loads(manifest.read_text())["ids"]["incidents"]


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
