"""Nearest-neighbor lookup over precomputed KG embeddings.

This is the retrieval layer consumed by the ``/ask`` page (another agent).
Call :func:`find_similar` with any free-text query to get the top-k closest
KG nodes by cosine similarity.

Embeddings are loaded once (module-cached) from ``.cache/embeddings/`` and
the sentence-transformer model is lazy-loaded on first call.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

from pipeline.embeddings.compute import (
    EmbeddingStore,
    encode_texts,
    load_store,
)

log = logging.getLogger(__name__)

_STORE: Optional[EmbeddingStore] = None


def _get_store() -> EmbeddingStore:
    global _STORE
    if _STORE is None:
        _STORE = load_store()
    return _STORE


def _reset_cache() -> None:
    """Test helper — drop the module-level cache."""
    global _STORE
    _STORE = None


def find_similar(
    query_text: str,
    k: int = 10,
    *,
    store: Optional[EmbeddingStore] = None,
    encoder: Optional[object] = None,
    node_type: Optional[str] = None,
) -> List[Tuple[str, float]]:
    """Return ``[(node_id, similarity)]`` for the top-k closest KG nodes.

    Parameters
    ----------
    query_text
        The free-text query to embed.
    k
        Number of results.
    store
        Optional pre-loaded :class:`EmbeddingStore`; if None, loads from disk.
    encoder
        Optional test double with ``.encode(list[str]) -> ndarray``.
    node_type
        If given, restrict results to nodes of this type.
    """
    if not query_text or not query_text.strip():
        return []

    s = store if store is not None else _get_store()
    if node_type is not None:
        s = s.by_type(node_type)
    if len(s.ids) == 0:
        return []

    qvec = encode_texts([query_text], encoder=encoder)[0]
    # Ensure both sides are L2-normalized → dot == cosine
    qn = float(np.linalg.norm(qvec))
    if qn > 1e-12:
        qvec = qvec / qn
    sims = s.vectors @ qvec
    k_eff = min(k, len(s.ids))
    order = np.argpartition(-sims, k_eff - 1)[:k_eff]
    order = order[np.argsort(-sims[order])]
    return [(s.ids[int(i)], float(sims[int(i)])) for i in order]
