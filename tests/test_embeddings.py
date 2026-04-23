"""Tests for the semantic-embedding layer.

All tests stub the sentence-transformers encoder with a deterministic mock
that returns random-but-reproducible unit vectors. The real MiniLM model is
too slow (and too network-dependent) for unit tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import numpy as np
import pytest
import yaml

from pipeline.embeddings import compute, drift_report, query, umap_project
from pipeline.embeddings.compute import (
    EMBED_DIM,
    EmbeddingStore,
    build_node_text,
    compute_embeddings,
    encode_texts,
    save_store,
    top_similar,
)
from pipeline.embeddings.drift_report import compute_drift, render_markdown
from pipeline.embeddings.query import _reset_cache, find_similar
from pipeline.embeddings.umap_project import project_all


# ---------------------------------------------------------------------------
# Stub encoder
# ---------------------------------------------------------------------------


class StubEncoder:
    """Deterministic bag-of-words encoder.

    Each distinct lowercase word hashes to one of ``dim`` random unit vectors;
    a text's embedding is the L2-normalized sum of its word vectors. This gives
    similar vocabularies similar embeddings — enough signal to exercise the
    drift-detection logic without loading a real LM. Non-overlapping vocabularies
    get ~orthogonal embeddings.
    """

    def __init__(self, dim: int = EMBED_DIM, seed: int = 0):
        self.dim = dim
        self._seed = seed
        self._word_cache: dict[str, np.ndarray] = {}

    def _word_vec(self, w: str) -> np.ndarray:
        if w not in self._word_cache:
            rng = np.random.default_rng(abs(hash(w)) % (2**32) + self._seed)
            v = rng.standard_normal(self.dim).astype(np.float32)
            v = v / (np.linalg.norm(v) + 1e-12)
            self._word_cache[w] = v
        return self._word_cache[w]

    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            words = [w for w in "".join(c if c.isalnum() else " " for c in str(t).lower()).split() if w]
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_encoder() -> StubEncoder:
    return StubEncoder()


@pytest.fixture
def tiny_data_dir(tmp_path: Path) -> Path:
    """A miniature KG under tmp_path/data/ with 6 tools and 1 failure_mode."""
    root = tmp_path / "data"
    (root / "tools").mkdir(parents=True)
    (root / "failure_modes").mkdir(parents=True)
    (root / "taxonomies").mkdir(parents=True)
    (root / "papers").mkdir(parents=True)

    # Four tools in cell A — three cohesive (linters), one outlier (chatbot-ish)
    tools = [
        {
            "id": "lint-a",
            "name": "LintA",
            "tagline": "Python linter.",
            "description": "Detects unused imports and undefined variables in Python source.",
            "inclusion_rationale": "Canonical static-analysis detector.",
            "addresses_failure_modes": ["fabrication"],
            "control_paradigm": "detection",
            "temporal_phase": "pre_generation",
            "autonomy_level": "fully_autonomous",
        },
        {
            "id": "lint-b",
            "name": "LintB",
            "tagline": "TypeScript linter.",
            "description": "Detects unused imports and undefined variables in TypeScript source.",
            "inclusion_rationale": "Canonical static-analysis detector.",
            "addresses_failure_modes": ["fabrication"],
            "control_paradigm": "detection",
            "temporal_phase": "pre_generation",
            "autonomy_level": "fully_autonomous",
        },
        {
            "id": "lint-c",
            "name": "LintC",
            "tagline": "Go linter.",
            "description": "Detects unused imports and undefined variables in Go source.",
            "inclusion_rationale": "Canonical static-analysis detector.",
            "addresses_failure_modes": ["fabrication"],
            "control_paradigm": "detection",
            "temporal_phase": "pre_generation",
            "autonomy_level": "fully_autonomous",
        },
        {
            # OUTLIER: labeled the same cell as the linters, but described
            # very differently — used by test_drift_report_flags_synthetic_outlier.
            "id": "outlier-x",
            "name": "OutlierX",
            "tagline": "Completely unrelated subject matter xyzzy plugh quux.",
            "description": "wibble wobble foo bar baz qux hocus pocus abracadabra.",
            "inclusion_rationale": "Totally different narrative vocabulary.",
            "addresses_failure_modes": ["scope_creep"],
            "control_paradigm": "detection",
            "temporal_phase": "pre_generation",
            "autonomy_level": "fully_autonomous",
        },
        # Two tools in a cohesive cell B
        {
            "id": "revert-a",
            "name": "RevertA",
            "tagline": "Git-based recovery.",
            "description": "Reverts agent changes via git revert.",
            "inclusion_rationale": "Recovery via VCS.",
            "addresses_failure_modes": ["logic_error"],
            "control_paradigm": "recovery",
            "temporal_phase": "post_generation",
            "autonomy_level": "graduated_hitl",
        },
        {
            "id": "revert-b",
            "name": "RevertB",
            "tagline": "Git-based recovery.",
            "description": "Reverts agent changes via git reset.",
            "inclusion_rationale": "Recovery via VCS.",
            "addresses_failure_modes": ["logic_error"],
            "control_paradigm": "recovery",
            "temporal_phase": "post_generation",
            "autonomy_level": "graduated_hitl",
        },
    ]
    for t in tools:
        (root / "tools" / f"{t['id']}.yml").write_text(yaml.safe_dump(t))

    fm = {
        "id": "fabrication",
        "name": "Fabrication",
        "description": "Generates references to nonexistent APIs.",
        "detection_signals": ["undefined import", "static-analysis error"],
    }
    (root / "failure_modes" / "fabrication.yml").write_text(yaml.safe_dump(fm))

    tax = {"id": "mast", "name": "MAST", "scope": "Multi-agent failure modes."}
    (root / "taxonomies" / "mast.yml").write_text(yaml.safe_dump(tax))

    paper = {
        "id": "demo-paper",
        "title": "Demo paper",
        "tldr": "Short summary of the demo.",
        "abstract": "A slightly longer abstract describing the demo.",
    }
    (root / "papers" / "demo-paper.yml").write_text(yaml.safe_dump(paper))

    return root


@pytest.fixture
def store(tiny_data_dir: Path, stub_encoder: StubEncoder) -> EmbeddingStore:
    return compute_embeddings(data_dir=tiny_data_dir, encoder=stub_encoder)


# ---------------------------------------------------------------------------
# 1. build_node_text correctly concatenates Tool fields
# ---------------------------------------------------------------------------


def test_embed_tool_concatenates_fields():
    doc = {
        "name": "MyTool",
        "tagline": "A tagline.",
        "description": "A description.",
        "inclusion_rationale": "Why it's here.",
        "addresses_failure_modes": ["fabrication", "logic_error"],
        "control_paradigm": "detection",  # should NOT appear in text
    }
    text = build_node_text("tool", doc)
    # Every embeddable field is present
    assert "MyTool" in text
    assert "A tagline." in text
    assert "A description." in text
    assert "Why it's here." in text
    assert "fabrication" in text
    assert "logic_error" in text
    # Facet enums are NOT in the text — they come from the label, not the prose
    assert "detection" not in text
    # Concat happened (single blob, not a list)
    assert isinstance(text, str)
    assert text.index("MyTool") < text.index("A tagline.")
    assert text.index("A tagline.") < text.index("A description.")


# ---------------------------------------------------------------------------
# 2. Drift report flags a synthetic outlier
# ---------------------------------------------------------------------------


def test_drift_report_flags_synthetic_outlier(store: EmbeddingStore):
    tools = store.by_type("tool")
    rows = compute_drift(tools, top_n=10)
    # The outlier tool should appear in the report
    tool_ids = [r.tool_id for r in rows]
    assert "outlier-x" in tool_ids

    outlier_row = next(r for r in rows if r.tool_id == "outlier-x")
    # And in the cohesive cell, the outlier's distance from its own centroid
    # should be higher than the three coherent linters' distances. We verify
    # by ranking: the outlier should be ranked strictly above all its
    # cell-mates in the drift report.
    cohesive_ids = {"lint-a", "lint-b", "lint-c"}
    outlier_rank = tool_ids.index("outlier-x")
    for cid in cohesive_ids:
        if cid in tool_ids:
            assert outlier_rank < tool_ids.index(cid), (
                f"{cid} ranked more outlying than the synthetic outlier"
            )

    # Report content has the required structure
    assert outlier_row.current_cell == (
        "detection",
        "pre_generation",
        "fully_autonomous",
    )
    assert len(outlier_row.top3_similar) == 3
    assert all(isinstance(s[1], float) for s in outlier_row.top3_similar)

    # Markdown rendering doesn't blow up
    md = render_markdown(rows)
    assert "outlier-x" in md
    assert "current cell" in md


# ---------------------------------------------------------------------------
# 3. UMAP produces (N, 2) output per type + combined
# ---------------------------------------------------------------------------


def test_umap_produces_correct_shape(store: EmbeddingStore):
    payload = project_all(store, k_similar=3)
    assert payload["dim"] == EMBED_DIM
    assert payload["count"] == len(store.ids)
    # Per-type projections exist for every type that has nodes
    for t in set(store.types):
        assert t in payload["by_type"]
        rows = payload["by_type"][t]
        for row in rows:
            assert set(["id", "name", "type", "x", "y", "top_similar_ids"]) <= set(row.keys())
            assert isinstance(row["x"], float)
            assert isinstance(row["y"], float)
            # Scaled to [0, 1]
            assert 0.0 - 1e-6 <= row["x"] <= 1.0 + 1e-6
            assert 0.0 - 1e-6 <= row["y"] <= 1.0 + 1e-6
    # Combined projection covers everyone
    assert len(payload["combined"]) == len(store.ids)
    for row in payload["combined"]:
        assert 0.0 - 1e-6 <= row["x"] <= 1.0 + 1e-6
        assert 0.0 - 1e-6 <= row["y"] <= 1.0 + 1e-6


# ---------------------------------------------------------------------------
# 4. find_similar returns top-k, sorted descending by similarity
# ---------------------------------------------------------------------------


def test_find_similar_returns_topk_sorted_desc(store: EmbeddingStore, stub_encoder: StubEncoder):
    _reset_cache()
    out = find_similar("LintA Python linter", k=4, store=store, encoder=stub_encoder)
    assert len(out) == 4
    # Descending by score
    scores = [s for _, s in out]
    assert scores == sorted(scores, reverse=True)
    # All scores within cosine's [-1, 1]
    assert all(-1.0 - 1e-6 <= s <= 1.0 + 1e-6 for s in scores)
    # k=0 / empty query behave sensibly
    assert find_similar("", k=5, store=store, encoder=stub_encoder) == []

    # node_type filter restricts results
    only_tools = find_similar(
        "anything", k=50, store=store, encoder=stub_encoder, node_type="tool"
    )
    tool_ids = {nid for nid, _ in only_tools}
    assert tool_ids.issubset(set(store.by_type("tool").ids))


# ---------------------------------------------------------------------------
# 5. embeddings.json matches the schema the Astro page reads
# ---------------------------------------------------------------------------


def test_embeddings_json_schema_matches_astro_expectations(
    store: EmbeddingStore, tmp_path: Path
):
    payload = project_all(store, k_similar=3)
    out_path = tmp_path / "embeddings.json"
    out_path.write_text(json.dumps(payload))

    loaded = json.loads(out_path.read_text())
    assert set(["model", "dim", "count", "by_type", "combined"]) <= set(loaded.keys())
    assert isinstance(loaded["by_type"], dict)
    assert isinstance(loaded["combined"], list)

    # Every combined row carries fields the /explore page reads
    required = {"id", "name", "type", "x", "y", "top_similar_ids"}
    for row in loaded["combined"]:
        assert required <= set(row.keys())
        assert row["type"] in {"tool", "failure_mode", "taxonomy", "paper"}
        # Tool rows carry a facet; others carry facet=null
        if row["type"] == "tool":
            assert row["facet"] is not None
            assert set(row["facet"].keys()) == {
                "control_paradigm",
                "temporal_phase",
                "autonomy_level",
            }

    # top_similar_ids is a list of strings (just IDs, not tuples)
    for row in loaded["combined"]:
        assert isinstance(row["top_similar_ids"], list)
        assert all(isinstance(s, str) for s in row["top_similar_ids"])


# ---------------------------------------------------------------------------
# Bonus: save_store round-trips
# ---------------------------------------------------------------------------


def test_save_store_round_trips(store: EmbeddingStore, tmp_path: Path):
    out_dir = tmp_path / "cache"
    save_store(store, out_dir)
    loaded = compute.load_store(out_dir)
    assert loaded.ids == store.ids
    assert loaded.types == store.types
    np.testing.assert_array_equal(loaded.vectors, store.vectors)
