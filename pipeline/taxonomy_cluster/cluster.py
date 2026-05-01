"""Run the two parallel clusterings over the 128-category corpus.

Clustering A (text): HDBSCAN over L2-normalized sentence-transformer
embeddings of ``label + description``. Cosine-equivalent metric (Euclidean
on normalized vectors). Sweep ``min_cluster_size in {2, 3, 5, 7, 10}``
and measure bootstrap-ARI stability.

Clustering B (bipartite): HDBSCAN over Jaccard distance between rows of
the sparse (category x tool) reachability matrix. A category c is
"reachable from" tool t if there exists a SAICA FailureMode s such that
s in t.addresses_failure_modes AND (s, c) is in some crosswalk. Categories
that reach no tools fall out as all-zero rows and are handled explicitly.

Same min_cluster_size sweep + bootstrap-ARI protocol in both cases. The
picked canonical setting is the one with the highest bootstrap-ARI subject
to producing at least 3 non-noise clusters — we want stability but also
enough granularity to compare against SAICA's 11-way partition.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

from pipeline.embeddings.compute import encode_texts
from pipeline.taxonomy_cluster.collect import (
    CategoryRow,
    crosswalk_map,
    load_crosswalk_pairs,
    load_tool_failure_modes,
)

log = logging.getLogger(__name__)

# HDBSCAN sweep — spans "trust every local density bump" (2) through
# "only honor clusters big enough to plausibly be their own family" (10).
MIN_CLUSTER_SIZE_SWEEP: Tuple[int, ...] = (2, 3, 5, 7, 10)

# Bootstrap: hold out ~15% of rows each iteration, compute ARI on the
# intersection. 10 bootstraps per setting is enough to tell "stable" from
# "volatile" at the precision we need for a paper appendix.
N_BOOTSTRAP = 10
BOOTSTRAP_FRAC = 0.85
RNG_SEED = 20260422


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


def build_embedding_texts(rows: Sequence[CategoryRow]) -> List[str]:
    return [r.text_for_embedding for r in rows]


def embed_rows(rows: Sequence[CategoryRow], *, encoder=None) -> np.ndarray:
    """Return an (N, D) matrix of L2-normalized embeddings."""
    texts = build_embedding_texts(rows)
    return encode_texts(texts, encoder=encoder)


# ---------------------------------------------------------------------------
# HDBSCAN helpers
# ---------------------------------------------------------------------------


def _hdbscan(
    X: np.ndarray,
    *,
    min_cluster_size: int,
    metric: str = "euclidean",
) -> np.ndarray:
    """Thin wrapper so tests can mock the cluster layer without importing sklearn."""
    from sklearn.cluster import HDBSCAN

    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=1,
        metric=metric,
        cluster_selection_method="eom",
    )
    return model.fit_predict(X)


def _adjusted_rand(labels_a: Sequence[int], labels_b: Sequence[int]) -> float:
    from sklearn.metrics import adjusted_rand_score

    return float(adjusted_rand_score(list(labels_a), list(labels_b)))


def _bootstrap_ari(
    X: np.ndarray,
    *,
    min_cluster_size: int,
    metric: str,
    n_bootstrap: int = N_BOOTSTRAP,
    frac: float = BOOTSTRAP_FRAC,
    seed: int = RNG_SEED,
) -> float:
    """Mean pairwise ARI across ``n_bootstrap`` resamples (on shared indices).

    We resample rows (without replacement) at ``frac`` rate, cluster the
    subset, and compare every pair of bootstrap runs on the intersection of
    their sampled indices. This measures "if I rerun with slightly different
    data, does the partition hold?" — the standard HDBSCAN stability check.
    """
    n = X.shape[0]
    rng = np.random.default_rng(seed)
    k = max(min_cluster_size + 1, int(round(frac * n)))
    runs: List[Dict[int, int]] = []
    for _ in range(n_bootstrap):
        idx = rng.choice(n, size=k, replace=False)
        idx.sort()
        if metric == "precomputed":
            # Precomputed-distance matrices must be sliced symmetrically
            # (rows AND columns) so HDBSCAN sees a square matrix.
            sub = X[np.ix_(idx, idx)]
        else:
            sub = X[idx]
        labels = _hdbscan(sub, min_cluster_size=min_cluster_size, metric=metric)
        runs.append({int(i): int(l) for i, l in zip(idx, labels)})

    scores: List[float] = []
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            shared = sorted(set(runs[i].keys()) & set(runs[j].keys()))
            if len(shared) < 2:
                continue
            a = [runs[i][s] for s in shared]
            b = [runs[j][s] for s in shared]
            scores.append(_adjusted_rand(a, b))
    return float(np.mean(scores)) if scores else 0.0


# ---------------------------------------------------------------------------
# Clustering run result
# ---------------------------------------------------------------------------


@dataclass
class ClusteringRun:
    """One HDBSCAN run + its bootstrap stability figure."""

    min_cluster_size: int
    n_clusters: int  # count of non-noise clusters
    n_noise: int  # points labelled -1
    labels: List[int]  # per-row cluster id (-1 == noise)
    bootstrap_ari: float  # mean pairwise ARI over N bootstrap resamples

    def to_jsonable(self) -> Dict:
        return {
            "min_cluster_size": self.min_cluster_size,
            "n_clusters": self.n_clusters,
            "n_noise": self.n_noise,
            "labels": list(self.labels),
            "bootstrap_ari": round(self.bootstrap_ari, 4),
        }


def run_hdbscan_sweep(
    X: np.ndarray,
    *,
    metric: str = "euclidean",
    sweep: Sequence[int] = MIN_CLUSTER_SIZE_SWEEP,
) -> List[ClusteringRun]:
    """Run HDBSCAN at each ``min_cluster_size`` and return per-setting results."""
    runs: List[ClusteringRun] = []
    for mcs in sweep:
        labels = _hdbscan(X, min_cluster_size=mcs, metric=metric)
        n_clusters = int(len({int(l) for l in labels if l >= 0}))
        n_noise = int(sum(1 for l in labels if l < 0))
        ari = _bootstrap_ari(X, min_cluster_size=mcs, metric=metric)
        runs.append(
            ClusteringRun(
                min_cluster_size=mcs,
                n_clusters=n_clusters,
                n_noise=n_noise,
                labels=[int(l) for l in labels],
                bootstrap_ari=ari,
            )
        )
    return runs


def pick_canonical_run(runs: Sequence[ClusteringRun]) -> ClusteringRun:
    """Pick the setting with the best stability-vs-granularity tradeoff.

    We require at least 3 non-noise clusters (so the result can meaningfully
    be compared to SAICA's 11) and, among qualifying runs, pick the one with
    the highest bootstrap ARI. Ties broken by larger ``min_cluster_size``
    (prefer the more conservative prior, standard practice when a plateau
    spans multiple settings).
    """
    eligible = [r for r in runs if r.n_clusters >= 3]
    pool = eligible or list(runs)
    return sorted(
        pool, key=lambda r: (r.bootstrap_ari, r.min_cluster_size), reverse=True
    )[0]


# ---------------------------------------------------------------------------
# Bipartite construction
# ---------------------------------------------------------------------------


def build_tool_matrix(rows: Sequence[CategoryRow]) -> Tuple[np.ndarray, List[str]]:
    """Build the (N_categories x M_tools) binary reachability matrix.

    A category c is marked reachable from tool t if some SAICA FailureMode s
    satisfies both (s in t.addresses_failure_modes) and ((s, c) in crosswalk).
    Matrix is dense np.ndarray of shape (N, M) dtype=int8 — N=128, M on the
    order of a few dozen (only tools that address at least one failure mode
    and where that mode is crosswalked to at least one ingested category).
    """
    pairs = load_crosswalk_pairs()
    cat_to_modes = crosswalk_map(pairs)  # "{tax}::{ext}" -> [saica_value]
    tool_modes = load_tool_failure_modes()  # tool_id -> [saica_value]

    tools_sorted = sorted(tool_modes.keys())
    tool_idx = {t: i for i, t in enumerate(tools_sorted)}
    N, M = len(rows), len(tools_sorted)
    mat = np.zeros((N, M), dtype=np.int8)

    for ri, row in enumerate(rows):
        modes_for_row = set(cat_to_modes.get(row.key, []))
        if not modes_for_row:
            continue
        for t, tmodes in tool_modes.items():
            if modes_for_row & set(tmodes):
                mat[ri, tool_idx[t]] = 1

    return mat, tools_sorted


def _jaccard_distance_matrix(M: np.ndarray) -> np.ndarray:
    """Return N x N pairwise Jaccard distance over binary rows.

    All-zero rows get distance 1.0 to every other row (including each other)
    so HDBSCAN treats them as noise-candidates rather than collapsing them
    into one giant cluster of "no-tool-coverage" categories.
    """
    B = (M > 0).astype(np.float32)
    inter = B @ B.T
    rs = B.sum(axis=1, keepdims=True)
    union = rs + rs.T - inter
    # Avoid div-by-zero for all-zero rows: treat as max distance.
    with np.errstate(divide="ignore", invalid="ignore"):
        sim = np.where(union > 0, inter / union, 0.0)
    dist = 1.0 - sim
    # Numerical cleanup.
    np.fill_diagonal(dist, 0.0)
    return dist.astype(np.float32)


def cluster_bipartite(
    rows: Sequence[CategoryRow],
    *,
    sweep: Sequence[int] = MIN_CLUSTER_SIZE_SWEEP,
) -> Tuple[List[ClusteringRun], np.ndarray, List[str]]:
    """Return sweep results + the matrix + tool labels for downstream figures."""
    mat, tools = build_tool_matrix(rows)
    if mat.size == 0 or mat.sum() == 0:
        # Degenerate fallback: no tool coverage at all.
        labels = np.full(len(rows), -1, dtype=int)
        runs = [
            ClusteringRun(
                min_cluster_size=mcs,
                n_clusters=0,
                n_noise=len(rows),
                labels=[-1] * len(rows),
                bootstrap_ari=0.0,
            )
            for mcs in sweep
        ]
        return runs, mat, tools

    D = _jaccard_distance_matrix(mat)
    runs: List[ClusteringRun] = []
    for mcs in sweep:
        labels = _hdbscan(D, min_cluster_size=mcs, metric="precomputed")
        n_clusters = int(len({int(l) for l in labels if l >= 0}))
        n_noise = int(sum(1 for l in labels if l < 0))
        ari = _bootstrap_ari(D, min_cluster_size=mcs, metric="precomputed")
        runs.append(
            ClusteringRun(
                min_cluster_size=mcs,
                n_clusters=n_clusters,
                n_noise=n_noise,
                labels=[int(l) for l in labels],
                bootstrap_ari=ari,
            )
        )
    return runs, mat, tools


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def save_embeddings(
    rows: Sequence[CategoryRow],
    X: np.ndarray,
    out_dir: Path,
) -> Tuple[Path, Path]:
    """Persist the (N, D) matrix + row-parallel metadata."""
    out_dir.mkdir(parents=True, exist_ok=True)
    np_path = out_dir / "embeddings.npy"
    meta_path = out_dir / "metadata.json"
    np.save(np_path, X)
    meta = {
        "n_rows": int(X.shape[0]),
        "dim": int(X.shape[1]),
        "keys": [r.key for r in rows],
        "labels": [r.label for r in rows],
        "source_tax_ids": [r.source_tax_id for r in rows],
    }
    with meta_path.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, sort_keys=False)
    return np_path, meta_path


def write_hdbscan_runs(
    runs: Sequence[ClusteringRun],
    canonical: ClusteringRun,
    out_path: Path,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sweep": [r.to_jsonable() for r in runs],
        "canonical_min_cluster_size": canonical.min_cluster_size,
        "canonical_n_clusters": canonical.n_clusters,
        "canonical_bootstrap_ari": round(canonical.bootstrap_ari, 4),
        "canonical_labels": list(canonical.labels),
    }
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
    return out_path


def write_bipartite_runs(
    runs: Sequence[ClusteringRun],
    canonical: ClusteringRun,
    mat: np.ndarray,
    tools: Sequence[str],
    keys: Sequence[str],
    out_path: Path,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    nonzero_rows = int((mat.sum(axis=1) > 0).sum())
    payload = {
        "matrix_shape": [int(mat.shape[0]), int(mat.shape[1])],
        "nonzero_rows": nonzero_rows,
        "tool_ids": list(tools),
        "keys": list(keys),
        "sweep": [r.to_jsonable() for r in runs],
        "canonical_min_cluster_size": canonical.min_cluster_size,
        "canonical_n_clusters": canonical.n_clusters,
        "canonical_bootstrap_ari": round(canonical.bootstrap_ari, 4),
        "canonical_labels": list(canonical.labels),
    }
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
    return out_path
