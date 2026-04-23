"""Reduce KG embeddings to 2D via UMAP for browser-side visualization.

Exports a single JSON file at ``site/public/embeddings.json`` that the
``/explore`` Astro page fetches at runtime.

The JSON shape is an object with keys:

* ``by_type``  — {node_type: [{id, name, x, y, top_similar_ids, facet?}]}
  (one 2D projection computed per node type — labels stay tight)
* ``combined`` — [{id, name, type, x, y, top_similar_ids, facet?}]
  (one 2D projection across all nodes — positions are comparable across types)

Positions in each projection are independently min-max scaled into [0, 1]
so the front-end doesn't have to know the raw UMAP range.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from pipeline.config import REPO_ROOT
from pipeline.embeddings.compute import EmbeddingStore, top_similar

log = logging.getLogger(__name__)

EMBEDDINGS_JSON_PATH = REPO_ROOT / "site" / "public" / "embeddings.json"


def _run_umap(
    vectors: np.ndarray,
    *,
    n_neighbors: int = 10,
    min_dist: float = 0.1,
    seed: int = 42,
) -> np.ndarray:
    """Run UMAP → 2D. Uses PCA fallback for very small N (< 5 points).

    UMAP's default n_neighbors (15) exceeds the number of samples in some of
    our per-type subsets (e.g. taxonomies: 6 nodes), so we clamp.
    """
    n = vectors.shape[0]
    if n < 3:
        # Degenerate: fall back to a trivial layout
        coords = np.zeros((n, 2), dtype=np.float32)
        for i in range(n):
            coords[i] = (float(i), 0.0)
        return coords
    if n < 5:
        # Too few for UMAP / PCA — use first two dims as-is
        return vectors[:, :2].astype(np.float32)

    # Lazy import so tests that stub it don't force umap-learn at import time
    import umap  # type: ignore

    nb = min(n_neighbors, max(2, n - 1))
    reducer = umap.UMAP(
        n_neighbors=nb,
        min_dist=min_dist,
        n_components=2,
        metric="cosine",
        random_state=seed,
    )
    return np.asarray(reducer.fit_transform(vectors), dtype=np.float32)


def _minmax01(coords: np.ndarray) -> np.ndarray:
    """Scale (N,2) coords into [0,1] independently per axis."""
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


def _facet_of(store: EmbeddingStore, idx: int) -> Optional[Dict[str, str]]:
    cell = store.cells[idx] if store.cells else None
    if not cell:
        return None
    cp, tp, al = cell
    return {"control_paradigm": cp, "temporal_phase": tp, "autonomy_level": al}


def project_all(
    store: EmbeddingStore,
    *,
    k_similar: int = 10,
) -> Dict:
    """Build the full payload for ``embeddings.json``."""
    neighbors = top_similar(store, k=k_similar)

    # Per-type projections
    by_type: Dict[str, List[Dict]] = {}
    for node_type in sorted(set(store.types)):
        subset = store.by_type(node_type)
        coords = _minmax01(_run_umap(subset.vectors))
        rows: List[Dict] = []
        for i, nid in enumerate(subset.ids):
            rows.append(
                {
                    "id": nid,
                    "name": subset.names[i] if subset.names else nid,
                    "type": node_type,
                    "x": float(coords[i, 0]),
                    "y": float(coords[i, 1]),
                    "top_similar_ids": [
                        sid for sid, _ in neighbors.get(nid, [])
                    ],
                    "facet": (
                        {
                            "control_paradigm": subset.cells[i][0],
                            "temporal_phase": subset.cells[i][1],
                            "autonomy_level": subset.cells[i][2],
                        }
                        if subset.cells and subset.cells[i]
                        else None
                    ),
                }
            )
        by_type[node_type] = rows

    # Combined projection
    combined_coords = _minmax01(_run_umap(store.vectors))
    combined: List[Dict] = []
    for i, nid in enumerate(store.ids):
        combined.append(
            {
                "id": nid,
                "name": store.names[i] if store.names else nid,
                "type": store.types[i],
                "x": float(combined_coords[i, 0]),
                "y": float(combined_coords[i, 1]),
                "top_similar_ids": [sid for sid, _ in neighbors.get(nid, [])],
                "facet": _facet_of(store, i),
            }
        )

    return {
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "dim": int(store.vectors.shape[1]),
        "count": len(store.ids),
        "by_type": by_type,
        "combined": combined,
    }


def write_embeddings_json(
    payload: Dict, out_path: Path = EMBEDDINGS_JSON_PATH
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    return out_path
