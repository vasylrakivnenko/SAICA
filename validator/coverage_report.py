#!/usr/bin/env python3
"""SAICA-KG coverage / gap reporter.

Produces a human-readable Markdown report (plus optional JSON sidecar)
describing where the KG is thin and what to add next. Never exits non-zero:
reports are diagnostics, not errors.

Usage:
    python validator/coverage_report.py                      # -> research/coverage_report.md
    python validator/coverage_report.py --out path.md        # custom path
    python validator/coverage_report.py --json               # also emit sibling .json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print(
        "Missing dependency: pyyaml. Install with: pip install pyyaml", file=sys.stderr
    )
    sys.exit(2)


REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"

CONTROL_PARADIGMS = ["prevention", "detection", "correction", "recovery"]
TEMPORAL_PHASES = ["pre_generation", "in_generation", "post_generation"]
AUTONOMY_LEVELS = ["fully_autonomous", "graduated_hitl", "full_hitl"]

FAILURE_MODES_CANONICAL = [
    "fabrication",
    "obsolescence",
    "dependency_blindness",
    "logic_error",
    "security_vulnerability",
    "scope_creep",
    "context_pollution",
    "supply_chain_attack",
]

STALE_DAYS_THRESHOLD = 180
TODAY = dt.date(
    2026, 4, 22
)  # hardcoded per spec; also matches dt.date.today() in this env

# Keyword heuristics for "papers a tool probably ought to cite" (Section 7).
# Each tuple: (paper_id, keywords that should match the tool description/tagline).
PAPER_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "spracklen-2024-we-have-a-package",
        ["slopsquat", "package hallucin", "typosquat", "supply chain", "supply-chain"],
    ),
    ("liu-2024-beyond-functional-correctness", ["hallucin", "fabricat"]),
    ("tian-2024-codehalu", ["hallucin", "code halu"]),
    ("zhang-wang-shi-ma-2024-practical-hallucination", ["hallucin"]),
    ("lee-2025-hallucination-taxonomy", ["hallucin"]),
    (
        "wang-2024-llms-meet-library-evolution",
        ["deprecat", "library evolution", "obsolescen", "version"],
    ),
    ("liu-2025-code-copycat", ["repetition", "copycat", "duplicat"]),
    ("cemri-2025-mast", ["multi-agent", "multi agent", "mas"]),
    ("williams-2025-sscs", ["supply chain", "supply-chain", "sscs"]),
    ("lindner-2025-monitoring", ["monitor", "observability", "trace"]),
    (
        "manheim-homewood-2025-control-oversight",
        ["oversight", "control", "supervision"],
    ),
    ("navneet-2025-safe-ai", ["safety", "safe ai"]),
    ("cihon-stein-2025-autonomy-scoring", ["autonomy", "autonomous"]),
    ("yan-2025-fault-tolerant-sandboxing", ["sandbox", "isolation", "fault toleran"]),
    ("luo-2025-mcp-universe", ["mcp", "model context protocol"]),
    ("xu-2025-ckgfuzzer", ["fuzz", "fuzzing"]),
    ("morabito-wu-2025-code-autopilot", ["autopilot", "coding agent"]),
    ("qi-2026-rift", ["rift", "regression"]),
    ("xue-uddin-2025-pagent", ["pagent", "planning agent"]),
    ("shah-2026-characterizing-faults", ["fault", "characteriz"]),
    ("ehsani-2026-where-ai-agents-fail", ["fail", "failure"]),
    ("zhu-2025-agent-error-taxonomy", ["error taxonomy", "agent error"]),
    ("jiang-2024-survey-llm-code", ["survey", "llm code"]),
    (
        "spracklen-2024-we-have-a-package",
        ["hallucinated package", "non-existent package"],
    ),
]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _coerce(value: Any) -> Any:
    """Convert date/datetime to ISO strings recursively (matches validator/cli.py)."""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _coerce(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce(v) for v in value]
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    return _coerce(data) if isinstance(data, dict) else {}


def load_dir(kind: str) -> list[dict[str, Any]]:
    subdir = DATA_DIR / kind
    if not subdir.exists():
        return []
    out = []
    for p in sorted(subdir.glob("*.yml")) + sorted(subdir.glob("*.yaml")):
        d = load_yaml(p)
        if d:
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def parse_date(s: Any) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(str(s))
    except ValueError:
        return None


def facet_cells(tools: list[dict]) -> list[dict]:
    """Return all 4*3*3 cells with tool membership."""
    index: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for t in tools:
        key = (
            t.get("control_paradigm"),
            t.get("temporal_phase"),
            t.get("autonomy_level"),
        )
        index[key].append(t.get("name") or t.get("id"))
    cells = []
    for cp in CONTROL_PARADIGMS:
        for tp in TEMPORAL_PHASES:
            for al in AUTONOMY_LEVELS:
                names = sorted(index.get((cp, tp, al), []))
                cells.append(
                    {
                        "control_paradigm": cp,
                        "temporal_phase": tp,
                        "autonomy_level": al,
                        "count": len(names),
                        "tools": names,
                        "empty": len(names) == 0,
                    }
                )
    return cells


def mitigators_by_mode(tools: list[dict]) -> dict[str, list[str]]:
    by: dict[str, list[str]] = defaultdict(list)
    for t in tools:
        for fm in t.get("addresses_failure_modes") or []:
            by[fm].append(t.get("name") or t.get("id"))
    for k in by:
        by[k] = sorted(by[k])
    return by


def crosswalk_counts_by_mode(
    modes: list[dict], crosswalks: list[dict]
) -> dict[str, int]:
    """Total external-taxonomy crosswalk entries per SAICA FailureMode (inline + bulk)."""
    counts: Counter = Counter()
    # Inline crosswalks on FailureMode nodes
    for m in modes:
        for cw in m.get("crosswalks") or []:
            counts[m["id"]] += 1
    # Bulk Crosswalk docs
    for doc in crosswalks:
        if doc.get("saica_axis") != "failure_mode":
            continue
        for mp in doc.get("mappings") or []:
            counts[mp.get("saica_value")] += 1
    return dict(counts)


def taxonomy_completeness(
    taxonomies: list[dict], modes: list[dict], crosswalks: list[dict]
) -> list[dict]:
    """Per-taxonomy: categories total, # SAICA modes mapped, missing category ids."""
    rows = []
    # external_id sets touched by inline + bulk, indexed by taxonomy id
    touched_by_tax: dict[str, set[str]] = defaultdict(set)
    mapped_modes_by_tax: dict[str, set[str]] = defaultdict(set)

    for m in modes:
        for cw in m.get("crosswalks") or []:
            touched_by_tax[cw["taxonomy"]].add(cw["external_id"])
            mapped_modes_by_tax[cw["taxonomy"]].add(m["id"])

    for doc in crosswalks:
        if doc.get("saica_axis") != "failure_mode":
            continue
        tax = doc.get("taxonomy")
        for mp in doc.get("mappings") or []:
            touched_by_tax[tax].add(mp.get("external_id"))
            mapped_modes_by_tax[tax].add(mp.get("saica_value"))

    for tx in taxonomies:
        tx_id = tx["id"]
        cats = tx.get("categories") or []
        cat_ids = [c["external_id"] for c in cats]
        touched = touched_by_tax.get(tx_id, set())
        missing = [cid for cid in cat_ids if cid not in touched]
        rows.append(
            {
                "id": tx_id,
                "name": tx.get("name", tx_id),
                "category_count": len(cat_ids),
                "mapped_saica_modes": sorted(mapped_modes_by_tax.get(tx_id, set())),
                "mapped_mode_count": len(mapped_modes_by_tax.get(tx_id, set())),
                "covered_categories": len(cat_ids) - len(missing),
                "missing_categories": missing,
            }
        )
    return rows


def stale_rows(tools: list[dict]) -> list[dict]:
    rows = []
    for t in tools:
        last = parse_date(t.get("last_updated"))
        age_days = (TODAY - last).days if last else None
        rows.append(
            {
                "id": t["id"],
                "name": t.get("name", t["id"]),
                "last_updated": t.get("last_updated"),
                "age_days": age_days,
                "maturity_status": t.get("maturity_status"),
                "stale": (age_days is not None and age_days > STALE_DAYS_THRESHOLD),
                "at_risk": t.get("maturity_status") == "at_risk",
            }
        )
    rows.sort(key=lambda r: (r["last_updated"] or "0000-00-00"))
    return rows


def missing_metadata(tools: list[dict]) -> list[dict]:
    """Report tools missing any of: stars, openssf_scorecard_score, cited_in, inclusion_rationale.

    `stars` is considered missing if the key is absent OR None (GitHub fetch failed
    / no repo). `openssf_scorecard_score` is considered missing if absent or None.
    `cited_in` and `inclusion_rationale` are considered missing if empty or absent.
    """
    out = []
    for t in tools:
        missing: list[str] = []
        if "stars" not in t or t.get("stars") is None:
            missing.append("stars")
        if (
            "openssf_scorecard_score" not in t
            or t.get("openssf_scorecard_score") is None
        ):
            missing.append("openssf_scorecard_score")
        if not t.get("cited_in"):
            missing.append("cited_in")
        if not t.get("inclusion_rationale"):
            missing.append("inclusion_rationale")
        if missing:
            out.append(
                {
                    "id": t["id"],
                    "name": t.get("name", t["id"]),
                    "missing": missing,
                }
            )
    return out


def paper_suggestions(tools: list[dict], papers_by_id: dict[str, dict]) -> list[dict]:
    """Tools with empty cited_in whose description mentions known paper keywords."""
    suggestions: list[dict] = []
    for t in tools:
        if t.get("cited_in"):
            continue
        blob = " ".join(
            [
                t.get("description") or "",
                t.get("tagline") or "",
                t.get("inclusion_rationale") or "",
                " ".join(t.get("implements_techniques") or []),
            ]
        ).lower()
        hits: list[str] = []
        for paper_id, kws in PAPER_KEYWORDS:
            if paper_id not in papers_by_id:
                continue
            if any(k in blob for k in kws):
                if paper_id not in hits:
                    hits.append(paper_id)
        if hits:
            suggestions.append(
                {
                    "id": t["id"],
                    "name": t.get("name", t["id"]),
                    "suggested_papers": hits,
                }
            )
    return suggestions


def org_counts(tools: list[dict]) -> list[dict]:
    c: Counter = Counter()
    for t in tools:
        org = t.get("published_by") or "<unknown>"
        c[org] += 1
    total = sum(c.values()) or 1
    rows = [{"org": org, "count": n, "share": n / total} for org, n in c.most_common()]
    return rows


# ---------------------------------------------------------------------------
# Next-step prioritization
# ---------------------------------------------------------------------------


def next_steps(
    cells: list[dict],
    mitigators: dict[str, list[str]],
    mode_crosswalk_counts: dict[str, int],
    tax_rows: list[dict],
    stale: list[dict],
    missing: list[dict],
    orgs: list[dict],
) -> list[str]:
    steps: list[tuple[int, str]] = []  # (priority-weight, text) -- lower = earlier

    # Empty facet cells — highest priority: they are the prescriptive gaps.
    empty = [c for c in cells if c["empty"]]
    for c in empty:
        steps.append(
            (
                0,
                f"Add Tool for {c['control_paradigm']} x {c['temporal_phase']} x {c['autonomy_level']} "
                f"(0 tools in that cell)",
            )
        )

    # Under-covered failure modes (<3 mitigators), sorted by fewest mitigators first.
    under = sorted(
        [(fm, len(mitigators.get(fm, []))) for fm in FAILURE_MODES_CANONICAL],
        key=lambda x: x[1],
    )
    for fm, n in under:
        if n < 3:
            steps.append(
                (
                    1,
                    f"FailureMode '{fm}' has only {n} mitigators - add supervision tools that address it",
                )
            )

    # Taxonomy coverage gaps
    for tx in tax_rows:
        missing_n = len(tx["missing_categories"])
        if missing_n:
            sample = ", ".join(tx["missing_categories"][:5])
            more = " ..." if missing_n > 5 else ""
            steps.append(
                (
                    2,
                    f"{tx['name']} has {tx['category_count']} categories; {tx['covered_categories']} crosswalked - "
                    f"map remaining {missing_n} ({sample}{more})",
                )
            )

    # Modes with no external-taxonomy crosswalk at all
    for fm in FAILURE_MODES_CANONICAL:
        if mode_crosswalk_counts.get(fm, 0) == 0:
            steps.append(
                (
                    3,
                    f"FailureMode '{fm}' has no external-taxonomy crosswalks - add at least one",
                )
            )

    # Stale / at-risk tools
    stale_n = sum(1 for r in stale if r["stale"])
    if stale_n:
        worst = max(
            (r for r in stale if r["stale"]),
            key=lambda r: r["age_days"] or 0,
            default=None,
        )
        if worst:
            steps.append(
                (
                    4,
                    f"Re-review {stale_n} tools with last_updated > {STALE_DAYS_THRESHOLD} days "
                    f"(oldest: {worst['name']} at {worst['age_days']} days)",
                )
            )
    at_risk_n = sum(1 for r in stale if r["at_risk"])
    if at_risk_n:
        steps.append(
            (
                4,
                f"{at_risk_n} tools flagged at_risk - confirm successor or mark deprecated",
            )
        )

    # Missing-metadata rollup
    metadata_counts: Counter = Counter()
    for row in missing:
        for f in row["missing"]:
            metadata_counts[f] += 1
    for field, n in metadata_counts.most_common():
        steps.append((5, f"Populate '{field}' on {n} tools"))

    # Governance bias
    for org in orgs:
        if org["share"] > 0.30:
            steps.append(
                (
                    6,
                    f"Org '{org['org']}' produces {org['count']} tools ({org['share']*100:.0f}%) "
                    f"- diversify sources to reduce vendor bias",
                )
            )

    steps.sort(key=lambda x: x[0])
    return [t for _, t in steps][:10]


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def md_table(header: list[str], rows: list[list[str]]) -> str:
    out = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def render_markdown(ctx: dict[str, Any]) -> str:
    tools = ctx["tools"]
    modes = ctx["modes"]
    papers = ctx["papers"]
    taxonomies = ctx["taxonomies"]
    crosswalks = ctx["crosswalks"]
    cells = ctx["facet_cells"]
    mitigators = ctx["mitigators"]
    mode_cw_counts = ctx["mode_cw_counts"]
    tax_rows = ctx["tax_rows"]
    stale = ctx["stale"]
    missing = ctx["missing"]
    suggestions = ctx["paper_suggestions"]
    orgs = ctx["orgs"]
    steps = ctx["next_steps"]

    generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    empty_cells = [c for c in cells if c["empty"]]
    under_covered = [
        fm for fm in FAILURE_MODES_CANONICAL if len(mitigators.get(fm, [])) < 3
    ]
    stale_n = sum(1 for r in stale if r["stale"])

    lines: list[str] = []
    lines.append("# SAICA-KG Coverage & Gap Report")
    lines.append("")
    lines.append(f"_Generated: {generated_at} (report date: {TODAY.isoformat()})_")
    lines.append("")
    lines.append(
        "This report highlights where the SAICA-KG is thin and what to add next. "
        "It is produced by `validator/coverage_report.py` and never blocks CI; "
        "the companion script `validator/cli.py` handles hard invariants."
    )
    lines.append("")

    # ---- 1. Summary ----
    lines.append("## 1. Summary")
    lines.append("")
    lines.append(
        md_table(
            ["Node type", "Count"],
            [
                ["Tools", len(tools)],
                ["FailureModes", len(modes)],
                ["Papers", len(papers)],
                ["Taxonomies", len(taxonomies)],
                ["Crosswalks (bulk)", len(crosswalks)],
                ["Facet cells (filled / 36)", f"{36 - len(empty_cells)} / 36"],
                ["FailureModes with < 3 mitigators", len(under_covered)],
                ["Tools older than 180 days", stale_n],
            ],
        )
    )
    lines.append("")

    # ---- 2. Facet-cell occupancy ----
    lines.append(
        "## 2. Facet-cell occupancy (ControlParadigm x TemporalPhase x AutonomyLevel)"
    )
    lines.append("")
    lines.append(f"Total cells: 4 x 3 x 3 = 36. Empty cells: **{len(empty_cells)}**.")
    lines.append("")
    rows = []
    for c in cells:
        flag = "**WARN EMPTY**" if c["empty"] else ""
        tool_list = ", ".join(c["tools"]) if c["tools"] else flag
        rows.append(
            [
                c["control_paradigm"],
                c["temporal_phase"],
                c["autonomy_level"],
                c["count"],
                tool_list,
            ]
        )
    lines.append(
        md_table(
            [
                "control_paradigm",
                "temporal_phase",
                "autonomy_level",
                "# tools",
                "tool names",
            ],
            rows,
        )
    )
    lines.append("")
    if empty_cells:
        lines.append("### Empty cells (prescriptive gaps)")
        lines.append("")
        for c in empty_cells:
            lines.append(
                f"- `{c['control_paradigm']}` x `{c['temporal_phase']}` x `{c['autonomy_level']}`"
            )
        lines.append("")

    # ---- 3. FailureMode coverage ----
    lines.append("## 3. FailureMode coverage")
    lines.append("")
    rows = []
    for fm in FAILURE_MODES_CANONICAL:
        tools_for = mitigators.get(fm, [])
        n = len(tools_for)
        flag = "**UNDER-COVERED**" if n < 3 else ""
        rows.append(
            [
                fm,
                n,
                flag,
                mode_cw_counts.get(fm, 0),
                ", ".join(tools_for) if tools_for else "_(none)_",
            ]
        )
    lines.append(
        md_table(
            [
                "failure_mode",
                "# mitigators",
                "flag",
                "# external crosswalks",
                "mitigating tools",
            ],
            rows,
        )
    )
    lines.append("")

    # ---- 4. Taxonomy crosswalk completeness ----
    lines.append("## 4. Taxonomy crosswalk completeness")
    lines.append("")
    rows = []
    for tx in tax_rows:
        missing_sample = ", ".join(tx["missing_categories"][:8])
        if len(tx["missing_categories"]) > 8:
            missing_sample += f", ... (+{len(tx['missing_categories']) - 8} more)"
        rows.append(
            [
                tx["id"],
                tx["category_count"],
                tx["mapped_mode_count"],
                tx["covered_categories"],
                len(tx["missing_categories"]),
                missing_sample or "_(all covered)_",
            ]
        )
    lines.append(
        md_table(
            [
                "taxonomy",
                "# categories",
                "# SAICA modes mapped",
                "# categories covered",
                "# missing",
                "missing category ids",
            ],
            rows,
        )
    )
    lines.append("")

    # ---- 5. Staleness ----
    lines.append("## 5. Staleness table")
    lines.append("")
    lines.append(
        f"Tools sorted by `last_updated` ascending. "
        f"Flag = age > {STALE_DAYS_THRESHOLD} days vs {TODAY.isoformat()}, "
        f"or `maturity_status: at_risk`."
    )
    lines.append("")
    rows = []
    for r in stale:
        flags = []
        if r["stale"]:
            flags.append("STALE")
        if r["at_risk"]:
            flags.append("AT_RISK")
        rows.append(
            [
                r["id"],
                r["last_updated"] or "_(none)_",
                r["age_days"] if r["age_days"] is not None else "_n/a_",
                r["maturity_status"] or "_(none)_",
                ", ".join(flags) if flags else "",
            ]
        )
    lines.append(
        md_table(
            ["tool", "last_updated", "age_days", "maturity_status", "flags"],
            rows,
        )
    )
    lines.append("")

    # ---- 6. Missing metadata ----
    lines.append("## 6. Tools with missing metadata")
    lines.append("")
    if missing:
        rows = [[r["id"], ", ".join(r["missing"])] for r in missing]
        lines.append(md_table(["tool", "missing fields"], rows))
    else:
        lines.append("_All tools have complete metadata._")
    lines.append("")

    # ---- 7. Paper citation suggestions ----
    lines.append("## 7. Papers the tool description suggests should be cited")
    lines.append("")
    lines.append(
        "_Best-effort keyword matching. Suggestions only; no YAML edits performed._"
    )
    lines.append("")
    if suggestions:
        rows = [[s["id"], ", ".join(s["suggested_papers"])] for s in suggestions]
        lines.append(md_table(["tool (cited_in is empty)", "suggested papers"], rows))
    else:
        lines.append("_No suggestions generated._")
    lines.append("")

    # ---- 8. Governance hygiene ----
    lines.append("## 8. Governance hygiene (Tools by `published_by`)")
    lines.append("")
    rows = []
    for o in orgs:
        flag = "**>30% of tools — potential bias**" if o["share"] > 0.30 else ""
        rows.append([o["org"], o["count"], f"{o['share']*100:.1f}%", flag])
    lines.append(md_table(["org", "# tools", "share", "flag"], rows))
    lines.append("")

    # ---- 9. Top-10 actionable next steps ----
    lines.append("## 9. Top 10 actionable next steps")
    lines.append("")
    if steps:
        for i, s in enumerate(steps, 1):
            lines.append(f"{i}. {s}")
    else:
        lines.append("_Nothing flagged — report is boringly clean._")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def build_context() -> dict[str, Any]:
    tools = load_dir("tools")
    modes = load_dir("failure_modes")
    papers = load_dir("papers")
    taxonomies = load_dir("taxonomies")
    crosswalks = load_dir("crosswalks")

    papers_by_id = {p["id"]: p for p in papers}
    cells = facet_cells(tools)
    mitigators = mitigators_by_mode(tools)
    mode_cw_counts = crosswalk_counts_by_mode(modes, crosswalks)
    tax_rows = taxonomy_completeness(taxonomies, modes, crosswalks)
    stale = stale_rows(tools)
    missing = missing_metadata(tools)
    suggestions = paper_suggestions(tools, papers_by_id)
    orgs = org_counts(tools)
    steps = next_steps(
        cells, mitigators, mode_cw_counts, tax_rows, stale, missing, orgs
    )

    return {
        "tools": tools,
        "modes": modes,
        "papers": papers,
        "taxonomies": taxonomies,
        "crosswalks": crosswalks,
        "facet_cells": cells,
        "mitigators": mitigators,
        "mode_cw_counts": mode_cw_counts,
        "tax_rows": tax_rows,
        "stale": stale,
        "missing": missing,
        "paper_suggestions": suggestions,
        "orgs": orgs,
        "next_steps": steps,
    }


def json_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    """Drop raw YAML blobs; keep aggregates suitable for programmatic use."""
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "report_date": TODAY.isoformat(),
        "totals": {
            "tools": len(ctx["tools"]),
            "failure_modes": len(ctx["modes"]),
            "papers": len(ctx["papers"]),
            "taxonomies": len(ctx["taxonomies"]),
            "crosswalks": len(ctx["crosswalks"]),
        },
        "facet_cells": ctx["facet_cells"],
        "mitigators_by_mode": {k: v for k, v in ctx["mitigators"].items()},
        "mode_crosswalk_counts": ctx["mode_cw_counts"],
        "taxonomies": ctx["tax_rows"],
        "stale": ctx["stale"],
        "missing_metadata": ctx["missing"],
        "paper_suggestions": ctx["paper_suggestions"],
        "orgs": ctx["orgs"],
        "next_steps": ctx["next_steps"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        default=str(REPO / "research" / "coverage_report.md"),
        help="Output Markdown path (default: research/coverage_report.md)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Also write a sibling .json file with structured data.",
    )
    args = ap.parse_args()

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ctx = build_context()
    out_path.write_text(render_markdown(ctx))

    if args.json:
        json_path = out_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(json_payload(ctx), indent=2, sort_keys=False) + "\n"
        )
        print(f"Wrote {out_path} and {json_path}")
    else:
        print(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
