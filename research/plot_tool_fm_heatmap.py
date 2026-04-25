#!/usr/bin/env python3
"""Tool x Failure-Mode evidence heatmap.

Two selections are rendered:

* ``breadth`` — top 11 tools by count of FMs declared (default). Naturally
  dominated by eval harnesses; good for "what's the busy part of the map",
  but leaves rare-FM columns (obsolescence, dependency_blindness, ...) empty.

* ``covering`` — greedy set-cover so every FM column is filled by at least
  one tool, padded with high-evidence rows up to 11. Better for "at a glance,
  can the KG address every failure mode at all?"

Cells are tiered 0..3 on evidence for *this specific mapping*, never tool
popularity.

Outputs:
  research/figures/tool_fm_heatmap.{png,pdf}            # breadth view
  research/figures/tool_fm_heatmap_covering.{png,pdf}   # covering view
  research/figures/tool_fm_heatmap.json
  site/public/tool_fm_heatmap.json
"""
from __future__ import annotations

import glob
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import yaml
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

REPO = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO / "data" / "tools"
FM_DIR = REPO / "data" / "failure_modes"
OUT_DIR = REPO / "research" / "figures"
SITE_PUBLIC = REPO / "site" / "public"

TOP_N = 11

FM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fabrication": ("fabricat", "hallucin", "nonexistent api", "made-up", "confabulat"),
    "obsolescence": ("obsolesc", "deprecat", "outdated", "stale api", "api evolution"),
    "dependency_blindness": ("dependency blind", "dependency-blind", "reinvent", "home-rolled", "duplicate code", "reimplement"),
    "logic_error": ("logic error", "logic bug", "reasoning error", "incorrect behavior", "wrong answer"),
    "security_vulnerability": ("security vuln", "vulnerab", " cve", "insecure", "sast", "taint"),
    "scope_creep": ("scope creep", "off-task", "off task", "unrelated change", "out-of-scope"),
    "context_pollution": ("context polluti", "prompt inject", "jailbreak", "context manipul", "indirect injection"),
    "supply_chain_attack": ("supply chain", "slopsquat", "typosquat", "malicious package", "malicious depend"),
    "cascading_failure": ("cascading", "error propagat", "runaway", "cascade"),
    "incomplete_execution": ("incomplete", "partial execution", "unfinished", "stop short", "half-done"),
    "test_manipulation": ("test manipul", "test gaming", "reward hack", "spec gaming", "gaming the test"),
}

FM_DISPLAY = {
    "fabrication": "Fabrication",
    "obsolescence": "Obsolescence",
    "dependency_blindness": "Dependency Blindness",
    "logic_error": "Logic Error",
    "security_vulnerability": "Security Vulnerability",
    "scope_creep": "Scope Creep",
    "context_pollution": "Context Pollution",
    "supply_chain_attack": "Supply-Chain Attack",
    "cascading_failure": "Cascading Failure",
    "incomplete_execution": "Incomplete Execution",
    "test_manipulation": "Test Manipulation",
}


@dataclass
class Row:
    id: str
    name: str
    stars: int
    breadth: int
    tier_sum: int
    row: np.ndarray  # shape (n_fms,), values in 0..3

    def addressed_fms(self, fm_ids: list[str]) -> set[str]:
        return {fm for fm, v in zip(fm_ids, self.row) if v > 0}


def load_tools() -> list[dict]:
    return [yaml.safe_load(open(p)) for p in sorted(glob.glob(str(TOOLS_DIR / "*.yml")))]


def load_fm_ids() -> list[str]:
    return sorted(p.stem for p in FM_DIR.glob("*.yml"))


def rationale_mentions(text: str, fm_id: str) -> bool:
    if not text:
        return False
    t = text.lower()
    if fm_id in t or fm_id.replace("_", " ") in t or fm_id.replace("_", "-") in t:
        return True
    for kw in FM_KEYWORDS.get(fm_id, ()):
        if kw in t:
            return True
    return False


def has_citation_evidence(tool: dict) -> bool:
    return bool(tool.get("cited_in") or tool.get("documented_in") or tool.get("evaluated_on"))


def cell_tier(tool: dict, fm_id: str) -> int:
    addressed = fm_id in (tool.get("addresses_failure_modes") or [])
    if not addressed:
        return 0
    mentioned = rationale_mentions(tool.get("inclusion_rationale") or "", fm_id)
    cited = has_citation_evidence(tool)
    if mentioned and cited:
        return 3
    if mentioned:
        return 2
    return 1


def build_rows(tools: list[dict], fm_ids: list[str]) -> list[Row]:
    out: list[Row] = []
    for t in tools:
        arr = np.array([cell_tier(t, fm) for fm in fm_ids], dtype=int)
        out.append(Row(
            id=t["id"],
            name=t.get("name") or t["id"],
            stars=int(t.get("stars") or 0),
            breadth=int((arr > 0).sum()),
            tier_sum=int(arr.sum()),
            row=arr,
        ))
    return out


def select_breadth(rows: list[Row], n: int) -> list[Row]:
    return sorted(rows, key=lambda r: (-r.breadth, -r.tier_sum, -r.stars))[:n]


def select_covering(rows: list[Row], fm_ids: list[str], n: int) -> list[Row]:
    """Greedy set cover of all FMs, padded to n rows with high-evidence tools.

    Phase 1 (coverage): at each step pick the tool that adds the most
    still-uncovered FMs; tiebreak by tier_sum, then stars, then breadth.
    Stops when every FM is covered or we hit n rows.

    Phase 2 (padding): if coverage used fewer than n tools, fill the
    remaining row budget with the highest-ranked tools not already picked,
    using the same (tier_sum, breadth, stars) order as the breadth view
    so pad rows look like a recognizable "deep bench" beneath the
    specialists — *not* an arbitrary grab bag.

    Result: every FM column has ≥1 filled cell; rows above the dashed
    divider are specialists selected to achieve coverage; rows below are
    pad rows added for depth on the already-covered columns.
    """
    by_id = {r.id: r for r in rows}
    remaining_fms: set[str] = set(fm_ids)
    selected: list[Row] = []
    picked_ids: set[str] = set()

    while remaining_fms and len(selected) < n:
        best: tuple[int, int, int, int] | None = None
        chosen: Row | None = None
        for r in rows:
            if r.id in picked_ids:
                continue
            new = len(r.addressed_fms(fm_ids) & remaining_fms)
            if new == 0:
                continue
            key = (new, r.tier_sum, r.stars, r.breadth)
            if best is None or key > best:
                best = key
                chosen = r
        if chosen is None:
            break
        selected.append(chosen)
        picked_ids.add(chosen.id)
        remaining_fms -= chosen.addressed_fms(fm_ids)

    if len(selected) < n:
        pad_pool = sorted(
            (r for r in rows if r.id not in picked_ids),
            key=lambda r: (-r.tier_sum, -r.breadth, -r.stars),
        )
        for r in pad_pool:
            if len(selected) >= n:
                break
            selected.append(r)
            picked_ids.add(r.id)

    return selected[:n]


def order_columns(selection: list[Row], fm_ids: list[str]) -> list[int]:
    """Column order: most-covered-by-selection FMs on the left."""
    mat = np.vstack([r.row for r in selection])
    col_weight = (mat > 0).sum(axis=0)
    # Stable sort so equal-weight columns keep their FM id order.
    return list(np.argsort(-col_weight, kind="stable"))


def fmt_stars(n: int | None) -> str:
    if not n:
        return "  —  "
    if n >= 1000:
        return f"{n/1000:4.1f}k"
    return f"{n:5d}"


def render_figure(
    selection: list[Row],
    fm_ids: list[str],
    col_order: list[int],
    *,
    title: str,
    out_png: Path,
    out_pdf: Path,
    specialist_divider: int | None = None,
) -> None:
    sub = np.vstack([r.row for r in selection])
    sub_ordered = sub[:, col_order]
    fm_ids_ordered = [fm_ids[i] for i in col_order]

    fig, ax = plt.subplots(figsize=(13.5, 8.5))
    cmap = ListedColormap(["#f5f5f5", "#d8e7f5", "#6aa3d3", "#1f4e79"])
    ax.imshow(sub_ordered, cmap=cmap, vmin=0, vmax=3, aspect="auto")

    ax.set_xticks(np.arange(-0.5, len(fm_ids_ordered), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(selection), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", length=0)

    ax.set_xticks(range(len(fm_ids_ordered)))
    ax.set_xticklabels(
        [FM_DISPLAY.get(f, f) for f in fm_ids_ordered],
        fontsize=9, rotation=40, ha="left", rotation_mode="anchor",
    )
    ax.set_yticks(range(len(selection)))
    ax.set_yticklabels(
        [f"{r.name}  [{fmt_stars(r.stars).strip()}]" for r in selection],
        fontsize=10,
    )
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")

    for i, r in enumerate(selection):
        for j, v in enumerate(sub_ordered[i]):
            if v == 0:
                continue
            color = "white" if v >= 2 else "#1f4e79"
            ax.text(j, i, str(int(v)), ha="center", va="center", fontsize=9, color=color)

    if specialist_divider is not None and 0 < specialist_divider < len(selection):
        ax.axhline(specialist_divider - 0.5, color="#1f4e79",
                   linewidth=1.2, linestyle="--", alpha=0.6)
        ax.text(
            len(fm_ids_ordered) - 0.5, specialist_divider - 0.5,
            "  set-cover ↑  ·  pad for depth ↓",
            fontsize=8, color="#1f4e79", va="center", ha="right",
        )

    ax.set_title(title, fontsize=11, pad=14, loc="left")

    handles = [
        Patch(color="#f5f5f5", label="0 — not addressed"),
        Patch(color="#d8e7f5", label="1 — declared mapping"),
        Patch(color="#6aa3d3", label="2 — rationale discusses FM"),
        Patch(color="#1f4e79", label="3 — + external citation"),
    ]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 0.55),
              frameon=False, fontsize=9, title="Evidence tier", title_fontsize=9)
    ax.text(
        1.01, 0.0,
        "Row labels show GitHub stars.\nStars are *not* used as cell color —\npopularity ≠ per-mapping evidence.",
        transform=ax.transAxes, fontsize=8, color="#555", va="top",
    )

    plt.subplots_adjust(left=0.18, right=0.80, top=0.80, bottom=0.08)
    plt.savefig(out_png, dpi=200)
    plt.savefig(out_pdf)
    plt.close(fig)


def _row_payload(r: Row, fm_ids_ordered: list[str], fm_ids: list[str]) -> dict:
    return {
        "id": r.id, "name": r.name, "stars": r.stars,
        "breadth": r.breadth, "tier_sum": r.tier_sum,
        "tiers": {fm: int(r.row[fm_ids.index(fm)]) for fm in fm_ids_ordered},
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SITE_PUBLIC.mkdir(parents=True, exist_ok=True)

    tools = load_tools()
    fm_ids = load_fm_ids()
    rows = build_rows(tools, fm_ids)

    # --- breadth view (legacy default) ---
    breadth_sel = select_breadth(rows, TOP_N)
    breadth_col_order = order_columns(breadth_sel, fm_ids)
    fm_ids_breadth = [fm_ids[i] for i in breadth_col_order]

    render_figure(
        breadth_sel, fm_ids, breadth_col_order,
        title=(
            "Tool × Failure-Mode evidence  (top 11 tools by coverage breadth)\n"
            "cell = evidence tier: 1 declared · 2 + rationale mention · 3 + external citation"
        ),
        out_png=OUT_DIR / "tool_fm_heatmap.png",
        out_pdf=OUT_DIR / "tool_fm_heatmap.pdf",
    )

    # --- covering view (every column filled) ---
    covering_sel = select_covering(rows, fm_ids, TOP_N)
    # Find the divider: the greedy phase stopped when every FM was covered.
    # Reconstruct that count by re-running the cover loop count-only.
    cover_size = 0
    _covered: set[str] = set()
    for r in covering_sel:
        if set(fm_ids) - _covered:
            cover_size += 1
            _covered |= r.addressed_fms(fm_ids)
            if not (set(fm_ids) - _covered):
                break

    covering_col_order = order_columns(covering_sel, fm_ids)
    fm_ids_covering = [fm_ids[i] for i in covering_col_order]

    render_figure(
        covering_sel, fm_ids, covering_col_order,
        title=(
            "Tool × Failure-Mode evidence  (11 tools, greedy set-cover + depth pad)\n"
            "every failure-mode column has ≥1 tool; top rows are specialists that achieve cover, bottom rows pad for depth"
        ),
        out_png=OUT_DIR / "tool_fm_heatmap_covering.png",
        out_pdf=OUT_DIR / "tool_fm_heatmap_covering.pdf",
        specialist_divider=cover_size,
    )

    # --- JSON payload (site uses the breadth column order; per-scope lists) ---
    all_sorted = sorted(rows, key=lambda r: (-r.breadth, -r.tier_sum, -r.stars))

    payload = {
        "top_n": TOP_N,
        "failure_modes": fm_ids_breadth,
        "failure_mode_display": {k: FM_DISPLAY.get(k, k).replace("\n", " ") for k in fm_ids_breadth},
        "tools_top": [_row_payload(r, fm_ids_breadth, fm_ids) for r in breadth_sel],
        "tools_covering": [_row_payload(r, fm_ids_breadth, fm_ids) for r in covering_sel],
        "covering_divider": cover_size,
        "tools_all": [_row_payload(r, fm_ids_breadth, fm_ids) for r in all_sorted],
        "legend": {
            "0": "not addressed",
            "1": "declared mapping (addresses_failure_modes)",
            "2": "declared + inclusion_rationale discusses the FM",
            "3": "declared + rationale + external citation evidence",
        },
        "selections": {
            "top":      "breadth desc, tier_sum desc, stars desc; top 11",
            "covering": "greedy set-cover (max new FMs, tiebreak tier_sum/stars) then pad by tier_sum/breadth/stars to 11",
            "all":      "every tool with ≥1 declared mapping",
        },
    }
    (OUT_DIR / "tool_fm_heatmap.json").write_text(json.dumps(payload, indent=2))
    (SITE_PUBLIC / "tool_fm_heatmap.json").write_text(json.dumps(payload, indent=2))

    print(f"breadth  view: {OUT_DIR / 'tool_fm_heatmap.png'}")
    print(f"covering view: {OUT_DIR / 'tool_fm_heatmap_covering.png'}"
          f"  (specialists above row {cover_size})")
    print(f"json:          {OUT_DIR / 'tool_fm_heatmap.json'}")
    print(f"site copy:     {SITE_PUBLIC / 'tool_fm_heatmap.json'}")


if __name__ == "__main__":
    main()
