"""Unit tests for the ``export_site_data`` taxonomy-study exporter.

We don't re-run the clustering study here — the ground-truth artifacts
already committed under ``research/taxonomy_clustering/`` are the input.
Tests verify the exporter packs them into the shape the
``/taxonomy-study`` Astro page expects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.config import REPO_ROOT
from pipeline.taxonomy_cluster import export_site_data as export_mod


RESEARCH_DIR = REPO_ROOT / "research" / "taxonomy_clustering"


def _have_inputs() -> bool:
    required = [
        "corpus.json",
        "metadata.json",
        "hdbscan_runs.json",
        "bipartite_clusters.json",
        "saica_comparison.json",
        "embeddings.npy",
    ]
    return all((RESEARCH_DIR / name).exists() for name in required)


pytestmark = pytest.mark.skipif(
    not _have_inputs(),
    reason="research/taxonomy_clustering artifacts not present; "
    "run `.venv/bin/python -m pipeline.cli.cluster_study` first.",
)


@pytest.fixture(scope="module")
def payload() -> dict:
    # Build without writing to disk so we can run tests in parallel without
    # clobbering the real site JSON — plus it runs UMAP once and shares.
    return export_mod.build_payload(research_dir=RESEARCH_DIR)


# ---------------------------------------------------------------------------
# 1. Top-level keys
# ---------------------------------------------------------------------------


def test_export_writes_taxonomy_study_json(tmp_path: Path) -> None:
    """The CLI produces taxonomy_study.json with all expected top-level keys."""
    out = tmp_path / "taxonomy_study.json"
    rc = export_mod.main(
        [
            "--research-dir",
            str(RESEARCH_DIR),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    assert out.exists()

    body = json.loads(out.read_text(encoding="utf-8"))
    for key in ("summary", "taxonomies", "saica_modes", "points", "clusters"):
        assert key in body, f"missing top-level key: {key}"

    # Summary contains the exact numeric fields /taxonomy-study renders.
    for key in (
        "corpus_size",
        "k_text",
        "k_bipartite",
        "k_manual_saica",
        "ari_text_saica",
        "nmi_text_saica",
        "ari_bipartite_saica",
        "nmi_bipartite_saica",
        "bootstrap_ari_text",
        "bootstrap_ari_bipartite",
        "chosen_text_mcs",
        "chosen_bipartite_mcs",
    ):
        assert key in body["summary"], f"missing summary key: {key}"

    # Clusters has both partitions.
    assert "bipartite" in body["clusters"]
    assert "text" in body["clusters"]


# ---------------------------------------------------------------------------
# 2. Point schema
# ---------------------------------------------------------------------------


def test_every_point_has_required_fields(payload: dict) -> None:
    required = {
        "id",
        "key",
        "source_tax_id",
        "label",
        "description",
        "x",
        "y",
        "text_cluster",
        "bipartite_cluster",
        "saica_match",
    }
    assert len(payload["points"]) == payload["summary"]["corpus_size"]
    for pt in payload["points"]:
        missing = required - set(pt.keys())
        assert not missing, f"point {pt.get('key')} missing: {missing}"
        assert isinstance(pt["x"], (int, float))
        assert isinstance(pt["y"], (int, float))
        assert isinstance(pt["text_cluster"], int)
        assert isinstance(pt["bipartite_cluster"], int)
        assert isinstance(pt["saica_match"], str) and pt["saica_match"]


# ---------------------------------------------------------------------------
# 3. UMAP coords normalized to [0, 1]
# ---------------------------------------------------------------------------


def test_umap_coords_normalized_to_unit_box(payload: dict) -> None:
    """UMAP coords must sit in the same [0, 1] box /explore uses."""
    xs = [pt["x"] for pt in payload["points"]]
    ys = [pt["y"] for pt in payload["points"]]
    assert xs and ys
    assert 0.0 <= min(xs) <= max(xs) <= 1.0
    assert 0.0 <= min(ys) <= max(ys) <= 1.0
    # Non-degenerate — there must be spread on both axes.
    assert max(xs) - min(xs) > 0.1
    assert max(ys) - min(ys) > 0.1


# ---------------------------------------------------------------------------
# 4. Cluster sizes sum to corpus size (noise included)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("partition", ["bipartite", "text"])
def test_cluster_sizes_sum_to_corpus_size(payload: dict, partition: str) -> None:
    """Every point is in exactly one cluster (or cluster_id = -1 = noise)."""
    rows = payload["clusters"][partition]
    total = sum(int(r["size"]) for r in rows)
    assert total == payload["summary"]["corpus_size"]

    # Also sanity-check that point cluster ids line up with cluster rows.
    field = "bipartite_cluster" if partition == "bipartite" else "text_cluster"
    seen_ids = {int(pt[field]) for pt in payload["points"]}
    listed_ids = {int(r["id"]) for r in rows}
    assert seen_ids == listed_ids, (
        f"cluster ids diverge between points and cluster table for {partition}: "
        f"points={seen_ids}, clusters={listed_ids}"
    )


# ---------------------------------------------------------------------------
# Extras beyond the 4 required cases
# ---------------------------------------------------------------------------


def test_taxonomies_have_color_and_name(payload: dict) -> None:
    assert payload["taxonomies"]
    for tid, meta in payload["taxonomies"].items():
        assert meta.get("name"), f"taxonomy {tid} missing name"
        color = meta.get("color", "")
        assert (
            color.startswith("#") and len(color) == 7
        ), f"taxonomy {tid} color must be a hex literal: {color!r}"


def test_site_json_under_size_budget() -> None:
    """The shipped site JSON must stay small enough for a static host."""
    path = REPO_ROOT / "site" / "public" / "taxonomy_study.json"
    if not path.exists():
        pytest.skip("site JSON not generated yet; run export_site_data")
    size_kb = path.stat().st_size / 1024
    assert size_kb < 200, f"site JSON is {size_kb:.1f} KB (> 200 KB budget)"
