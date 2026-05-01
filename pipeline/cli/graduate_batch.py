"""Batch-graduation helper for Phase 2 candidates.

Reads a curated list of candidate_tool ids from Postgres, synthesizes
a valid Tool YAML for each, and writes to data/tools/.

Unlike ``graduate.py``'s conservative strict-enum approach (which leaves
REVIEW_REQUIRED sentinels that break the validator), this helper uses
Kimi's low-confidence facets as drafts and fills in ``fully_autonomous``
as the autonomy default when Kimi's value is null. Every graduated YAML
carries a provenance block so the reviewer can retrace the path.

Usage:
    python -m pipeline.cli.graduate_batch --ids 97,229,239,273,237,...

Always writes fresh files — refuses to overwrite existing YAMLs.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from typing import Any, Optional

from pipeline import config, db, dedup
from pipeline.logging_config import configure_logging

log = logging.getLogger(__name__)

DATA_TOOLS = config.REPO_ROOT / "data" / "tools"

# Fallback autonomy default — most supervision tools operate at fully_autonomous.
AUTONOMY_DEFAULT = "fully_autonomous"

# Valid enum values for sanity checking.
PARADIGM = {"prevention", "detection", "correction", "recovery"}
PHASE = {"pre_generation", "in_generation", "post_generation"}
AUTONOMY = {"fully_autonomous", "graduated_hitl", "full_hitl"}
FAILURE_MODES = {
    "fabrication",
    "obsolescence",
    "dependency_blindness",
    "logic_error",
    "security_vulnerability",
    "scope_creep",
    "context_pollution",
    "supply_chain_attack",
}


def _val(payload: dict, field: str) -> Any:
    return (payload.get(field) or {}).get("value")


def _conf(payload: dict, field: str) -> float:
    return float((payload.get(field) or {}).get("confidence") or 0.0)


def _load_raw_json(source_url: str) -> Optional[dict]:
    canon = dedup.canonical_github_url(source_url) or source_url
    sql = """
        SELECT raw_json FROM raw_search_results
        WHERE url = %s OR url = %s
        ORDER BY fetched_at DESC LIMIT 1
    """
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (source_url, canon))
        row = cur.fetchone()
        return row[0] if row else None


def _github_field(raw: Optional[dict], *path: str) -> Any:
    if not raw:
        return None
    # sources/github.py writes {"query":..., "result": {...}}
    node = raw.get("result", raw)
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def build_tool_yaml(cand: dict) -> Optional[str]:
    """Return YAML text for a Tool, or None if we can't build a valid one."""
    if not cand.get("extracted"):
        log.warning("id=%s: no extraction; skip", cand["id"])
        return None
    ext = cand["extracted"]
    payload = ext.get("payload") or {}

    paradigm = _val(payload, "control_paradigm")
    phase = _val(payload, "temporal_phase")
    autonomy = _val(payload, "autonomy_level") or AUTONOMY_DEFAULT
    addresses = _val(payload, "addresses_failure_modes") or []

    if paradigm not in PARADIGM:
        log.warning("id=%s: paradigm '%s' invalid; skip", cand["id"], paradigm)
        return None
    if phase not in PHASE:
        log.warning("id=%s: phase '%s' invalid; skip", cand["id"], phase)
        return None
    if autonomy not in AUTONOMY:
        autonomy = AUTONOMY_DEFAULT
    addresses = [a for a in addresses if a in FAILURE_MODES]
    if not addresses:
        log.warning("id=%s: no valid addresses_failure_modes; skip", cand["id"])
        return None

    source_url = cand["source_url"]
    raw = _load_raw_json(source_url)

    # Required fields
    tool_id = (_val(payload, "proposed_id") or cand.get("proposed_id") or "").strip()
    if not tool_id:
        return None
    name = (_val(payload, "name") or cand.get("name") or tool_id).strip()
    tagline = _val(payload, "tagline") or _github_field(raw, "description") or ""
    tagline = (tagline or "")[:140]
    description = (
        _val(payload, "description") or _github_field(raw, "description") or tagline
    )
    license_ = (
        _val(payload, "license_spdx")
        or _github_field(raw, "license", "spdx_id")
        or "NOASSERTION"
    )
    if license_ in (None, "NOASSERTION", ""):
        license_ = "NOASSERTION"

    first_released = _github_field(raw, "created_at")
    first_released = (
        first_released[:10] if isinstance(first_released, str) else str(date.today())
    )
    last_updated = _github_field(raw, "pushed_at")
    last_updated = last_updated[:10] if isinstance(last_updated, str) else None
    stars = _github_field(raw, "stargazers_count") or 0

    nlp_tags = cand.get("nlp_tags") or {}
    rerank_score = nlp_tags.get("rerank_score")
    overall_conf = ext.get("overall_confidence")

    # Build YAML by hand (no YAML library round-trip to keep formatting predictable).
    lines = [
        f"id: {tool_id}",
        f"name: {_yaml_str(name)}",
        f"tagline: {_yaml_str(tagline)}",
        f"description: {_yaml_str(description)}",
        f"first_released: '{first_released}'",
    ]
    if last_updated:
        lines.append(f"last_updated: '{last_updated}'")
    lines.extend(
        [
            "maturity_status: experimental",
            f"repository_url: {source_url}",
            f"license: {_yaml_str(license_)}",
            f"control_paradigm: {paradigm}",
            f"temporal_phase: {phase}",
            f"autonomy_level: {autonomy}",
            "addresses_failure_modes:",
        ]
    )
    for fm in addresses:
        lines.append(f"  - {fm}")
    if stars:
        lines.append(f"stars: {int(stars)}")
        lines.append(f"stars_updated_at: '{date.today().isoformat()}'")

    lines.append("inclusion_rationale: >")
    lines.append(
        f"  Graduated from pipeline candidate id={cand['id']} (Kimi-K2.5 extraction,"
    )
    lines.append(
        f"  overall_confidence={overall_conf}, rerank_score={rerank_score}). Pending human"
    )
    lines.append(
        "  review of MECE facet placement; autonomy_level defaulted to fully_autonomous if"
    )
    lines.append("  Kimi declined to assign.")

    # Provenance
    lines.append("provenance:")
    lines.append("  source: pipeline-v0.1")
    lines.append(f"  ingested_at: '{date.today().isoformat()}'")
    lines.append("  extractor_model: Kimi-K2.5")
    if overall_conf is not None:
        lines.append(f"  extractor_confidence: {float(overall_conf):.2f}")
    if rerank_score is not None:
        lines.append(f"  rerank_score: {float(rerank_score):.3f}")
    lines.append(f"  candidate_id: {int(cand['id'])}")

    return "\n".join(lines) + "\n"


def _yaml_str(s: str) -> str:
    """Render a scalar string — quote if it contains special chars."""
    if not s:
        return '""'
    if (
        any(c in s for c in (":", "#", "[", "]", "{", "}", "|", ">", "\n", '"'))
        or s.strip() != s
    ):
        return json.dumps(s, ensure_ascii=False)  # JSON strings are valid YAML strings
    return s


def main(argv=None) -> int:
    configure_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True, help="comma-separated candidate_tool ids")
    ap.add_argument("--force", action="store_true", help="overwrite existing YAMLs")
    args = ap.parse_args(argv)

    ids = [int(x) for x in args.ids.split(",") if x.strip()]
    written, skipped = [], []

    with db.get_conn() as conn:
        from psycopg.rows import dict_row

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM candidate_tools WHERE id = ANY(%s)",
                (ids,),
            )
            rows = {r["id"]: r for r in cur.fetchall()}

    for cid in ids:
        cand = rows.get(cid)
        if not cand:
            log.warning("id=%s: not found", cid)
            skipped.append((cid, "not-found"))
            continue
        yaml_text = build_tool_yaml(cand)
        if yaml_text is None:
            skipped.append((cid, "missing-facets"))
            continue
        tool_id = yaml_text.split("\n", 1)[0].removeprefix("id: ").strip()
        out = DATA_TOOLS / f"{tool_id}.yml"
        if out.exists() and not args.force:
            log.warning("id=%s: %s already exists; skip", cid, out.name)
            skipped.append((cid, "exists"))
            continue
        out.write_text(yaml_text)
        written.append((cid, tool_id))

    print(f"wrote: {len(written)}, skipped: {len(skipped)}")
    for cid, tid in written:
        print(f"  ✓ id={cid} -> data/tools/{tid}.yml")
    for cid, reason in skipped:
        print(f"  - id={cid}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
