"""Editorial drift report: flag Tools whose text embedding disagrees with
their labeled ``(control_paradigm, temporal_phase, autonomy_level)`` cell.

This is a *signal*, not a decision. The output is a markdown report under
``research/embedding_drift_report_<date>.md`` listing the top-20 tools that
sit farthest from their own cell's centroid — plus, for each, the nearest
*alternative* cell whose centroid would be a better fit, and the three most
similar tools regardless of cell. Human review follows; this module never
mutates YAMLs.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from pipeline.config import REPO_ROOT
from pipeline.embeddings.compute import EmbeddingStore

log = logging.getLogger(__name__)

DEFAULT_TOP_N = 20
DEFAULT_REPORT_DIR = REPO_ROOT / "research"

Cell = Tuple[str, str, str]


@dataclass
class DriftRow:
    tool_id: str
    current_cell: Cell
    distance_from_own_centroid: float
    nearest_alt_cell: Optional[Cell]
    nearest_alt_distance: Optional[float]
    top3_similar: List[Tuple[str, float]]  # (tool_id, cosine_similarity)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _cell_centroids(tools: EmbeddingStore) -> Dict[Cell, np.ndarray]:
    """Mean of each cell's tool vectors. Missing-cell tools are ignored."""
    groups: Dict[Cell, List[int]] = {}
    for i, cell in enumerate(tools.cells):
        if cell is None:
            continue
        groups.setdefault(cell, []).append(i)
    return {cell: tools.vectors[idx].mean(axis=0) for cell, idx in groups.items()}


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine *distance* in [0, 2]. Vectors need not be normalized."""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-12 or nb < 1e-12:
        return 1.0
    return 1.0 - float(np.dot(a, b) / (na * nb))


def _top3_similar_tools(tools: EmbeddingStore, i: int) -> List[Tuple[str, float]]:
    """Top-3 other tools by cosine similarity (regardless of cell)."""
    V = tools.vectors
    v = V[i]
    sims = V @ v  # normalized vectors → dot = cosine
    sims[i] = -np.inf
    order = np.argsort(-sims)[:3]
    return [(tools.ids[j], float(sims[j])) for j in order]


def compute_drift(
    tools: EmbeddingStore, *, top_n: int = DEFAULT_TOP_N
) -> List[DriftRow]:
    """Rank tools by distance from their own cell centroid (descending)."""
    centroids = _cell_centroids(tools)
    rows: List[DriftRow] = []
    for i, cell in enumerate(tools.cells):
        if cell is None or cell not in centroids:
            continue

        own_centroid = centroids[cell]
        own_dist = _cosine_distance(tools.vectors[i], own_centroid)

        # Nearest *alternative* cell
        alt_cell: Optional[Cell] = None
        alt_dist: Optional[float] = None
        for other_cell, other_centroid in centroids.items():
            if other_cell == cell:
                continue
            d = _cosine_distance(tools.vectors[i], other_centroid)
            if alt_dist is None or d < alt_dist:
                alt_cell, alt_dist = other_cell, d

        rows.append(
            DriftRow(
                tool_id=tools.ids[i],
                current_cell=cell,
                distance_from_own_centroid=own_dist,
                nearest_alt_cell=alt_cell,
                nearest_alt_distance=alt_dist,
                top3_similar=_top3_similar_tools(tools, i),
            )
        )

    rows.sort(key=lambda r: r.distance_from_own_centroid, reverse=True)
    return rows[:top_n]


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _fmt_cell(cell: Cell) -> str:
    return f"`{cell[0]} × {cell[1]} × {cell[2]}`"


def render_markdown(
    rows: Sequence[DriftRow], *, generated_at: Optional[dt.date] = None
) -> str:
    generated_at = generated_at or dt.date.today()
    lines: List[str] = []
    lines.append(f"# Embedding drift report — {generated_at.isoformat()}")
    lines.append("")
    lines.append(
        "Each row below is a tool whose text embedding sits far from the "
        "centroid of its labeled `(control_paradigm, temporal_phase, "
        "autonomy_level)` cell. High distance is a **signal for human review**, "
        "not a verdict — embeddings are noisy and tool descriptions vary in "
        "verbosity."
    )
    lines.append("")
    lines.append(
        "| # | tool | current cell | distance | nearest alt cell | alt distance |"
    )
    lines.append(
        "|---|------|--------------|---------:|------------------|-------------:|"
    )
    for i, r in enumerate(rows, 1):
        alt = _fmt_cell(r.nearest_alt_cell) if r.nearest_alt_cell else "—"
        alt_d = (
            f"{r.nearest_alt_distance:.4f}"
            if r.nearest_alt_distance is not None
            else "—"
        )
        lines.append(
            f"| {i} | `{r.tool_id}` | {_fmt_cell(r.current_cell)} | "
            f"{r.distance_from_own_centroid:.4f} | {alt} | {alt_d} |"
        )
    lines.append("")
    lines.append("## Detail")
    for i, r in enumerate(rows, 1):
        lines.append("")
        lines.append(f"### {i}. `{r.tool_id}`")
        lines.append("")
        lines.append(f"- **current cell**: {_fmt_cell(r.current_cell)}")
        lines.append(
            f"- **distance from own centroid**: {r.distance_from_own_centroid:.4f}"
        )
        if r.nearest_alt_cell is not None:
            lines.append(
                f"- **nearest alternative cell**: {_fmt_cell(r.nearest_alt_cell)} "
                f"(distance {r.nearest_alt_distance:.4f})"
            )
        if r.top3_similar:
            sims = ", ".join(f"`{tid}` ({s:.3f})" for tid, s in r.top3_similar)
            lines.append(f"- **top-3 embedding-similar tools**: {sims}")
    lines.append("")
    return "\n".join(lines)


def write_report(
    rows: Sequence[DriftRow],
    *,
    out_dir: Path = DEFAULT_REPORT_DIR,
    generated_at: Optional[dt.date] = None,
) -> Path:
    generated_at = generated_at or dt.date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"embedding_drift_report_{generated_at.isoformat()}.md"
    path.write_text(render_markdown(rows, generated_at=generated_at), encoding="utf-8")
    return path
