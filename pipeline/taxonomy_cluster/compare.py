"""Compare algorithmic clusters to SAICA's manual 11-FailureMode taxonomy.

For each algorithmic cluster c we:

1. Look up every member category's crosswalked SAICA FailureMode(s)
2. Take a majority vote to pick the cluster's best SAICA match
3. Compute coverage: what share of c landed in its top SAICA mode
4. Report the spread: how many distinct SAICA modes c spans

For the partition-level agreement (ARI / NMI):

* SAICA ground truth = for each category, the majority SAICA mode across
  its crosswalks. Categories with no crosswalk get a sentinel label
  ``__unmapped__`` so they don't silently distort the statistic.
* We compute ARI and NMI against that labeling for both clusterings.

We also compute a "naming" draft for each algorithmic cluster following
the spec: the member category whose parent taxonomy has the highest
citation_count wins the name slot; ties broken by longest description.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from pipeline.taxonomy_cluster.collect import (
    CategoryRow,
    crosswalk_map,
    load_crosswalk_pairs,
)


UNMAPPED = "__unmapped__"


@dataclass
class ClusterSummary:
    """Per-cluster row of the comparison table."""

    cluster_id: int                     # -1 for HDBSCAN noise
    size: int
    proposed_name: str                  # from the most-cited parent taxonomy's member
    proposed_from_external_id: str      # the member category used for naming
    proposed_from_source_tax_id: str
    top_saica_mode: str                 # winner of majority vote, or UNMAPPED
    coverage_pct: float                 # share of cluster that lands in top_saica_mode
    saica_mode_spread: int              # distinct SAICA modes spanned
    disagreement: bool                  # cluster combines >1 SAICA modes or is unmapped
    members: List[str]                  # row keys ("{tax}::{ext}") in the cluster

    def to_jsonable(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Ground-truth SAICA label for each category
# ---------------------------------------------------------------------------


def saica_labels_for_rows(rows: Sequence[CategoryRow]) -> List[str]:
    """For each row, return its majority-vote SAICA FailureMode.

    Ties are broken alphabetically (stable). Categories with no crosswalk
    get the sentinel ``__unmapped__`` so they contribute to the partition
    without being silently merged into whatever label has count 0 first.
    """
    pairs = load_crosswalk_pairs()
    cmap = crosswalk_map(pairs)  # key -> list of saica values
    out: List[str] = []
    for r in rows:
        modes = cmap.get(r.key, [])
        if not modes:
            out.append(UNMAPPED)
            continue
        ctr = Counter(modes)
        top = sorted(ctr.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        out.append(top)
    return out


# ---------------------------------------------------------------------------
# Cluster naming
# ---------------------------------------------------------------------------


def _pick_naming_member(
    members: Sequence[CategoryRow],
) -> Optional[CategoryRow]:
    """Pick the canonical member for naming per the spec: highest parent-paper
    citation_count, tie-break by longest description."""
    if not members:
        return None
    return sorted(
        members,
        key=lambda m: (
            -int(m.citation_count_of_parent_taxonomy),
            -len(m.description or ""),
            m.source_tax_id,
            m.external_id,
        ),
    )[0]


# ---------------------------------------------------------------------------
# Per-cluster summary
# ---------------------------------------------------------------------------


def summarize_clusters(
    rows: Sequence[CategoryRow],
    labels: Sequence[int],
    *,
    saica_labels: Optional[Sequence[str]] = None,
) -> List[ClusterSummary]:
    """Build one :class:`ClusterSummary` per distinct cluster id.

    Pass ``saica_labels`` to reuse an existing ground-truth labeling (keeps
    the downstream ARI computation consistent with per-cluster coverage).
    """
    if saica_labels is None:
        saica_labels = saica_labels_for_rows(rows)
    assert len(rows) == len(labels) == len(saica_labels)

    grouped: Dict[int, List[int]] = {}
    for i, lbl in enumerate(labels):
        grouped.setdefault(int(lbl), []).append(i)

    out: List[ClusterSummary] = []
    for cid, idxs in sorted(grouped.items()):
        members = [rows[i] for i in idxs]
        # Top SAICA mode by majority (ignore UNMAPPED unless that's all we have).
        vote = Counter(saica_labels[i] for i in idxs)
        mapped = Counter({k: v for k, v in vote.items() if k != UNMAPPED})
        if mapped:
            top_mode, top_count = sorted(
                mapped.items(), key=lambda kv: (-kv[1], kv[0])
            )[0]
        else:
            top_mode = UNMAPPED
            top_count = vote.get(UNMAPPED, 0)
        coverage = top_count / len(idxs) if idxs else 0.0
        spread = len([k for k in vote if k != UNMAPPED])

        naming = _pick_naming_member(members)
        if naming is not None:
            proposed_name = naming.label
            proposed_ext = naming.external_id
            proposed_tax = naming.source_tax_id
        else:
            proposed_name = f"cluster-{cid}"
            proposed_ext = ""
            proposed_tax = ""

        disagreement = (spread > 1) or (top_mode == UNMAPPED)
        out.append(
            ClusterSummary(
                cluster_id=cid,
                size=len(idxs),
                proposed_name=proposed_name,
                proposed_from_external_id=proposed_ext,
                proposed_from_source_tax_id=proposed_tax,
                top_saica_mode=top_mode,
                coverage_pct=round(100.0 * coverage, 1),
                saica_mode_spread=spread,
                disagreement=disagreement,
                members=[rows[i].key for i in idxs],
            )
        )
    return out


# ---------------------------------------------------------------------------
# Partition-level agreement
# ---------------------------------------------------------------------------


def agreement_scores(
    cluster_labels: Sequence[int],
    saica_labels: Sequence[str],
) -> Dict[str, float]:
    """Return Adjusted Rand Index + Normalized Mutual Information.

    Both metrics handle unequal label spaces gracefully; they treat HDBSCAN's
    -1 noise label as just another class, which is the honest thing to do
    (noise points *are* an algorithmic choice and SAICA labels them something).
    """
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

    a = [int(x) for x in cluster_labels]
    b = list(saica_labels)
    return {
        "ari": round(float(adjusted_rand_score(a, b)), 4),
        "nmi": round(float(normalized_mutual_info_score(a, b)), 4),
    }


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def write_comparison_json(
    *,
    text_summaries: Sequence[ClusterSummary],
    bipartite_summaries: Sequence[ClusterSummary],
    text_agreement: Dict[str, float],
    bipartite_agreement: Dict[str, float],
    saica_labels: Sequence[str],
    out_path: Path,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "text": {
            "agreement_vs_saica": text_agreement,
            "clusters": [s.to_jsonable() for s in text_summaries],
        },
        "bipartite": {
            "agreement_vs_saica": bipartite_agreement,
            "clusters": [s.to_jsonable() for s in bipartite_summaries],
        },
        "saica_labels": list(saica_labels),
    }
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
    return out_path


def render_comparison_markdown(
    *,
    text_summaries: Sequence[ClusterSummary],
    bipartite_summaries: Sequence[ClusterSummary],
    text_agreement: Dict[str, float],
    bipartite_agreement: Dict[str, float],
    n_manual: int,
    n_text: int,
    n_bipartite: int,
) -> str:
    lines: List[str] = []
    lines.append("# SAICA-vs-Algorithmic Cluster Comparison")
    lines.append("")
    lines.append(
        f"- Manual SAICA FailureModes: **{n_manual}**"
    )
    lines.append(
        f"- Text-embedding clusters: **{n_text}** "
        f"(ARI vs SAICA: {text_agreement['ari']}, NMI: {text_agreement['nmi']})"
    )
    lines.append(
        f"- Tool-bipartite clusters: **{n_bipartite}** "
        f"(ARI vs SAICA: {bipartite_agreement['ari']}, NMI: {bipartite_agreement['nmi']})"
    )
    lines.append("")
    lines.append("## Text-embedding clusters")
    lines.append("")
    lines.append(
        "| cid | size | proposed name | top SAICA mode | coverage % | spread | disagreement |"
    )
    lines.append("|----:|----:|:--|:--|----:|----:|:--:|")
    for s in text_summaries:
        lines.append(
            f"| {s.cluster_id} | {s.size} | {s.proposed_name} | "
            f"{s.top_saica_mode} | {s.coverage_pct} | {s.saica_mode_spread} | "
            f"{'yes' if s.disagreement else 'no'} |"
        )
    lines.append("")
    lines.append("## Tool-bipartite clusters")
    lines.append("")
    lines.append(
        "| cid | size | proposed name | top SAICA mode | coverage % | spread | disagreement |"
    )
    lines.append("|----:|----:|:--|:--|----:|----:|:--:|")
    for s in bipartite_summaries:
        lines.append(
            f"| {s.cluster_id} | {s.size} | {s.proposed_name} | "
            f"{s.top_saica_mode} | {s.coverage_pct} | {s.saica_mode_spread} | "
            f"{'yes' if s.disagreement else 'no'} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_comparison_markdown(md: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(md)
    return out_path


# ---------------------------------------------------------------------------
# Top-N disagreements for the narrative report
# ---------------------------------------------------------------------------


def top_disagreements(
    summaries: Sequence[ClusterSummary], *, n: int = 3
) -> List[ClusterSummary]:
    """Pick the N most informative cluster/SAICA disagreements.

    We rank by (cluster size desc, spread desc, coverage asc) so the biggest
    "this cluster spans multiple SAICA modes" disagreements rise to the top.
    Noise clusters (cid = -1) and single-member clusters are skipped.
    """
    candidates = [
        s
        for s in summaries
        if s.disagreement and s.cluster_id >= 0 and s.size >= 2
    ]
    candidates.sort(
        key=lambda s: (-s.size, -s.saica_mode_spread, s.coverage_pct, s.cluster_id)
    )
    return candidates[:n]
