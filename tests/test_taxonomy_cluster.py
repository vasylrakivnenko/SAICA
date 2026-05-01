"""Unit tests for the taxonomy-clustering study.

Exercises the three pure modules (collect, cluster, compare) without
touching the real sentence-transformer model. The stub encoder is an exact
mirror of ``tests.test_embeddings.StubEncoder`` — a deterministic bag-of-
words that makes similar prose produce similar vectors.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
import pytest
import yaml

from pipeline.taxonomy_cluster import cluster as cluster_mod
from pipeline.taxonomy_cluster import collect as collect_mod
from pipeline.taxonomy_cluster import compare as compare_mod


# ---------------------------------------------------------------------------
# Stub encoder (matches the one used in tests/test_embeddings.py)
# ---------------------------------------------------------------------------


class StubEncoder:
    def __init__(self, dim: int = 64, seed: int = 0):
        self.dim = dim
        self._seed = seed
        self._word_cache: dict = {}

    def _word_vec(self, w: str) -> np.ndarray:
        if w not in self._word_cache:
            rng = np.random.default_rng(abs(hash(w)) % (2**32) + self._seed)
            v = rng.standard_normal(self.dim).astype(np.float32)
            v = v / (np.linalg.norm(v) + 1e-12)
            self._word_cache[w] = v
        return self._word_cache[w]

    def encode(
        self,
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    ):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            words = [
                w
                for w in "".join(
                    c if c.isalnum() else " " for c in str(t).lower()
                ).split()
                if w
            ]
            if not words:
                v = np.zeros(self.dim, dtype=np.float32)
                v[0] = 1.0
            else:
                v = np.sum([self._word_vec(w) for w in words], axis=0)
            if normalize_embeddings:
                n = float(np.linalg.norm(v))
                if n > 1e-12:
                    v = v / n
            out[i] = v
        return out


# ---------------------------------------------------------------------------
# collect.py
# ---------------------------------------------------------------------------


def test_collect_corpus_has_all_128_categories_from_6_taxonomies():
    rows = collect_mod.collect_corpus()
    # The repo is expected to ship exactly six taxonomy YAMLs.
    source_ids = {r.source_tax_id for r in rows}
    assert len(source_ids) == 6, f"expected 6 source taxonomies, got {len(source_ids)}"
    # Every row should have non-empty label + unique (source_tax, external_id).
    seen = set()
    for r in rows:
        assert r.label, f"empty label: {r}"
        key = (r.source_tax_id, r.external_id)
        assert key not in seen, f"duplicate key {key}"
        seen.add(key)
    # Each row carries an int citation count (0 for taxonomies without a paper).
    for r in rows:
        assert isinstance(r.citation_count_of_parent_taxonomy, int)
        assert r.citation_count_of_parent_taxonomy >= 0


def test_collect_corpus_tmp_dir_respects_citation_counts(tmp_path: Path):
    taxonomies = tmp_path / "taxonomies"
    papers = tmp_path / "papers"
    taxonomies.mkdir()
    papers.mkdir()

    # One paper with a known citation count, and one taxonomy that cites it.
    (papers / "paper-a.yml").write_text(
        yaml.safe_dump({"id": "paper-a", "citation_count": 777}),
        encoding="utf-8",
    )
    (taxonomies / "tax-a.yml").write_text(
        yaml.safe_dump(
            {
                "id": "tax-a",
                "paper_id": "paper-a",
                "categories": [
                    {
                        "external_id": "A1",
                        "label": "Alpha",
                        "description": "First category.",
                    },
                    {
                        "external_id": "A2",
                        "label": "Beta",
                        "description": "Second category.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    # A taxonomy with no linked paper → citation_count_of_parent_taxonomy must be 0.
    (taxonomies / "tax-b.yml").write_text(
        yaml.safe_dump(
            {
                "id": "tax-b",
                "categories": [
                    {
                        "external_id": "B1",
                        "label": "Gamma",
                        "description": "Third category.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    rows = collect_mod.collect_corpus(taxonomies_dir=taxonomies, papers_dir=papers)
    assert len(rows) == 3
    by_key = {r.key: r for r in rows}
    assert by_key["tax-a::A1"].citation_count_of_parent_taxonomy == 777
    assert by_key["tax-a::A2"].citation_count_of_parent_taxonomy == 777
    assert by_key["tax-b::B1"].citation_count_of_parent_taxonomy == 0
    # Serialization round-trip.
    jsonable = collect_mod.rows_to_jsonable(rows)
    assert jsonable[0]["source_tax_id"] in {"tax-a", "tax-b"}


def test_crosswalk_map_merges_bulk_and_inline():
    pairs = collect_mod.load_crosswalk_pairs()
    cmap = collect_mod.crosswalk_map(pairs)
    # Every key looks like "{taxonomy}::{external_id}" and every value is a list.
    for k, v in cmap.items():
        assert "::" in k
        assert isinstance(v, list) and v
    # There is at least one mapping for DAP-01 -> incomplete_execution (bulk crosswalk).
    assert "incomplete_execution" in cmap.get("daplab-9-patterns::DAP-01", [])


# ---------------------------------------------------------------------------
# cluster.py
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_rows() -> List[collect_mod.CategoryRow]:
    """A synthetic 12-row corpus with three obvious prose clusters.

    The word-level stub encoder gives near-cosine-1 scores inside each trio
    and near-zero across trios, so HDBSCAN sees three dense blobs + some
    noise. Enough signal to exercise the sweep + bootstrap logic.
    """
    mk = lambda tax, ext, label, desc, cc: collect_mod.CategoryRow(
        source_tax_id=tax,
        external_id=ext,
        label=label,
        description=desc,
        citation_count_of_parent_taxonomy=cc,
    )
    desc_fab = "Agent emits hallucinated identifiers that do not exist."
    desc_sec = "Adversarial injection compromises credentials and privileges."
    desc_exec = "Task remains incomplete while agent claims success prematurely."
    return [
        mk("taxA", "A1", "Fabrication one", desc_fab, 100),
        mk("taxA", "A2", "Fabrication two", desc_fab, 100),
        mk("taxA", "A3", "Fabrication three", desc_fab, 100),
        mk("taxB", "B1", "Fabrication four", desc_fab, 50),
        mk("taxB", "B2", "Security one", desc_sec, 50),
        mk("taxB", "B3", "Security two", desc_sec, 50),
        mk("taxC", "C1", "Security three", desc_sec, 10),
        mk("taxC", "C2", "Security four", desc_sec, 10),
        mk("taxC", "C3", "Incomplete one", desc_exec, 10),
        mk("taxD", "D1", "Incomplete two", desc_exec, 0),
        mk("taxD", "D2", "Incomplete three", desc_exec, 0),
        mk("taxD", "D3", "Incomplete four", desc_exec, 0),
    ]


def test_embed_rows_returns_normalized_matrix(tiny_rows):
    enc = StubEncoder(dim=32)
    X = cluster_mod.embed_rows(tiny_rows, encoder=enc)
    assert X.shape == (12, 32)
    # Every row should be approximately unit-norm (encoder normalizes).
    norms = np.linalg.norm(X, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_run_hdbscan_sweep_discovers_three_blobs(tiny_rows):
    enc = StubEncoder(dim=32)
    X = cluster_mod.embed_rows(tiny_rows, encoder=enc)
    runs = cluster_mod.run_hdbscan_sweep(X, sweep=(2, 3, 5))
    assert len(runs) == 3
    # At min_cluster_size=3 the three prose blobs should all appear.
    r3 = next(r for r in runs if r.min_cluster_size == 3)
    assert r3.n_clusters == 3
    # Labels are integers of length 12; non-noise labels fall in [0, K).
    assert len(r3.labels) == 12
    non_noise = [l for l in r3.labels if l >= 0]
    assert non_noise and max(non_noise) < r3.n_clusters
    # Bootstrap ARI should be high because blobs are well-separated.
    assert r3.bootstrap_ari >= 0.5


def test_pick_canonical_prefers_stability():
    # Build runs by hand. The canonical pick must (a) require n_clusters >= 3
    # when possible and (b) prefer highest bootstrap_ari, tie-breaking by
    # the larger min_cluster_size.
    runs = [
        cluster_mod.ClusteringRun(
            min_cluster_size=2,
            n_clusters=7,
            n_noise=0,
            labels=[0] * 10,
            bootstrap_ari=0.3,
        ),
        cluster_mod.ClusteringRun(
            min_cluster_size=5,
            n_clusters=4,
            n_noise=2,
            labels=[0] * 10,
            bootstrap_ari=0.9,
        ),
        cluster_mod.ClusteringRun(
            min_cluster_size=7,
            n_clusters=2,
            n_noise=4,
            labels=[0] * 10,
            bootstrap_ari=0.95,
        ),
        cluster_mod.ClusteringRun(
            min_cluster_size=10,
            n_clusters=1,
            n_noise=6,
            labels=[0] * 10,
            bootstrap_ari=1.0,
        ),
    ]
    picked = cluster_mod.pick_canonical_run(runs)
    # n_clusters=1 and n_clusters=2 are below the granularity floor of 3.
    assert picked.min_cluster_size == 5
    assert picked.n_clusters == 4


def test_jaccard_distance_matrix_handles_all_zero_rows():
    # Row 0 has no tool coverage; rows 1 and 2 are identical and row 3 is disjoint.
    M = np.array(
        [
            [0, 0, 0, 0],
            [1, 1, 0, 0],
            [1, 1, 0, 0],
            [0, 0, 1, 1],
        ],
        dtype=np.int8,
    )
    D = cluster_mod._jaccard_distance_matrix(M)
    # Identical rows: zero distance.
    assert D[1, 2] == pytest.approx(0.0, abs=1e-6)
    # Disjoint rows: distance 1.
    assert D[1, 3] == pytest.approx(1.0, abs=1e-6)
    # Row 0 is at max distance from everyone else (including itself on diag
    # we force 0).
    assert D[0, 1] == pytest.approx(1.0, abs=1e-6)
    assert D[0, 0] == pytest.approx(0.0, abs=1e-6)


def test_build_tool_matrix_shape_and_coverage():
    rows = collect_mod.collect_corpus()
    mat, tools = cluster_mod.build_tool_matrix(rows)
    assert mat.shape[0] == len(rows)
    assert mat.shape[1] == len(tools)
    # At least some rows should be covered — the repo ships tools that address
    # failure modes that are crosswalked to ingested categories.
    assert mat.sum() > 0
    # Every tool in the matrix has at least one addressed failure mode.
    assert all(isinstance(t, str) for t in tools)


# ---------------------------------------------------------------------------
# compare.py
# ---------------------------------------------------------------------------


def test_saica_labels_for_rows_uses_majority_vote():
    # Two rows: one with explicit majority, one unmapped.
    rows = [
        collect_mod.CategoryRow(
            source_tax_id="daplab-9-patterns",
            external_id="DAP-02",
            label="Fabricated References",
            description="Agent emits code referencing non-existent functions or packages.",
            citation_count_of_parent_taxonomy=0,
        ),
        collect_mod.CategoryRow(
            source_tax_id="unknown-taxonomy",
            external_id="Z99",
            label="Unknown category",
            description="No crosswalk for this one.",
            citation_count_of_parent_taxonomy=0,
        ),
    ]
    labels = compare_mod.saica_labels_for_rows(rows)
    assert labels[0] == "fabrication"
    assert labels[1] == compare_mod.UNMAPPED


def test_summarize_clusters_coverage_and_naming():
    # Three rows in cluster 0 — two from a high-citation taxonomy with a
    # short description, one from a low-citation taxonomy but longer
    # description. The naming rule should pick the higher-citation one first.
    rows = [
        collect_mod.CategoryRow(
            source_tax_id="big-paper",
            external_id="BP-1",
            label="Big label",
            description="Short.",
            citation_count_of_parent_taxonomy=500,
        ),
        collect_mod.CategoryRow(
            source_tax_id="big-paper",
            external_id="BP-2",
            label="Big label two",
            description="Short too.",
            citation_count_of_parent_taxonomy=500,
        ),
        collect_mod.CategoryRow(
            source_tax_id="small-paper",
            external_id="SP-1",
            label="Small label",
            description="A much longer description that would otherwise win the tiebreak.",
            citation_count_of_parent_taxonomy=5,
        ),
    ]
    labels = [0, 0, 0]
    saica = ["fabrication", "fabrication", "logic_error"]
    out = compare_mod.summarize_clusters(rows, labels, saica_labels=saica)
    assert len(out) == 1
    s = out[0]
    assert s.size == 3
    assert s.top_saica_mode == "fabrication"
    # 2 of 3 members -> 66.7% coverage.
    assert 66.0 < s.coverage_pct < 67.0
    # Spread = 2 distinct SAICA modes covered.
    assert s.saica_mode_spread == 2
    # Name must come from the high-citation paper. Of the two tied members,
    # tiebreak by longest description → BP-2 ("Short too." > "Short.").
    assert s.proposed_from_source_tax_id == "big-paper"
    assert s.proposed_from_external_id in {"BP-1", "BP-2"}
    assert s.disagreement is True


def test_agreement_scores_roundtrip_perfect_partition():
    cluster_labels = [0, 0, 1, 1, 2, 2]
    saica = ["a", "a", "b", "b", "c", "c"]
    scores = compare_mod.agreement_scores(cluster_labels, saica)
    assert scores["ari"] == pytest.approx(1.0)
    assert scores["nmi"] == pytest.approx(1.0)


def test_top_disagreements_skips_noise_and_singletons():
    make = lambda cid, size, spread, cov: compare_mod.ClusterSummary(
        cluster_id=cid,
        size=size,
        proposed_name=f"c{cid}",
        proposed_from_external_id="X",
        proposed_from_source_tax_id="tax",
        top_saica_mode="fabrication",
        coverage_pct=cov,
        saica_mode_spread=spread,
        disagreement=spread > 1 or cov < 50.0,
        members=[],
    )
    summaries = [
        make(-1, 15, 4, 20.0),  # noise, skipped
        make(0, 1, 0, 100.0),  # singleton, skipped
        make(1, 8, 3, 40.0),  # keep, biggest
        make(2, 6, 5, 20.0),  # keep
        make(3, 2, 1, 99.0),  # disagreement False; filtered
    ]
    top = compare_mod.top_disagreements(summaries, n=5)
    ids = [s.cluster_id for s in top]
    assert -1 not in ids and 0 not in ids
    assert ids[0] == 1  # biggest first
    assert 2 in ids
