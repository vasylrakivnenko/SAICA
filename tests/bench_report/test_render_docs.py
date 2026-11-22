"""Tests for bench/render_docs.py: the README table, the llms.txt block and bench/<mode>/RESULTS.md are rendered
from results.json, so they cannot drift from the published numbers.

Run: .venv/bin/python -m pytest tests/bench_report -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BENCH = REPO / "bench"
sys.path.insert(0, str(BENCH))

import render_docs  # noqa: E402


@pytest.fixture(scope="module")
def res():
    return json.loads((REPO / "site" / "public" / "bench" / "results.json").read_text())


def test_readme_block_has_every_mode_grouped_by_provenance(res):
    block = render_docs.readme_block(res)
    for m in res["modes"]:
        assert f"| {m['name']}" in block
    heads = [f"**{g['label']}**" for g in res["overview"]["groups"]]
    assert [block.index(h) for h in heads] == sorted(block.index(h) for h in heads)
    assert f"v{res['version']}" in block
    for m in res["modes"]:
        if m["below_floor"]:  # nobody is named where every row is close to chance
            line = next(x for x in block.splitlines() if x.startswith(f"| {m['name']}"))
            assert (
                "none (no reviewer reaches J" in line
                and m["best_reviewer"]["short"] not in line
            )


def test_llms_block_names_version_and_counts(res):
    block = render_docs.llms_block(res)
    c = res["overview"]["counts"]
    assert res["cite_as"] in block and f"{c['modes']} failure modes" in block
    assert (
        f"{c['constructed']} of the {c['modes']} sets have constructed positives"
        in block
    )


def test_results_md_matches_the_tracked_files(res):
    """bench/<mode>/RESULTS.md is generated; a hand edit or a stale copy fails here."""
    for m in res["modes"]:
        path = BENCH / render_docs.mode_folder(m["id"]) / "RESULTS.md"
        assert path.read_text() == render_docs.results_md(
            res, m
        ), f"{path} is out of date: run bench/build_report.py"


def test_splice_replaces_only_the_block_between_the_markers():
    text = f"intro\n{render_docs.BEGIN}\nold\n{render_docs.END}\noutro\n"
    new = render_docs.splice(text, "NEW")
    assert new == f"intro\n{render_docs.BEGIN}\nNEW\n{render_docs.END}\noutro\n"
    assert render_docs.splice(new, "NEW") == new
    with pytest.raises(ValueError):
        render_docs.splice("no markers here", "x")


def test_insert_and_check_on_a_file(res, tmp_path):
    f = tmp_path / "README.md"
    f.write_text(f"# x\n\n{render_docs.BEGIN}\n{render_docs.END}\n")
    results = str(REPO / "site" / "public" / "bench" / "results.json")
    assert render_docs.main(["readme", "--results", results, "--check", str(f)]) == 1
    assert render_docs.main(["readme", "--results", results, "--insert", str(f)]) == 0
    assert render_docs.main(["readme", "--results", results, "--check", str(f)]) == 0
    assert render_docs.readme_block(res) in f.read_text()
