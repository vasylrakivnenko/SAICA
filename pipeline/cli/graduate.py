"""CLI: human-gated graduation from Postgres candidates to ``data/<kind>/<id>.yml``.

The LLM never writes YAML. This CLI — invoked by a human reviewer — is the
only path from Postgres into the canonical ``data/`` tree.

Flow (per candidate):

1. Load ``candidate_*.extracted.payload`` (must have been produced by the
   extract CLI; otherwise refuse).
2. Walk each ConfidenceField:
   - If confidence >= threshold (default 0.85 or per ``--auto-accept-above``):
     accept as-is.
   - Else: interactive prompt — accept / reject / edit.
3. Compose the YAML with ``# REVIEW REQUIRED`` comments on any field that
   ended up rejected or low-confidence-not-accepted.
4. Run ``validator/cli.py --only <kind>`` on the new file and echo any
   schema errors.
5. Mark the candidate ``status='graduated', graduated_to=<path>``.

Examples::

    python -m pipeline.cli.graduate tool 42
    python -m pipeline.cli.graduate tool 42 --auto-accept-above 0.85
    python -m pipeline.cli.graduate tool 42 --dry-run
    python -m pipeline.cli.graduate paper 7 --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from psycopg.rows import dict_row

try:
    from ruamel.yaml import YAML  # type: ignore
    from ruamel.yaml.comments import CommentedMap, CommentedSeq  # type: ignore
except ImportError:
    print(
        "Missing dependency: ruamel.yaml. Install with: pip install ruamel.yaml",
        file=sys.stderr,
    )
    sys.exit(2)

from pipeline import db


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
VALIDATOR_SCRIPT = REPO_ROOT / "validator" / "cli.py"

DEFAULT_ACCEPT_THRESHOLD = 0.85  # used by field-level accept check
AUTO_MODE_DEFAULT = 0.85         # used by --auto-accept-above default

_KIND_TABLE = {"tool": "candidate_tools", "paper": "candidate_papers"}
_KIND_DATA_DIR = {"tool": "tools", "paper": "papers"}


# ---------------------------------------------------------------------------
# Field specs — mirrors schemas.py, with hints for the YAML layout
# ---------------------------------------------------------------------------

# Each tuple: (schema_field_name, yaml_key, is_required, comment)
TOOL_FIELDS = [
    ("proposed_id",             "id",                  True,  None),
    ("name",                    "name",                True,  None),
    ("tagline",                 "tagline",             False, None),
    ("description",             "description",         True,  None),
    ("repository_url",          "repository_url",      False, None),
    ("license_spdx",            "license",             True,  None),
    ("control_paradigm",        "control_paradigm",    True,
     "one of prevention|detection|correction|recovery"),
    ("temporal_phase",          "temporal_phase",      True,
     "one of pre_generation|in_generation|post_generation"),
    ("autonomy_level",          "autonomy_level",      True,
     "one of fully_autonomous|graduated_hitl|full_hitl"),
    ("addresses_failure_modes", "addresses_failure_modes", True,
     "subset of fabrication|obsolescence|dependency_blindness|logic_error|"
     "security_vulnerability|scope_creep|context_pollution|supply_chain_attack"),
    ("locus_of_control",        "locus_of_control",    False,
     "subset of model|prompt|context|environment|human"),
    ("inclusion_rationale",     "inclusion_rationale", False, None),
]

PAPER_FIELDS = [
    ("title",          "title",          True,  None),
    ("authors",        "authors",        True,  None),
    ("year",           "year",           True,  "integer"),
    ("venue",          "venue",          False, None),
    ("doi",            "doi",            False, None),
    ("arxiv_id",       "arxiv_id",       False, None),
    ("tldr",           "tldr",           False, None),
    ("relevance_tags", "relevance_tags", False, None),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _fetch_candidate(kind: str, candidate_id: int) -> Optional[dict]:
    table = _KIND_TABLE[kind]
    sql = f"SELECT * FROM {table} WHERE id = %s"
    with db.get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (candidate_id,))
        return cur.fetchone()


def _payload_from_row(row: dict) -> Optional[dict]:
    extracted = row.get("extracted") or {}
    if not isinstance(extracted, dict):
        return None
    payload = extracted.get("payload")
    if not isinstance(payload, dict):
        return None
    return payload


def _field_triple(payload: dict, field: str) -> tuple[Any, float, list[str]]:
    """Return (value, confidence, evidence) from a payload field, safely."""
    f = payload.get(field) or {}
    if not isinstance(f, dict):
        return None, 0.0, []
    return f.get("value"), float(f.get("confidence") or 0.0), list(f.get("evidence") or [])


def _prompt_yn(prompt: str, default: str = "a") -> str:
    """Return one of 'a' (accept), 'r' (reject), 'e' (edit)."""
    while True:
        ans = input(prompt).strip().lower()
        if not ans:
            ans = default
        if ans in ("a", "accept"):
            return "a"
        if ans in ("r", "reject"):
            return "r"
        if ans in ("e", "edit"):
            return "e"
        print("  please answer accept (a), reject (r), or edit (e)")


def _coerce_edit(raw: str, prior_value: Any) -> Any:
    """Parse user-entered string, auto-detect list/JSON vs scalar."""
    raw = raw.strip()
    if raw == "":
        return None
    # If prior value was a list, accept comma-sep or JSON list.
    if isinstance(prior_value, list) or raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return [x.strip() for x in raw.split(",") if x.strip()]
    # Try JSON scalar for integers / booleans.
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, (int, float, bool)):
            return parsed
    except json.JSONDecodeError:
        pass
    return raw


# ---------------------------------------------------------------------------
# Field resolution (auto / interactive)
# ---------------------------------------------------------------------------


class Decision:
    """Outcome of resolving one field."""

    __slots__ = ("value", "confidence", "accepted", "reason")

    def __init__(self, value: Any, confidence: float, accepted: bool, reason: str = ""):
        self.value = value
        self.confidence = confidence
        self.accepted = accepted
        self.reason = reason


def _resolve_field(
    field: str,
    yaml_key: str,
    payload: dict,
    *,
    auto_threshold: float,
    interactive: bool,
) -> Decision:
    value, conf, evidence = _field_triple(payload, field)
    if conf >= auto_threshold:
        return Decision(value, conf, accepted=True)
    if not interactive:
        return Decision(
            value, conf, accepted=False, reason=f"confidence {conf:.2f} < {auto_threshold}"
        )
    # Interactive path.
    print(f"\n--- {yaml_key} ---")
    print(f"  value      : {value!r}")
    print(f"  confidence : {conf:.2f}")
    for ev in evidence[:3]:
        print(f"  evidence   : {ev!r}")
    resp = _prompt_yn(
        f"  [a]ccept / [r]eject / [e]dit? (default: a if conf>={auto_threshold} else r) ",
        default="a" if conf >= auto_threshold else "r",
    )
    if resp == "a":
        return Decision(value, conf, accepted=True)
    if resp == "r":
        return Decision(value, conf, accepted=False, reason="reviewer rejected")
    # edit
    raw = input(f"  new value for {yaml_key}: ")
    new_value = _coerce_edit(raw, value)
    return Decision(new_value, 1.0, accepted=True, reason="reviewer edited")


# ---------------------------------------------------------------------------
# YAML composition
# ---------------------------------------------------------------------------


def _emit_review_required(doc: CommentedMap, yaml_key: str, decision: Decision, hint: Optional[str]) -> None:
    """Write a REVIEW-REQUIRED placeholder for a rejected/low-conf field."""
    prior = decision.value
    if isinstance(prior, list):
        placeholder = CommentedSeq()
    else:
        placeholder = None
    doc[yaml_key] = placeholder if placeholder is not None else "REVIEW_REQUIRED"
    reason_bits = [f"reason={decision.reason or 'low confidence'}"]
    if decision.confidence is not None:
        reason_bits.append(f"conf={decision.confidence:.2f}")
    if hint:
        reason_bits.append(hint)
    doc.yaml_add_eol_comment(
        "REVIEW REQUIRED: " + "; ".join(reason_bits),
        yaml_key,
    )


def _build_tool_yaml(
    row: dict,
    payload: dict,
    decisions: dict[str, Decision],
    *,
    today: dt.date,
) -> tuple[str, CommentedMap]:
    tool_id = (
        decisions["proposed_id"].value
        if decisions["proposed_id"].accepted and isinstance(decisions["proposed_id"].value, str)
        else str(row.get("proposed_id") or "review-required")
    )
    doc: CommentedMap = CommentedMap()

    # id always goes in (required for validator to find the file); flag low-conf.
    doc["id"] = tool_id
    if not decisions["proposed_id"].accepted:
        doc.yaml_add_eol_comment(
            f"REVIEW REQUIRED: slug may be wrong (conf={decisions['proposed_id'].confidence:.2f})",
            "id",
        )

    for field, yaml_key, required, hint in TOOL_FIELDS:
        if yaml_key == "id":
            continue
        d = decisions[field]
        if d.accepted and d.value not in (None, "", []):
            doc[yaml_key] = d.value
        elif required:
            _emit_review_required(doc, yaml_key, d, hint)
        else:
            if d.accepted and d.value in (None, "", []):
                # Don't emit empty optional fields.
                continue
            _emit_review_required(doc, yaml_key, d, hint)

    # Mandatory scaffolding the schema requires but the LLM doesn't emit.
    doc["first_released"] = today.isoformat()
    doc.yaml_add_eol_comment(
        "REVIEW REQUIRED: confirm first_released (defaulted to today)",
        "first_released",
    )
    doc["maturity_status"] = "experimental"
    doc.yaml_add_eol_comment(
        "REVIEW REQUIRED: confirm maturity_status "
        "(one of experimental|stable|at_risk|deprecated|abandoned)",
        "maturity_status",
    )

    header = (
        f" Graduated from candidate_tools id={row['id']} on {today.isoformat()}\n"
        f" Source: {row.get('source_url') or '(unknown)'}\n"
        f" Overall LLM confidence: {payload.get('overall_confidence')}\n"
        f" REVIEW REQUIRED markers flag fields that need human attention before merge.\n"
    )
    doc.yaml_set_start_comment(header)
    return tool_id, doc


def _build_paper_yaml(
    row: dict,
    payload: dict,
    decisions: dict[str, Decision],
    *,
    today: dt.date,
) -> tuple[str, CommentedMap]:
    # Derive paper id — prefer doi -> arxiv -> slugified title.
    doi = decisions.get("doi")
    arxiv = decisions.get("arxiv_id")
    year_d = decisions.get("year")
    title_d = decisions.get("title")

    def _slug(s: str) -> str:
        import re
        s = s.lower().strip()
        s = re.sub(r"[^a-z0-9]+", "-", s)
        return re.sub(r"-+", "-", s).strip("-")

    paper_id = None
    if arxiv and arxiv.accepted and isinstance(arxiv.value, str) and arxiv.value:
        paper_id = f"arxiv-{_slug(arxiv.value)}"
    elif title_d and title_d.accepted and isinstance(title_d.value, str) and title_d.value:
        y = ""
        if year_d and year_d.accepted and year_d.value:
            y = f"{year_d.value}-"
        paper_id = _slug(f"{y}{title_d.value}")[:80].strip("-")
    paper_id = paper_id or f"candidate-{row['id']}"

    doc: CommentedMap = CommentedMap()
    doc["id"] = paper_id

    for field, yaml_key, required, hint in PAPER_FIELDS:
        d = decisions[field]
        value = d.value
        # Coerce year to int if it's a string digit.
        if yaml_key == "year" and isinstance(value, str) and value.isdigit():
            value = int(value)
        if d.accepted and value not in (None, "", []):
            doc[yaml_key] = value
        elif required:
            _emit_review_required(doc, yaml_key, d, hint)
        else:
            if d.accepted and value in (None, "", []):
                continue
            _emit_review_required(doc, yaml_key, d, hint)

    header = (
        f" Graduated from candidate_papers id={row['id']} on {today.isoformat()}\n"
        f" Source: {row.get('source_url') or '(unknown)'}\n"
        f" Overall LLM confidence: {payload.get('overall_confidence')}\n"
        f" REVIEW REQUIRED markers flag fields that need human attention before merge.\n"
    )
    doc.yaml_set_start_comment(header)
    return paper_id, doc


# ---------------------------------------------------------------------------
# Validator hop
# ---------------------------------------------------------------------------


def _run_validator(kind: str, yaml_path: Path) -> tuple[int, str]:
    """Invoke ``validator/cli.py --only <kind>`` and capture output."""
    only_arg = _KIND_DATA_DIR[kind]
    cmd = [sys.executable, str(VALIDATOR_SCRIPT), "--only", only_arg]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return 124, "validator timed out after 60s"
    output = (proc.stdout or "") + (proc.stderr or "")
    # Filter for lines mentioning this file, so the reviewer isn't drowned
    # in unrelated warnings from other YAML files.
    fname = yaml_path.name
    focused = [
        line for line in output.splitlines()
        if fname in line or line.startswith(("WARN", "ERROR")) is False
    ]
    if not any(fname in line for line in output.splitlines()):
        return proc.returncode, output
    return proc.returncode, "\n".join(focused)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _graduate(
    kind: str,
    candidate_id: int,
    *,
    auto_accept_above: float,
    dry_run: bool,
    reviewer: Optional[str],
) -> int:
    if kind not in _KIND_TABLE:
        print(f"unknown kind {kind!r}", file=sys.stderr)
        return 2

    row = _fetch_candidate(kind, candidate_id)
    if row is None:
        print(f"no {kind} candidate with id={candidate_id}", file=sys.stderr)
        return 2

    payload = _payload_from_row(row)
    if payload is None:
        print(
            f"candidate {kind} id={candidate_id} has no extraction payload"
            f" — run `python -m pipeline.cli.extract {kind} {candidate_id}` first",
            file=sys.stderr,
        )
        return 2

    fields = TOOL_FIELDS if kind == "tool" else PAPER_FIELDS
    # Interactive iff stdin is a TTY AND user did not pass the auto threshold.
    # --auto-accept-above on its own still runs interactive for below-threshold
    # fields; that's the documented behaviour of the flag.
    interactive = sys.stdin.isatty()

    decisions: dict[str, Decision] = {}
    for schema_field, yaml_key, _required, _hint in fields:
        decisions[schema_field] = _resolve_field(
            schema_field,
            yaml_key,
            payload,
            auto_threshold=auto_accept_above,
            interactive=interactive,
        )

    today = dt.date.today()
    if kind == "tool":
        slug, doc = _build_tool_yaml(row, payload, decisions, today=today)
    else:
        slug, doc = _build_paper_yaml(row, payload, decisions, today=today)

    subdir = DATA_DIR / _KIND_DATA_DIR[kind]
    target = subdir / f"{slug}.yml"

    yaml_text_buf = io.StringIO()
    _make_yaml().dump(doc, yaml_text_buf)
    yaml_text = yaml_text_buf.getvalue()

    if dry_run:
        print(f"--- {target} (dry-run) ---")
        sys.stdout.write(yaml_text)
        if not yaml_text.endswith("\n"):
            sys.stdout.write("\n")
        print(f"--- end {slug} ---")
        return 0

    if target.exists():
        print(
            f"refusing to overwrite existing file {target}; "
            f"move or delete it first",
            file=sys.stderr,
        )
        return 3

    subdir.mkdir(parents=True, exist_ok=True)
    with target.open("w") as fh:
        fh.write(yaml_text)
    print(f"wrote {target}")

    # Run validator.
    rc, output = _run_validator(kind, target)
    if output.strip():
        print("\n--- validator output (filtered to this file) ---")
        print(output)
    if rc != 0:
        print(
            f"\nvalidator exited {rc}; the file was still written. "
            f"Fix the REVIEW REQUIRED / errors before opening a PR.",
            file=sys.stderr,
        )

    # Mark as graduated.
    rel_path = str(target.relative_to(REPO_ROOT))
    db.update_candidate_status(
        _KIND_DATA_DIR[kind],  # 'tools' | 'papers'
        candidate_id,
        status="graduated",
        reviewer=reviewer or os.environ.get("USER"),
        graduated_to=rel_path,
    )
    print(f"marked candidate_{_KIND_DATA_DIR[kind]} id={candidate_id} as graduated")
    return 0


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pipeline.cli.graduate")
    sub = p.add_subparsers(dest="kind", required=True)
    for kind in ("tool", "paper"):
        sp = sub.add_parser(kind, help=f"Graduate a {kind} candidate to data/{kind}s/")
        sp.add_argument("candidate_id", type=int)
        sp.add_argument(
            "--auto-accept-above",
            type=float,
            default=AUTO_MODE_DEFAULT,
            metavar="THRESHOLD",
            help=(
                "Auto-accept fields with confidence >= THRESHOLD "
                f"(default {AUTO_MODE_DEFAULT}). Below-threshold fields are "
                "either prompted (TTY) or marked REVIEW REQUIRED."
            ),
        )
        sp.add_argument(
            "--dry-run",
            action="store_true",
            help="Print YAML to stdout without writing or touching Postgres.",
        )
        sp.add_argument(
            "--reviewer",
            default=None,
            help="Reviewer handle (defaults to $USER).",
        )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return _graduate(
        args.kind,
        args.candidate_id,
        auto_accept_above=args.auto_accept_above,
        dry_run=args.dry_run,
        reviewer=args.reviewer,
    )


if __name__ == "__main__":
    sys.exit(main())
