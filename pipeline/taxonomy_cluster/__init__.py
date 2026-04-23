"""Data-driven clustering study over the six ingested failure taxonomies.

This package exists to validate — or challenge — SAICA-KG's manual 11-mode
FailureMode axis by letting text embeddings and a tool-bipartite signal
propose their own grouping of the ~128 categories ingested from OWASP,
MAST, DAPLab, Microsoft AIRT, Swiss Cheese, and Shah et al.

Pipeline:

    collect  -> corpus.json + per-category metadata
    cluster  -> hdbscan_runs.json + bipartite_clusters.json
    compare  -> saica_comparison.{json,md} (ARI/NMI vs SAICA's 11)
    figures  -> UMAP scatter + cluster-count plot + agreement heatmap
    cli/cluster_study.py -> end-to-end orchestrator

No code here mutates any YAML under ``data/``. This is a paper-ready
methodology artifact.
"""

__all__ = ["collect", "cluster", "compare", "figures"]
