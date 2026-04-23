"""Compute sentence-transformer embeddings for SAICA-KG nodes.

This module is offline-only: it reads the YAMLs under ``data/`` and writes
numpy arrays + id lists to ``.cache/embeddings/`` for downstream consumption
by :mod:`pipeline.embeddings.umap_project`, :mod:`pipeline.embeddings.query`,
and :mod:`pipeline.embeddings.drift_report`.

The encoder is ``all-MiniLM-L6-v2`` (384-dim, ~90 MB), chosen for speed and
a good-enough signal on the kinds of short semi-structured descriptions in
the KG. The model is lazy-loaded via :func:`_load_encoder` so tests that stub
encoding never trigger a network fetch.

Node-type text assembly rules (order matters for reproducibility):

* ``tool``         → ``name + tagline + description + inclusion_rationale +
                     " ".join(addresses_failure_modes)``
* ``failure_mode`` → ``name + description + " ".join(detection_signals)``
* ``taxonomy``     → ``name + scope``
* ``paper``        → ``title + tldr + abstract``

Missing fields are tolerated — we just drop them from the concat.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np
import yaml

from pipeline.config import REPO_ROOT

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = REPO_ROOT / ".cache" / "embeddings"
MODEL_CACHE_DIR = REPO_ROOT / ".cache" / "st-models"

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384

NODE_TYPES = ("tool", "failure_mode", "taxonomy", "paper")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class KGNode:
    """A flat representation of a KG node for embedding + drift analysis."""

    id: str
    type: str  # tool | failure_mode | taxonomy | paper
    name: str
    text: str  # the concatenated text that will be embedded
    # Tool-only facet (None for non-tools); used by drift_report
    cell: Optional[tuple[str, str, str]] = None
    # Full raw record — handy for downstream consumers
    raw: Dict = field(default_factory=dict)


@dataclass
class EmbeddingStore:
    """All embeddings for the KG, keyed by node id."""

    ids: List[str]
    types: List[str]
    vectors: np.ndarray  # (N, EMBED_DIM)
    # Optional parallel metadata
    names: List[str] = field(default_factory=list)
    cells: List[Optional[tuple[str, str, str]]] = field(default_factory=list)

    def index_of(self, node_id: str) -> int:
        return self.ids.index(node_id)

    def by_type(self, node_type: str) -> "EmbeddingStore":
        idx = [i for i, t in enumerate(self.types) if t == node_type]
        return EmbeddingStore(
            ids=[self.ids[i] for i in idx],
            types=[self.types[i] for i in idx],
            vectors=self.vectors[idx],
            names=[self.names[i] for i in idx] if self.names else [],
            cells=[self.cells[i] for i in idx] if self.cells else [],
        )


# ---------------------------------------------------------------------------
# Text assembly
# ---------------------------------------------------------------------------


def _join_nonempty(parts: Sequence[Optional[str]], sep: str = " ") -> str:
    return sep.join(p.strip() for p in parts if p and str(p).strip())


def _tool_text(doc: Dict) -> str:
    return _join_nonempty(
        [
            doc.get("name"),
            doc.get("tagline"),
            doc.get("description"),
            doc.get("inclusion_rationale"),
            " ".join(doc.get("addresses_failure_modes") or []),
        ]
    )


def _failure_mode_text(doc: Dict) -> str:
    return _join_nonempty(
        [
            doc.get("name"),
            doc.get("description"),
            " ".join(doc.get("detection_signals") or []),
        ]
    )


def _taxonomy_text(doc: Dict) -> str:
    return _join_nonempty([doc.get("name"), doc.get("scope")])


def _paper_text(doc: Dict) -> str:
    return _join_nonempty(
        [doc.get("title"), doc.get("tldr"), doc.get("abstract")]
    )


TEXT_BUILDERS: Dict[str, Callable[[Dict], str]] = {
    "tool": _tool_text,
    "failure_mode": _failure_mode_text,
    "taxonomy": _taxonomy_text,
    "paper": _paper_text,
}


def build_node_text(node_type: str, doc: Dict) -> str:
    """Assemble the text blob that will be fed to the encoder.

    Public (not underscored) because tests exercise it directly.
    """
    builder = TEXT_BUILDERS.get(node_type)
    if builder is None:
        raise ValueError(f"Unknown node type: {node_type!r}")
    return builder(doc)


# ---------------------------------------------------------------------------
# Loading KG nodes
# ---------------------------------------------------------------------------


_TYPE_TO_SUBDIR = {
    "tool": "tools",
    "failure_mode": "failure_modes",
    "taxonomy": "taxonomies",
    "paper": "papers",
}


def iter_kg_nodes(data_dir: Path = DATA_DIR) -> Iterable[KGNode]:
    """Walk ``data/`` and yield every embeddable node."""
    for node_type, subdir in _TYPE_TO_SUBDIR.items():
        d = data_dir / subdir
        if not d.is_dir():
            continue
        for yml_path in sorted(d.glob("*.yml")):
            with yml_path.open("r", encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}
            node_id = doc.get("id")
            if not node_id:
                log.warning("Skipping %s: no id field", yml_path)
                continue
            text = build_node_text(node_type, doc)
            if not text:
                log.warning("Skipping %s: empty text after assembly", node_id)
                continue
            cell: Optional[tuple[str, str, str]] = None
            if node_type == "tool":
                cp = doc.get("control_paradigm")
                tp = doc.get("temporal_phase")
                al = doc.get("autonomy_level")
                if cp and tp and al:
                    cell = (cp, tp, al)
            yield KGNode(
                id=node_id,
                type=node_type,
                name=doc.get("name") or node_id,
                text=text,
                cell=cell,
                raw=doc,
            )


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


# A drop-in protocol — tests inject a stub with an .encode() method.
EncoderLike = Callable[[List[str]], np.ndarray]


_ENCODER = None  # module-level cache


def _load_encoder(model_name: str = DEFAULT_MODEL_NAME):  # pragma: no cover - heavy
    """Lazy-load the sentence-transformers model, caching weights on disk."""
    global _ENCODER
    if _ENCODER is not None:
        return _ENCODER
    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Force HF + sentence-transformers to use our repo-local cache
    os.environ.setdefault("HF_HOME", str(MODEL_CACHE_DIR))
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(MODEL_CACHE_DIR))
    from sentence_transformers import SentenceTransformer

    log.info("Loading encoder %s (cache=%s)", model_name, MODEL_CACHE_DIR)
    _ENCODER = SentenceTransformer(model_name, cache_folder=str(MODEL_CACHE_DIR))
    return _ENCODER


def encode_texts(
    texts: List[str],
    *,
    encoder: Optional[object] = None,
    model_name: str = DEFAULT_MODEL_NAME,
) -> np.ndarray:
    """Encode a batch of texts. Tests can pass a stub via ``encoder=``."""
    if encoder is None:  # pragma: no cover - heavy path hits network on first run
        encoder = _load_encoder(model_name)
    vecs = encoder.encode(
        texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
    )
    vecs = np.asarray(vecs, dtype=np.float32)
    return vecs


# ---------------------------------------------------------------------------
# End-to-end compute
# ---------------------------------------------------------------------------


def compute_embeddings(
    *,
    data_dir: Path = DATA_DIR,
    encoder: Optional[object] = None,
    model_name: str = DEFAULT_MODEL_NAME,
) -> EmbeddingStore:
    nodes = list(iter_kg_nodes(data_dir))
    if not nodes:
        raise RuntimeError(f"No nodes found under {data_dir}")
    texts = [n.text for n in nodes]
    vecs = encode_texts(texts, encoder=encoder, model_name=model_name)
    return EmbeddingStore(
        ids=[n.id for n in nodes],
        types=[n.type for n in nodes],
        vectors=vecs,
        names=[n.name for n in nodes],
        cells=[n.cell for n in nodes],
    )


def save_store(store: EmbeddingStore, cache_dir: Path = CACHE_DIR) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(cache_dir / "vectors.npy", store.vectors)
    meta = {
        "ids": store.ids,
        "types": store.types,
        "names": store.names,
        "cells": [list(c) if c else None for c in store.cells],
        "dim": int(store.vectors.shape[1]),
    }
    with (cache_dir / "meta.json").open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, sort_keys=False)
    return cache_dir


def load_store(cache_dir: Path = CACHE_DIR) -> EmbeddingStore:
    vectors = np.load(cache_dir / "vectors.npy")
    with (cache_dir / "meta.json").open("r", encoding="utf-8") as fh:
        meta = json.load(fh)
    cells = [tuple(c) if c else None for c in meta.get("cells", [])]
    return EmbeddingStore(
        ids=list(meta["ids"]),
        types=list(meta["types"]),
        vectors=vectors,
        names=list(meta.get("names") or []),
        cells=cells,
    )


def top_similar(
    store: EmbeddingStore, k: int = 10
) -> Dict[str, List[tuple[str, float]]]:
    """For each node, return the top-k most-similar *other* nodes by cosine sim.

    Vectors are assumed L2-normalized (the encoder does this for us), so we can
    treat the dot product as cosine similarity.
    """
    V = store.vectors
    sims = V @ V.T  # (N, N)
    np.fill_diagonal(sims, -np.inf)
    # argsort descending by row
    order = np.argsort(-sims, axis=1)[:, :k]
    out: Dict[str, List[tuple[str, float]]] = {}
    for i, nid in enumerate(store.ids):
        out[nid] = [
            (store.ids[j], float(sims[i, j]))
            for j in order[i]
            if sims[i, j] != -np.inf
        ]
    return out
