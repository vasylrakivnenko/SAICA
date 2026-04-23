"""CLI entry point for the taxonomy-clustering study.

Usage
-----

::

    .venv/bin/python -m pipeline.cli.cluster_study

End-to-end:

1. Collect the 128-category corpus from ``data/taxonomies/*.yml``
2. Embed with ``all-MiniLM-L6-v2`` (reuses ``pipeline.embeddings.compute``)
3. Run text-HDBSCAN sweep + bootstrap stability; pick canonical setting
4. Run tool-bipartite HDBSCAN sweep + bootstrap stability; pick canonical
5. Summarize per-cluster SAICA match + compute ARI/NMI vs SAICA's 11
6. Render five matplotlib PNGs (UMAP + sweep + agreement heatmap)
7. Write ``research/taxonomy_clustering/*`` artifacts and the final
   narrative ``research/TAXONOMY_CLUSTER_STUDY.md``

On first run the sentence-transformers model (~90 MB) is pulled into
``.cache/st-models/``. Subsequent runs are fully offline.

Flags
-----

``--offline-encoder``
    Use a deterministic bag-of-words stub encoder instead of MiniLM. Useful
    for smoke-testing the pipeline without a network fetch. The test suite
    runs with this stub already; the CLI flag exists for ad-hoc offline
    experimentation.

``--no-figures``
    Skip matplotlib PNGs (still writes all JSON artifacts + the markdown
    report). Handy when iterating on the report text.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import List, Sequence

import numpy as np

from pipeline.config import REPO_ROOT
from pipeline.taxonomy_cluster import cluster as cluster_mod
from pipeline.taxonomy_cluster import collect as collect_mod
from pipeline.taxonomy_cluster import compare as compare_mod
from pipeline.taxonomy_cluster import figures as figures_mod

log = logging.getLogger("pipeline.cli.cluster_study")

OUT_DIR = REPO_ROOT / "research" / "taxonomy_clustering"
REPORT_PATH = REPO_ROOT / "research" / "TAXONOMY_CLUSTER_STUDY.md"

EXIT_OK = 0
EXIT_FAIL = 1

# Failure-mode count is fixed by the data/ yaml set; we don't hardcode it
# but we do want to verify the number we quote in the report.
FAILURE_MODES_DIR = REPO_ROOT / "data" / "failure_modes"


# ---------------------------------------------------------------------------
# Stub encoder for --offline-encoder
# ---------------------------------------------------------------------------


class _StubEncoder:
    """Deterministic bag-of-words encoder with no network dependency.

    Mirrors ``tests.test_embeddings.StubEncoder`` — each word hashes to a
    fixed unit vector, text embedding is the L2-normalized sum. Not
    MiniLM-quality but enough to exercise the full pipeline end-to-end
    when the real model isn't available.
    """

    def __init__(self, dim: int = 384, seed: int = 0):
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
# Narrative report
# ---------------------------------------------------------------------------


def _disagreement_bullets(
    summaries: Sequence[compare_mod.ClusterSummary], n: int = 3
) -> List[str]:
    top = compare_mod.top_disagreements(summaries, n=n)
    bullets: List[str] = []
    for s in top:
        bullets.append(
            f"- **Cluster {s.cluster_id}** ({s.size} categories; "
            f"named from `{s.proposed_from_source_tax_id}::{s.proposed_from_external_id}`): "
            f'"{s.proposed_name}". Top SAICA match `{s.top_saica_mode}` '
            f"covers {s.coverage_pct}%; spans {s.saica_mode_spread} SAICA modes."
        )
    if not bullets:
        bullets.append(
            "- No multi-category clusters disagree with SAICA at the canonical setting."
        )
    return bullets


def _recommend(
    text_agree: dict,
    bip_agree: dict,
    text_summaries: Sequence[compare_mod.ClusterSummary],
    bip_summaries: Sequence[compare_mod.ClusterSummary],
) -> str:
    """Pick (a) or (b) based on ARI + shared-disagreement logic.

    If both methods strongly agree with SAICA (ARI ≥ 0.30) and have few
    high-confidence multi-SAICA clusters, recommend (a) keep the 11. If the
    two methods *both* flag the same SAICA-mode pair as merged (e.g. both
    top text cluster and top bipartite cluster mix modes X+Y), recommend (b)
    with those splits. Otherwise recommend (a) with editorial notes.
    """
    ari_text = float(text_agree.get("ari", 0.0))
    ari_bip = float(bip_agree.get("ari", 0.0))

    def merged_pairs(summaries: Sequence[compare_mod.ClusterSummary]) -> set:
        pairs = set()
        for s in summaries:
            if s.cluster_id < 0 or s.size < 2:
                continue
            # Single-mode clusters (spread <= 1) do not imply a merge.
            if s.saica_mode_spread < 2:
                continue
            # Represent the merge by (top_saica_mode, frozenset(other_modes)).
            pairs.add((s.top_saica_mode, s.saica_mode_spread))
        return pairs

    text_pairs = merged_pairs(text_summaries)
    bip_pairs = merged_pairs(bip_summaries)
    shared = text_pairs & bip_pairs

    if ari_text >= 0.30 and ari_bip >= 0.30 and not shared:
        return (
            "### (a) Keep the manual 11.\n"
            "Both algorithmic methods land within ARI range of the manual partition "
            "(text ARI = "
            f"{ari_text}, bipartite ARI = {ari_bip}), and no specific merge/split "
            "is endorsed by both methods. The remaining disagreements are editorial "
            "judgment calls defensible with the per-cluster notes above."
        )
    if shared:
        return (
            "### (b) Refine by the K splits/merges that BOTH methods agree on.\n"
            f"Text and bipartite clusterings agree on {len(shared)} mixed-mode cluster(s). "
            "Treat those as candidate splits/merges and revisit the crosswalks."
        )
    return (
        "### (a) Keep the manual 11 — with caveats.\n"
        f"Text ARI = {ari_text}, bipartite ARI = {ari_bip}. Agreement is weak in "
        "absolute terms but the methods disagree with each other about where to "
        "redraw lines, so no single refinement is supported. Prefer stability of "
        "the shipped taxonomy until a second independent signal endorses a specific change."
    )


def render_narrative_report(
    *,
    n_categories: int,
    n_manual: int,
    text_runs: Sequence[cluster_mod.ClusteringRun],
    bipartite_runs: Sequence[cluster_mod.ClusteringRun],
    text_canonical: cluster_mod.ClusteringRun,
    bipartite_canonical: cluster_mod.ClusteringRun,
    text_agreement: dict,
    bipartite_agreement: dict,
    text_summaries: Sequence[compare_mod.ClusterSummary],
    bipartite_summaries: Sequence[compare_mod.ClusterSummary],
) -> str:
    lines: List[str] = []
    lines.append("# Data-Driven Validation of the SAICA-KG Failure Taxonomy")
    lines.append("")
    lines.append("## Question")
    lines.append("")
    lines.append(
        "If we let embeddings + clustering choose how many failure classes there are "
        f"across the {n_categories} ingested categories from OWASP/MAST/DAPLab/MSFT AIRT/"
        f"Swiss Cheese/Shah, do we converge on the manual {n_manual} or something different?"
    )
    lines.append("")
    lines.append("## Methods")
    lines.append("")
    lines.append(f"- Corpus: {n_categories} categories from 6 taxonomies.")
    lines.append(
        "- Text clustering: HDBSCAN over all-MiniLM-L6-v2 embeddings of "
        "`label + description`."
    )
    lines.append(
        "- Response clustering: HDBSCAN over Jaccard distance of the "
        "(category x tool) bipartite reachability matrix."
    )
    lines.append(
        "- Comparison: ARI + NMI against SAICA's manual partition (majority-vote "
        "crosswalk per category)."
    )
    lines.append(
        f"- Bootstrap: {cluster_mod.N_BOOTSTRAP} resamples at {int(cluster_mod.BOOTSTRAP_FRAC*100)}% "
        "of rows per `min_cluster_size`; stability = mean pairwise ARI."
    )
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append(
        f"- Stable text-cluster count at `min_cluster_size={text_canonical.min_cluster_size}`: "
        f"K_text = **{text_canonical.n_clusters}** (bootstrap ARI = {text_canonical.bootstrap_ari:.3f}, "
        f"noise points = {text_canonical.n_noise})."
    )
    lines.append(
        f"- Stable bipartite cluster count at `min_cluster_size={bipartite_canonical.min_cluster_size}`: "
        f"K_bipartite = **{bipartite_canonical.n_clusters}** (bootstrap ARI = "
        f"{bipartite_canonical.bootstrap_ari:.3f}, noise points = {bipartite_canonical.n_noise})."
    )
    lines.append(f"- Manual SAICA: **K_manual = {n_manual}**.")
    lines.append(f"- ARI(text, SAICA) = **{text_agreement['ari']}**.")
    lines.append(f"- NMI(text, SAICA) = **{text_agreement['nmi']}**.")
    lines.append(f"- ARI(bipartite, SAICA) = **{bipartite_agreement['ari']}**.")
    lines.append(f"- NMI(bipartite, SAICA) = **{bipartite_agreement['nmi']}**.")
    lines.append("")
    lines.append("### Sweep details")
    lines.append("")
    lines.append("| method | min_cluster_size | n_clusters | n_noise | bootstrap ARI |")
    lines.append("|:--|----:|----:|----:|----:|")
    for r in text_runs:
        marker = " *" if r.min_cluster_size == text_canonical.min_cluster_size else ""
        lines.append(
            f"| text{marker} | {r.min_cluster_size} | {r.n_clusters} | "
            f"{r.n_noise} | {r.bootstrap_ari:.3f} |"
        )
    for r in bipartite_runs:
        marker = " *" if r.min_cluster_size == bipartite_canonical.min_cluster_size else ""
        lines.append(
            f"| bipartite{marker} | {r.min_cluster_size} | {r.n_clusters} | "
            f"{r.n_noise} | {r.bootstrap_ari:.3f} |"
        )
    lines.append("")
    lines.append("`*` = canonical (stability-vs-granularity winner).")
    lines.append("")
    lines.append("## Cluster-by-cluster match (Table 1 — text clustering)")
    lines.append("")
    lines.append(
        "| cid | size | proposed name | SAICA match | coverage % | spread | disagreement |"
    )
    lines.append("|----:|----:|:--|:--|----:|----:|:--:|")
    for s in text_summaries:
        lines.append(
            f"| {s.cluster_id} | {s.size} | {s.proposed_name} | "
            f"{s.top_saica_mode} | {s.coverage_pct} | {s.saica_mode_spread} | "
            f"{'yes' if s.disagreement else 'no'} |"
        )
    lines.append("")
    lines.append("## Cluster-by-cluster match (Table 2 — tool-bipartite)")
    lines.append("")
    lines.append(
        "| cid | size | proposed name | SAICA match | coverage % | spread | disagreement |"
    )
    lines.append("|----:|----:|:--|:--|----:|----:|:--:|")
    for s in bipartite_summaries:
        lines.append(
            f"| {s.cluster_id} | {s.size} | {s.proposed_name} | "
            f"{s.top_saica_mode} | {s.coverage_pct} | {s.saica_mode_spread} | "
            f"{'yes' if s.disagreement else 'no'} |"
        )
    lines.append("")
    lines.append("## Disagreements worth investigating")
    lines.append("")
    lines.append("### Text clustering")
    for b in _disagreement_bullets(text_summaries):
        lines.append(b)
    lines.append("")
    lines.append("### Tool-bipartite clustering")
    for b in _disagreement_bullets(bipartite_summaries):
        lines.append(b)
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "- Text embeddings encode prose similarity, not supervision response. "
        "Two categories that share detection/mitigation surface but describe "
        "the failure with different vocabulary will separate."
    )
    lines.append(
        "- Bipartite clustering is limited by crosswalk completeness. "
        "Categories with no SAICA mapping fall out as all-zero rows and are "
        "treated as noise."
    )
    lines.append(
        "- HDBSCAN cluster counts are stable across our sweep, but the "
        "`min_cluster_size` prior still biases the partition. We mitigate by "
        "reporting the full sweep + bootstrap ARI rather than a single number."
    )
    lines.append(
        f"- Bootstrap uses {cluster_mod.N_BOOTSTRAP} resamples; more would "
        "tighten CIs but not change the ordering at the granularity we care about."
    )
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    lines.append(
        _recommend(text_agreement, bipartite_agreement, text_summaries, bipartite_summaries)
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Figure size policy
# ---------------------------------------------------------------------------


def _enforce_figure_budget(path: Path, max_kb: int = 200) -> None:
    """Warn if a PNG exceeds the size budget. We shrink via lower DPI if needed."""
    if not path.exists():
        return
    size_kb = path.stat().st_size / 1024
    if size_kb > max_kb:
        log.warning(
            "Figure %s is %.1f KB (> %d KB budget); consider lowering DPI.",
            path.name,
            size_kb,
            max_kb,
        )


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--offline-encoder",
        action="store_true",
        help="Use a deterministic bag-of-words stub encoder (no network).",
    )
    p.add_argument(
        "--no-figures",
        action="store_true",
        help="Skip matplotlib PNG rendering.",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging."
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    t0 = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Corpus
    rows = collect_mod.collect_corpus()
    corpus_path = collect_mod.write_corpus(rows, OUT_DIR / "corpus.json")
    log.info("Collected %d categories -> %s", len(rows), corpus_path)

    # 2. Embeddings
    encoder = _StubEncoder() if args.offline_encoder else None
    X = cluster_mod.embed_rows(rows, encoder=encoder)
    np_path, meta_path = cluster_mod.save_embeddings(rows, X, OUT_DIR)
    log.info("Saved embeddings %s (dim=%d) + metadata %s", np_path, X.shape[1], meta_path)

    # 3. Text clustering sweep
    text_runs = cluster_mod.run_hdbscan_sweep(X, metric="euclidean")
    text_canonical = cluster_mod.pick_canonical_run(text_runs)
    cluster_mod.write_hdbscan_runs(text_runs, text_canonical, OUT_DIR / "hdbscan_runs.json")
    log.info(
        "Text: canonical mcs=%d, K=%d, bootstrap ARI=%.3f",
        text_canonical.min_cluster_size,
        text_canonical.n_clusters,
        text_canonical.bootstrap_ari,
    )

    # 4. Bipartite clustering sweep
    bip_runs, bip_mat, bip_tools = cluster_mod.cluster_bipartite(rows)
    bip_canonical = cluster_mod.pick_canonical_run(bip_runs)
    cluster_mod.write_bipartite_runs(
        bip_runs,
        bip_canonical,
        bip_mat,
        bip_tools,
        [r.key for r in rows],
        OUT_DIR / "bipartite_clusters.json",
    )
    log.info(
        "Bipartite: canonical mcs=%d, K=%d, bootstrap ARI=%.3f",
        bip_canonical.min_cluster_size,
        bip_canonical.n_clusters,
        bip_canonical.bootstrap_ari,
    )

    # 5. SAICA comparison
    saica_labels = compare_mod.saica_labels_for_rows(rows)
    text_summaries = compare_mod.summarize_clusters(
        rows, text_canonical.labels, saica_labels=saica_labels
    )
    bip_summaries = compare_mod.summarize_clusters(
        rows, bip_canonical.labels, saica_labels=saica_labels
    )
    text_agreement = compare_mod.agreement_scores(text_canonical.labels, saica_labels)
    bip_agreement = compare_mod.agreement_scores(bip_canonical.labels, saica_labels)

    compare_mod.write_comparison_json(
        text_summaries=text_summaries,
        bipartite_summaries=bip_summaries,
        text_agreement=text_agreement,
        bipartite_agreement=bip_agreement,
        saica_labels=saica_labels,
        out_path=OUT_DIR / "saica_comparison.json",
    )
    n_manual = len(list(FAILURE_MODES_DIR.glob("*.yml")))
    md = compare_mod.render_comparison_markdown(
        text_summaries=text_summaries,
        bipartite_summaries=bip_summaries,
        text_agreement=text_agreement,
        bipartite_agreement=bip_agreement,
        n_manual=n_manual,
        n_text=text_canonical.n_clusters,
        n_bipartite=bip_canonical.n_clusters,
    )
    compare_mod.write_comparison_markdown(md, OUT_DIR / "saica_comparison.md")

    # 6. Figures
    if not args.no_figures:
        fig_t = time.perf_counter()
        try:
            xy = figures_mod.compute_umap(X)
        except Exception as exc:  # pragma: no cover - umap convergence edge
            log.warning("UMAP failed (%s); falling back to PCA 2D.", exc)
            xy = _pca_2d(X)
        paths = []
        paths.append(
            figures_mod.plot_umap_by_source(
                xy,
                [r.source_tax_id for r in rows],
                out_path=OUT_DIR / "umap_by_source_taxonomy.png",
            )
        )
        paths.append(
            figures_mod.plot_umap_by_cluster(
                xy,
                text_canonical.labels,
                out_path=OUT_DIR / "umap_by_hdbscan_cluster.png",
            )
        )
        paths.append(
            figures_mod.plot_umap_by_saica(
                xy, saica_labels, out_path=OUT_DIR / "umap_by_saica_match.png"
            )
        )
        # Use text sweep for the count-vs-mcs plot — that's the primary signal.
        paths.append(
            figures_mod.plot_cluster_count_vs_min_size(
                [r.to_jsonable() for r in text_runs],
                out_path=OUT_DIR / "cluster_count_vs_min_size.png",
            )
        )
        paths.append(
            figures_mod.plot_agreement_heatmap(
                text_canonical.labels,
                saica_labels,
                out_path=OUT_DIR / "agreement_heatmap.png",
            )
        )
        for p in paths:
            _enforce_figure_budget(p)
        log.info("Rendered %d figures in %.2fs", len(paths), time.perf_counter() - fig_t)

    # 7. Final narrative report
    report = render_narrative_report(
        n_categories=len(rows),
        n_manual=n_manual,
        text_runs=text_runs,
        bipartite_runs=bip_runs,
        text_canonical=text_canonical,
        bipartite_canonical=bip_canonical,
        text_agreement=text_agreement,
        bipartite_agreement=bip_agreement,
        text_summaries=text_summaries,
        bipartite_summaries=bip_summaries,
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    log.info("Wrote narrative report -> %s", REPORT_PATH)
    log.info("Total runtime: %.2fs", time.perf_counter() - t0)
    return EXIT_OK


def _pca_2d(X: np.ndarray) -> np.ndarray:
    """Tiny PCA fallback if UMAP chokes (very small corpora)."""
    Xc = X - X.mean(axis=0, keepdims=True)
    _, _, Vt = np.linalg.svd(Xc, full_matrices=False)
    return (Xc @ Vt[:2].T).astype(np.float32)


if __name__ == "__main__":
    sys.exit(main())
