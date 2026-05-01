"""Top-level driver for the κ empirical-validation study.

Runs Rater A (Kimi) and Rater B (rule engine) over the fault corpus,
persists per-rater JSONL + a joined CSV + a κ-metrics JSON, then prints a
human-readable summary.

Usage:
    .venv/bin/python research/kappa/run_kappa.py \
        [--corpus research/kappa_corpus_shah2026.json] \
        [--limit 85] \
        [--skip-kimi] \
        [--kimi-cache research/kappa/kimi_cache.jsonl] \
        [--max-kimi-calls 100]

Budget: hard-caps Kimi calls at ``--max-kimi-calls`` (default 100). Rater B
is free. Every Kimi response is cached to ``--kimi-cache`` so re-runs do
not re-spend.

This file is research scaffolding: no prod-path imports, no DB writes, no
YAML mutations. It reads the corpus JSON, writes per-run artefacts under
``research/kappa_run_<ts>/``, and exits.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Make sure "research" is importable when run from anywhere.
HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv

load_dotenv(REPO / ".env.local")

from pipeline.cost_caps import CallBudget, CostCapExceeded
from research.kappa.rater_b import classify_fault_rules  # noqa: E402

log = logging.getLogger("kappa")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# Rater runners
# ---------------------------------------------------------------------------


def _load_corpus(path: Path, limit: int | None) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if limit is not None:
        data = data[:limit]
    return data


def _load_kimi_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out[rec["fault_id"]] = rec
    return out


def _append_kimi_cache(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def run_rater_a(
    corpus: list[dict],
    *,
    budget: CallBudget,
    cache_path: Path,
    skip_kimi: bool = False,
) -> list[dict]:
    """Run Kimi over each fault. Cache-aware. Honours the call budget."""
    results: list[dict] = []
    cache = _load_kimi_cache(cache_path)
    if skip_kimi:
        log.info("--skip-kimi: using cache only (%d entries)", len(cache))
        for rec in corpus:
            if rec["id"] in cache:
                results.append(cache[rec["id"]])
            else:
                results.append(
                    {
                        "fault_id": rec["id"],
                        "classification": {
                            "control_paradigm": None,
                            "control_paradigm_confidence": 0.0,
                            "temporal_phase": None,
                            "temporal_phase_confidence": 0.0,
                            "failure_modes": [],
                            "failure_modes_confidence": 0.0,
                            "evidence": [],
                        },
                        "error": "not-cached (skip-kimi)",
                    }
                )
        return results

    # Lazy import — avoids tripping env checks when --skip-kimi.
    from pipeline.extract.kappa_rater import classify_fault_kimi, get_client

    client = get_client()
    for i, rec in enumerate(corpus):
        fid = rec["id"]
        if fid in cache:
            log.info("[A %3d/%3d] cache hit %s", i + 1, len(corpus), fid)
            results.append(cache[fid])
            continue
        try:
            c = classify_fault_kimi(
                rec["description"],
                client=client,
                budget=budget,
                fault_id=fid,
            )
            out = {
                "fault_id": fid,
                "classification": c.model_dump(),
            }
        except CostCapExceeded as exc:
            log.warning("budget exceeded after %d calls: %s", i, exc)
            results.append(
                {
                    "fault_id": fid,
                    "classification": {
                        "control_paradigm": None,
                        "control_paradigm_confidence": 0.0,
                        "temporal_phase": None,
                        "temporal_phase_confidence": 0.0,
                        "failure_modes": [],
                        "failure_modes_confidence": 0.0,
                        "evidence": [],
                    },
                    "error": "budget-exceeded",
                }
            )
            # Fall through and stop issuing new calls; remaining corpus rows
            # get the same placeholder so ratings align by index.
            for later in corpus[i + 1 :]:
                results.append(
                    {
                        "fault_id": later["id"],
                        "classification": {
                            "control_paradigm": None,
                            "control_paradigm_confidence": 0.0,
                            "temporal_phase": None,
                            "temporal_phase_confidence": 0.0,
                            "failure_modes": [],
                            "failure_modes_confidence": 0.0,
                            "evidence": [],
                        },
                        "error": "budget-exceeded-downstream",
                    }
                )
            return results
        except Exception as exc:  # noqa: BLE001
            log.error("[A %3d/%3d] %s FAILED: %s", i + 1, len(corpus), fid, exc)
            out = {
                "fault_id": fid,
                "classification": {
                    "control_paradigm": None,
                    "control_paradigm_confidence": 0.0,
                    "temporal_phase": None,
                    "temporal_phase_confidence": 0.0,
                    "failure_modes": [],
                    "failure_modes_confidence": 0.0,
                    "evidence": [],
                },
                "error": str(exc)[:200],
            }
        _append_kimi_cache(cache_path, out)
        cache[fid] = out
        results.append(out)
        log.info(
            "[A %3d/%3d] %s CP=%s TP=%s modes=%s",
            i + 1,
            len(corpus),
            fid,
            out["classification"].get("control_paradigm"),
            out["classification"].get("temporal_phase"),
            out["classification"].get("failure_modes"),
        )
    return results


def run_rater_b(corpus: list[dict]) -> list[dict]:
    out: list[dict] = []
    for rec in corpus:
        c = classify_fault_rules(rec["description"])
        out.append({"fault_id": rec["id"], "classification": c.to_dict()})
    return out


# ---------------------------------------------------------------------------
# κ computation
# ---------------------------------------------------------------------------


def _pairwise_labels(
    rater_a: list[dict], rater_b: list[dict], facet: str
) -> tuple[list[str], list[str]]:
    """Return aligned label lists for a single-label facet.

    Missing / None values are coerced to the literal string ``"__null__"`` so
    :func:`sklearn.metrics.cohen_kappa_score` treats them as an additional
    class. Raters both emitting null for the same row is counted as agreement.
    """
    la: list[str] = []
    lb: list[str] = []
    a_by_id = {r["fault_id"]: r for r in rater_a}
    for rb in rater_b:
        fid = rb["fault_id"]
        ra = a_by_id.get(fid, {"classification": {}})
        va = ra["classification"].get(facet) or "__null__"
        vb = rb["classification"].get(facet) or "__null__"
        la.append(str(va))
        lb.append(str(vb))
    return la, lb


def _binary_mode_vectors(
    rater_a: list[dict], rater_b: list[dict], mode: str
) -> tuple[list[int], list[int]]:
    """Return 0/1 vectors over the corpus for a single FailureMode id."""
    va: list[int] = []
    vb: list[int] = []
    a_by_id = {r["fault_id"]: r for r in rater_a}
    for rb in rater_b:
        fid = rb["fault_id"]
        ra = a_by_id.get(fid, {"classification": {}})
        a_modes = set(ra["classification"].get("failure_modes") or [])
        b_modes = set(rb["classification"].get("failure_modes") or [])
        va.append(1 if mode in a_modes else 0)
        vb.append(1 if mode in b_modes else 0)
    return va, vb


def _jaccard(rater_a: list[dict], rater_b: list[dict]) -> float:
    """Mean Jaccard index of failure_modes sets across the corpus."""
    a_by_id = {r["fault_id"]: r for r in rater_a}
    ratios: list[float] = []
    for rb in rater_b:
        fid = rb["fault_id"]
        ra = a_by_id.get(fid, {"classification": {}})
        a_modes = set(ra["classification"].get("failure_modes") or [])
        b_modes = set(rb["classification"].get("failure_modes") or [])
        if not a_modes and not b_modes:
            ratios.append(1.0)
            continue
        union = a_modes | b_modes
        inter = a_modes & b_modes
        ratios.append(len(inter) / len(union) if union else 1.0)
    return sum(ratios) / len(ratios) if ratios else 0.0


def compute_kappas(
    rater_a: list[dict], rater_b: list[dict], all_modes: list[str]
) -> dict:
    """Compute all κ metrics for the §5 writeup."""
    from sklearn.metrics import cohen_kappa_score, confusion_matrix

    metrics: dict[str, Any] = {}

    for facet in ("control_paradigm", "temporal_phase"):
        la, lb = _pairwise_labels(rater_a, rater_b, facet)
        # Sorted union of labels for a stable confusion-matrix axis.
        labels = sorted(set(la) | set(lb))
        kappa = (
            float(cohen_kappa_score(la, lb, labels=labels)) if len(labels) >= 2 else 1.0
        )
        cm = confusion_matrix(la, lb, labels=labels).tolist()
        metrics[facet] = {
            "kappa": kappa,
            "labels": labels,
            "confusion_matrix": cm,
            "n": len(la),
        }

    # FailureMode: per-mode binary κ + Jaccard.
    per_mode: dict[str, dict] = {}
    ks: list[float] = []
    for mode in all_modes:
        va, vb = _binary_mode_vectors(rater_a, rater_b, mode)
        # Skip modes where BOTH raters never assert the label — κ is undefined.
        if sum(va) == 0 and sum(vb) == 0:
            per_mode[mode] = {
                "kappa": None,
                "note": "neither rater assigned",
                "support_a": 0,
                "support_b": 0,
            }
            continue
        try:
            k = float(cohen_kappa_score(va, vb))
        except Exception:
            k = float("nan")
        per_mode[mode] = {
            "kappa": k,
            "support_a": int(sum(va)),
            "support_b": int(sum(vb)),
            "both": int(sum(1 for i in range(len(va)) if va[i] == 1 and vb[i] == 1)),
        }
        if k == k:  # not NaN
            ks.append(k)
    metrics["failure_mode"] = {
        "per_mode": per_mode,
        "kappa_mean": sum(ks) / len(ks) if ks else 0.0,
        "jaccard_mean": _jaccard(rater_a, rater_b),
        "n": len(rater_b),
    }
    return metrics


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _write_joined_csv(
    path: Path,
    corpus: list[dict],
    rater_a: list[dict],
    rater_b: list[dict],
) -> None:
    a_by_id = {r["fault_id"]: r for r in rater_a}
    b_by_id = {r["fault_id"]: r for r in rater_b}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "fault_id",
                "shah_subcategory",
                "A_cp",
                "B_cp",
                "A_tp",
                "B_tp",
                "A_modes",
                "B_modes",
                "description_excerpt",
            ]
        )
        for rec in corpus:
            fid = rec["id"]
            ra = a_by_id.get(fid, {}).get("classification", {})
            rb = b_by_id.get(fid, {}).get("classification", {})
            w.writerow(
                [
                    fid,
                    rec.get("shah_subcategory", ""),
                    ra.get("control_paradigm") or "",
                    rb.get("control_paradigm") or "",
                    ra.get("temporal_phase") or "",
                    rb.get("temporal_phase") or "",
                    "|".join(ra.get("failure_modes") or []),
                    "|".join(rb.get("failure_modes") or []),
                    (rec.get("description") or "")[:200],
                ]
            )


def _render_ascii_confusion(metrics: dict, facet: str) -> str:
    m = metrics[facet]
    labels = m["labels"]
    cm = m["confusion_matrix"]
    # Shorten labels to 16 chars.
    short = [l[:16] for l in labels]
    header_line = " " * 18 + "".join(f"{s:>18}" for s in short)
    rows = [header_line]
    for i, lab in enumerate(short):
        row = f"{lab:>18}" + "".join(f"{cm[i][j]:>18}" for j in range(len(short)))
        rows.append(row)
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--corpus", default=str(REPO / "research/kappa_corpus_shah2026.json")
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--skip-kimi", action="store_true")
    p.add_argument(
        "--kimi-cache",
        default=str(REPO / "research/kappa/kimi_cache.jsonl"),
    )
    p.add_argument("--max-kimi-calls", type=int, default=100)
    args = p.parse_args()

    corpus = _load_corpus(Path(args.corpus), args.limit)
    log.info("loaded %d fault records from %s", len(corpus), args.corpus)

    ts = _dt.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    run_dir = REPO / f"research/kappa_run_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info("run dir: %s", run_dir)

    budget = CallBudget(max_calls=args.max_kimi_calls)

    log.info("==> Rater A (Kimi)")
    rater_a = run_rater_a(
        corpus,
        budget=budget,
        cache_path=Path(args.kimi_cache),
        skip_kimi=args.skip_kimi,
    )
    _write_jsonl(run_dir / "rater_A.jsonl", rater_a)

    log.info("==> Rater B (rules)")
    rater_b = run_rater_b(corpus)
    _write_jsonl(run_dir / "rater_B.jsonl", rater_b)

    # FailureMode universe: union of every id either rater ever emits plus
    # the canonical list so Kappa for "never-assigned" modes is surfaced.
    from pipeline.models import FailureModeId

    all_modes = [m.value for m in FailureModeId]

    log.info("==> computing κ")
    metrics = compute_kappas(rater_a, rater_b, all_modes)

    # Write results artefacts.
    _write_joined_csv(run_dir / "joined.csv", corpus, rater_a, rater_b)
    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    # Summary text to stdout.
    summary_lines = []
    summary_lines.append(f"# κ summary (N={len(corpus)})")
    summary_lines.append("")
    summary_lines.append(
        f"Kimi calls made: {budget._calls_made}  tokens≈{budget._tokens_used}"
    )
    summary_lines.append("")
    for facet in ("control_paradigm", "temporal_phase"):
        m = metrics[facet]
        summary_lines.append(
            f"{facet}: κ={m['kappa']:.3f}  labels={m['labels']}  n={m['n']}"
        )
        summary_lines.append(_render_ascii_confusion(metrics, facet))
        summary_lines.append("")
    fm = metrics["failure_mode"]
    summary_lines.append(
        f"failure_mode: κ_mean={fm['kappa_mean']:.3f}  jaccard_mean={fm['jaccard_mean']:.3f}  n={fm['n']}"
    )
    summary_lines.append("Per-mode breakdown:")
    for mode, stats in fm["per_mode"].items():
        if stats["kappa"] is None:
            summary_lines.append(
                f"  {mode:<28} κ=--   (support A={stats['support_a']} B={stats['support_b']})"
            )
        else:
            summary_lines.append(
                f"  {mode:<28} κ={stats['kappa']:+.3f}"
                f"  A={stats['support_a']}  B={stats['support_b']}  both={stats['both']}"
            )
    text = "\n".join(summary_lines)
    with open(run_dir / "summary.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)

    # Symlink latest for convenience.
    latest = REPO / "research/kappa_run_latest"
    if latest.is_symlink() or latest.exists():
        try:
            latest.unlink()
        except OSError:
            pass
    try:
        latest.symlink_to(run_dir)
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
