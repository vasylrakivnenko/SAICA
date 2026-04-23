"""Export cluster-study artifacts into a single site-consumable JSON.

Reads the research-grade artifacts that
``pipeline.cli.cluster_study`` produces under
``research/taxonomy_clustering/`` and merges them — together with a fresh
2-D UMAP projection of the saved embeddings — into a compact JSON that the
``/taxonomy-study`` Astro page fetches at runtime.

Output: ``site/public/taxonomy_study.json``

Shape (roughly)::

    {
      "summary": {corpus_size, k_text, k_bipartite, k_manual_saica,
                  ari_text_saica, nmi_text_saica,
                  ari_bipartite_saica, nmi_bipartite_saica,
                  bootstrap_ari_text, bootstrap_ari_bipartite,
                  chosen_text_mcs, chosen_bipartite_mcs},
      "taxonomies": {"<id>": {"name": "...", "color": "#xxx"}, ...},
      "saica_modes": [...],
      "points": [
        {id, source_tax_id, label, description, x, y,
         text_cluster, bipartite_cluster, saica_match},
        ...
      ],
      "clusters": {
        "bipartite": [{id, name, size, saica_top, saica_coverage, member_ids},...],
        "text":      [{id, name, size, saica_top, saica_coverage, member_ids},...]
      }
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from pipeline.config import REPO_ROOT

log = logging.getLogger("pipeline.taxonomy_cluster.export_site_data")

RESEARCH_DIR = REPO_ROOT / "research" / "taxonomy_clustering"
SITE_JSON_PATH = REPO_ROOT / "site" / "public" / "taxonomy_study.json"

# Human-friendly taxonomy names + palette. Palette extends the site's
# indigo/rose/violet/slate accents so /explore and /taxonomy-study feel
# like the same visual family.
TAXONOMY_META: Dict[str, Dict[str, str]] = {
    "daplab-9-patterns": {
        "name": "DAPLab 9 Patterns",
        "color": "#2563eb",  # blue
    },
    "mast": {
        "name": "MAST",
        "color": "#e11d48",  # rose
    },
    "microsoft-airt-2025": {
        "name": "Microsoft AIRT 2025",
        "color": "#7c3aed",  # violet
    },
    "owasp-agentic-top-10-2026": {
        "name": "OWASP Agentic Top 10",
        "color": "#f59e0b",  # amber
    },
    "shah-2026-agentic-faults": {
        "name": "Shah 2026 Agentic Faults",
        "color": "#0891b2",  # cyan
    },
    "swiss-cheese-model": {
        "name": "Swiss Cheese Model",
        "color": "#64748b",  # slate
    },
}


# ---------------------------------------------------------------------------
# 2-D UMAP projection
# ---------------------------------------------------------------------------


def _umap_2d(X: np.ndarray, *, seed: int = 42) -> np.ndarray:
    """2-D UMAP projection, with PCA fallback for tiny corpora/failures."""
    n = X.shape[0]
    if n < 3:
        coords = np.zeros((n, 2), dtype=np.float32)
        for i in range(n):
            coords[i] = (float(i), 0.0)
        return coords
    try:
        import umap  # type: ignore

        nn = max(2, min(15, n - 1))
        reducer = umap.UMAP(
            n_components=2,
            n_neighbors=nn,
            min_dist=0.1,
            metric="cosine",
            random_state=seed,
        )
        return np.asarray(reducer.fit_transform(X), dtype=np.float32)
    except Exception as exc:  # pragma: no cover - umap convergence edge
        log.warning("UMAP failed (%s); falling back to PCA.", exc)
        Xc = X - X.mean(axis=0, keepdims=True)
        _, _, Vt = np.linalg.svd(Xc, full_matrices=False)
        return (Xc @ Vt[:2].T).astype(np.float32)


def _minmax01(coords: np.ndarray) -> np.ndarray:
    """Scale (N, 2) coords into [0, 1] per axis. Mirrors /explore."""
    if coords.size == 0:
        return coords
    out = coords.astype(np.float32).copy()
    for axis in (0, 1):
        col = out[:, axis]
        lo, hi = float(col.min()), float(col.max())
        span = hi - lo
        if span < 1e-9:
            out[:, axis] = 0.5
        else:
            out[:, axis] = (col - lo) / span
    return out


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _key(source_tax_id: str, external_id: str) -> str:
    return f"{source_tax_id}::{external_id}"


def _saica_modes_from_dir() -> List[str]:
    """Return the 11 SAICA modes as sorted filenames (stable order)."""
    fm_dir = REPO_ROOT / "data" / "failure_modes"
    if not fm_dir.exists():
        return []
    return sorted(p.stem for p in fm_dir.glob("*.yml"))


def build_payload(
    *,
    research_dir: Path = RESEARCH_DIR,
) -> Dict:
    corpus = json.loads((research_dir / "corpus.json").read_text(encoding="utf-8"))
    meta = json.loads((research_dir / "metadata.json").read_text(encoding="utf-8"))
    hdb = json.loads((research_dir / "hdbscan_runs.json").read_text(encoding="utf-8"))
    bip = json.loads((research_dir / "bipartite_clusters.json").read_text(encoding="utf-8"))
    sai = json.loads((research_dir / "saica_comparison.json").read_text(encoding="utf-8"))

    X = np.load(research_dir / "embeddings.npy")
    if X.shape[0] != len(corpus):
        raise RuntimeError(
            f"corpus has {len(corpus)} rows but embeddings has {X.shape[0]}"
        )

    coords = _minmax01(_umap_2d(X))

    # --- cluster label arrays ----------------------------------------------
    text_labels: List[int] = list(hdb["canonical_labels"])
    text_mcs: int = int(hdb.get("canonical_min_cluster_size", -1))
    text_k: int = int(hdb.get("canonical_n_clusters", -1))
    text_boot: float = float(hdb.get("canonical_bootstrap_ari", 0.0))

    bip_labels: List[int] = list(bip["canonical_labels"])
    bip_mcs: int = int(bip.get("canonical_min_cluster_size", -1))
    bip_k: int = int(bip.get("canonical_n_clusters", -1))
    bip_boot: float = float(bip.get("canonical_bootstrap_ari", 0.0))

    saica_labels_per_row: List[str] = list(sai.get("saica_labels", []))
    if len(saica_labels_per_row) != len(corpus):
        raise RuntimeError(
            "saica_comparison.saica_labels length mismatch with corpus."
        )

    # The research artifacts already use the same key ordering as corpus,
    # but belt-and-suspenders verify.
    key_order = [_key(r["source_tax_id"], r["external_id"]) for r in corpus]
    if "keys" in meta and list(meta["keys"]) != key_order:
        raise RuntimeError("metadata.keys drifted from corpus key order.")

    # --- summary ------------------------------------------------------------
    text_agree = sai.get("text", {}).get("agreement_vs_saica", {})
    bip_agree = sai.get("bipartite", {}).get("agreement_vs_saica", {})

    saica_modes = _saica_modes_from_dir()
    k_manual = len(saica_modes) if saica_modes else 11

    summary = {
        "corpus_size": len(corpus),
        "k_text": text_k,
        "k_bipartite": bip_k,
        "k_manual_saica": k_manual,
        "ari_text_saica": float(text_agree.get("ari", 0.0)),
        "nmi_text_saica": float(text_agree.get("nmi", 0.0)),
        "ari_bipartite_saica": float(bip_agree.get("ari", 0.0)),
        "nmi_bipartite_saica": float(bip_agree.get("nmi", 0.0)),
        "bootstrap_ari_text": text_boot,
        "bootstrap_ari_bipartite": bip_boot,
        "chosen_text_mcs": text_mcs,
        "chosen_bipartite_mcs": bip_mcs,
    }

    # --- points -------------------------------------------------------------
    # Map from row key -> saica match, reusing the per-row labels already
    # computed by the study. Noise + unmapped rows keep their literal label.
    points: List[Dict] = []
    for i, row in enumerate(corpus):
        points.append(
            {
                "id": row["external_id"],
                "key": key_order[i],
                "source_tax_id": row["source_tax_id"],
                "label": row["label"],
                "description": row["description"],
                "x": round(float(coords[i, 0]), 4),
                "y": round(float(coords[i, 1]), 4),
                "text_cluster": int(text_labels[i]),
                "bipartite_cluster": int(bip_labels[i]),
                "saica_match": saica_labels_per_row[i],
            }
        )

    # --- cluster summaries --------------------------------------------------
    def _pack(summary_list: List[Dict]) -> List[Dict]:
        out: List[Dict] = []
        for s in summary_list:
            out.append(
                {
                    "id": int(s["cluster_id"]),
                    "name": s.get("proposed_name", ""),
                    "size": int(s.get("size", 0)),
                    "saica_top": s.get("top_saica_mode", ""),
                    "saica_coverage": float(s.get("coverage_pct", 0.0)) / 100.0,
                    "saica_mode_spread": int(s.get("saica_mode_spread", 0)),
                    "disagreement": bool(s.get("disagreement", False)),
                    "member_ids": list(s.get("members", [])),
                }
            )
        return out

    clusters = {
        "bipartite": _pack(sai.get("bipartite", {}).get("clusters", [])),
        "text": _pack(sai.get("text", {}).get("clusters", [])),
    }

    # --- taxonomies meta ----------------------------------------------------
    tax_ids = sorted({r["source_tax_id"] for r in corpus})
    taxonomies: Dict[str, Dict[str, str]] = {}
    fallback_palette = ["#2563eb", "#e11d48", "#7c3aed", "#f59e0b", "#0891b2", "#64748b", "#059669", "#db2777"]
    for i, tid in enumerate(tax_ids):
        meta_entry = TAXONOMY_META.get(tid)
        if meta_entry:
            taxonomies[tid] = dict(meta_entry)
        else:
            taxonomies[tid] = {
                "name": tid,
                "color": fallback_palette[i % len(fallback_palette)],
            }

    payload = {
        "summary": summary,
        "taxonomies": taxonomies,
        "saica_modes": saica_modes,
        "points": points,
        "clusters": clusters,
    }
    return payload


def write_payload(payload: Dict, out_path: Path = SITE_JSON_PATH) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--research-dir",
        type=Path,
        default=RESEARCH_DIR,
        help="Where the cluster-study artifacts live.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=SITE_JSON_PATH,
        help="Output JSON path consumed by /taxonomy-study.",
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
    payload = build_payload(research_dir=args.research_dir)
    out = write_payload(payload, out_path=args.out)
    size_kb = out.stat().st_size / 1024
    log.info(
        "Wrote %s (%.1f KB, %d points, K_text=%d, K_bip=%d)",
        out,
        size_kb,
        len(payload["points"]),
        payload["summary"]["k_text"],
        payload["summary"]["k_bipartite"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
