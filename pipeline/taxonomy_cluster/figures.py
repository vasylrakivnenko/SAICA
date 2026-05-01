"""Matplotlib figures for the taxonomy-clustering study.

Five PNGs, each capped at 150 DPI and kept under 200 KB by using small
figure sizes + default rasterized scatter markers. We always reload
matplotlib with the ``Agg`` backend so the CLI is fully headless.

Figures:
* ``umap_by_source_taxonomy.png``   — UMAP with marker color = source taxonomy
* ``umap_by_hdbscan_cluster.png``   — UMAP with marker color = text-cluster id
* ``umap_by_saica_match.png``       — UMAP with marker color = SAICA top match
* ``cluster_count_vs_min_size.png`` — n_clusters + bootstrap_ari vs min_cluster_size
* ``agreement_heatmap.png``         — rows=algorithmic cluster, cols=SAICA mode
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Sequence

import numpy as np

log = logging.getLogger(__name__)

DPI = 150
FIG_SIZE = (6.4, 4.8)  # matches a conservative sub-200KB PNG at 150 DPI


def _use_agg():
    """Force non-interactive backend — CLI runs on headless CI boxes."""
    import matplotlib

    matplotlib.use("Agg", force=True)


def compute_umap(X: np.ndarray, *, n_neighbors: int = 15, seed: int = 42) -> np.ndarray:
    """2-D UMAP projection of an (N, D) embedding matrix.

    Uses cosine metric — matches how the embeddings were trained and how our
    HDBSCAN step interpreted them (L2-normalized => cosine equivalent).
    """
    import umap

    n = X.shape[0]
    # UMAP requires n_neighbors < n_samples; clamp for tiny corpora in tests.
    nn = max(2, min(n_neighbors, n - 1))
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=nn,
        min_dist=0.1,
        metric="cosine",
        random_state=seed,
    )
    return np.asarray(reducer.fit_transform(X), dtype=np.float32)


# ---------------------------------------------------------------------------
# Scatter helpers
# ---------------------------------------------------------------------------


def _scatter_by_label(
    xy: np.ndarray,
    labels: Sequence,
    *,
    title: str,
    out_path: Path,
    legend: bool = True,
) -> Path:
    _use_agg()
    import matplotlib.pyplot as plt

    uniq = sorted(set(labels), key=lambda v: (isinstance(v, int) and v < 0, str(v)))
    cmap = plt.get_cmap("tab20", max(len(uniq), 1))
    fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=DPI)
    for i, lbl in enumerate(uniq):
        mask = np.array([l == lbl for l in labels])
        ax.scatter(
            xy[mask, 0],
            xy[mask, 1],
            s=18,
            alpha=0.85,
            color=cmap(i % 20),
            label=str(lbl),
            linewidths=0.0,
        )
    ax.set_title(title)
    ax.set_xticks([])
    ax.set_yticks([])
    if legend and len(uniq) <= 20:
        ax.legend(
            loc="center left",
            bbox_to_anchor=(1.01, 0.5),
            fontsize=7,
            frameon=False,
            markerscale=0.8,
        )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_umap_by_source(
    xy: np.ndarray, source_ids: Sequence[str], *, out_path: Path
) -> Path:
    return _scatter_by_label(
        xy,
        list(source_ids),
        title="UMAP of 128 categories — by source taxonomy",
        out_path=out_path,
    )


def plot_umap_by_cluster(
    xy: np.ndarray, cluster_labels: Sequence[int], *, out_path: Path
) -> Path:
    return _scatter_by_label(
        xy,
        [int(x) for x in cluster_labels],
        title="UMAP of 128 categories — by HDBSCAN cluster",
        out_path=out_path,
    )


def plot_umap_by_saica(
    xy: np.ndarray, saica_labels: Sequence[str], *, out_path: Path
) -> Path:
    return _scatter_by_label(
        xy,
        list(saica_labels),
        title="UMAP of 128 categories — by majority-vote SAICA FailureMode",
        out_path=out_path,
    )


# ---------------------------------------------------------------------------
# Sweep plot
# ---------------------------------------------------------------------------


def plot_cluster_count_vs_min_size(
    sweep: Sequence[Dict],
    *,
    out_path: Path,
    title: str = "HDBSCAN sweep: cluster count & bootstrap stability",
) -> Path:
    """Double-axis line plot over the min_cluster_size sweep."""
    _use_agg()
    import matplotlib.pyplot as plt

    xs = [int(r["min_cluster_size"]) for r in sweep]
    n_clusters = [int(r["n_clusters"]) for r in sweep]
    ari = [float(r["bootstrap_ari"]) for r in sweep]

    fig, ax1 = plt.subplots(figsize=FIG_SIZE, dpi=DPI)
    ax1.plot(xs, n_clusters, marker="o", color="#1f77b4", label="n clusters")
    ax1.set_xlabel("min_cluster_size")
    ax1.set_ylabel("n clusters", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax2 = ax1.twinx()
    ax2.plot(xs, ari, marker="s", color="#d62728", label="bootstrap ARI")
    ax2.set_ylabel("bootstrap ARI", color="#d62728")
    ax2.set_ylim(0.0, 1.05)
    ax2.tick_params(axis="y", labelcolor="#d62728")
    ax1.set_title(title)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# Agreement heatmap
# ---------------------------------------------------------------------------


def plot_agreement_heatmap(
    cluster_labels: Sequence[int],
    saica_labels: Sequence[str],
    *,
    out_path: Path,
    title: str = "Cluster vs SAICA mode (row-normalized counts)",
) -> Path:
    """Heatmap of row-normalized co-occurrence: cluster id x SAICA mode."""
    _use_agg()
    import matplotlib.pyplot as plt

    cluster_labels = [int(x) for x in cluster_labels]
    cluster_ids = sorted(set(cluster_labels))
    saica_ids = sorted(set(saica_labels))
    c_idx = {c: i for i, c in enumerate(cluster_ids)}
    s_idx = {s: i for i, s in enumerate(saica_ids)}
    M = np.zeros((len(cluster_ids), len(saica_ids)), dtype=np.float32)
    for c, s in zip(cluster_labels, saica_labels):
        M[c_idx[c], s_idx[s]] += 1
    row_sums = M.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        Mn = np.where(row_sums > 0, M / row_sums, 0.0)

    fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=DPI)
    im = ax.imshow(Mn, aspect="auto", cmap="viridis", vmin=0.0, vmax=1.0)
    ax.set_xticks(range(len(saica_ids)))
    ax.set_xticklabels(saica_ids, rotation=45, ha="right", fontsize=7)
    ax.set_yticks(range(len(cluster_ids)))
    ax.set_yticklabels([f"c{c}" for c in cluster_ids], fontsize=7)
    ax.set_title(title)
    fig.colorbar(im, ax=ax, shrink=0.75, label="row share")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return out_path
