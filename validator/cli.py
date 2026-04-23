#!/usr/bin/env python3
"""SAICA-KG validator.

Validates YAML data files by parsing them into the canonical Pydantic models
in :mod:`pipeline.models`, then enforcing cross-node invariants (MECE axis
usage, citation requirements, staleness flags, supersession acyclicity,
symmetric composes_with).

This is a refactor from jsonschema-driven validation: Pydantic is now the
single source of truth; the JSON Schemas under ``schema/*.json`` are
generated from the same models. Error messages mirror the jsonschema format
(``[kind] filename :: path — message``) but surface Pydantic's richer per-
field reasons where available.

Usage:
    python validator/cli.py            # validate everything
    python validator/cli.py --strict   # fail on warnings
    python validator/cli.py --only tools,failure_modes
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print(
        "Missing dependency: pyyaml. Install with: pip install pyyaml pydantic",
        file=sys.stderr,
    )
    sys.exit(2)

try:
    from pydantic import ValidationError
except ImportError:
    print(
        "Missing dependency: pydantic. Install with: pip install pyyaml pydantic",
        file=sys.stderr,
    )
    sys.exit(2)


REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
MANIFEST_PATH = DATA_DIR / "MANIFEST.json"

# Ensure the repo root is importable whether this script is invoked directly
# (``python validator/cli.py``) or as a module (``python -m validator.cli``).
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline.models import NODE_MODELS  # noqa: E402

STALE_AT_RISK_DAYS = 365  # force at_risk below this threshold (see §7 invariants)

# Closed-set FailureMode ids permitted on Tool.addresses_failure_modes. Must
# mirror pipeline.models.FailureModeId.
KNOWN_FAILURE_MODE_IDS = {
    "fabrication",
    "obsolescence",
    "dependency_blindness",
    "logic_error",
    "security_vulnerability",
    "scope_creep",
    "context_pollution",
    "supply_chain_attack",
}


def _coerce(value: Any) -> Any:
    """Coerce ``datetime.date`` values back to ISO strings so Pydantic's
    YAML output matches its JSON-input expectations. Also recurses into
    dicts/lists.
    """
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
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level must be a mapping")
    return _coerce(data)


def iter_nodes(kind: str) -> list[tuple[Path, dict[str, Any]]]:
    subdir = DATA_DIR / kind
    if not subdir.exists():
        return []
    out = []
    for p in sorted(subdir.glob("*.yml")) + sorted(subdir.glob("*.yaml")):
        out.append((p, load_yaml(p)))
    return out


def _fmt_loc(loc: tuple[Any, ...]) -> str:
    return "/".join(str(x) for x in loc) or "<root>"


def _format_pydantic_error(err: dict[str, Any]) -> str:
    """Format one entry from :meth:`ValidationError.errors()`.

    Pydantic produces richer error types than jsonschema (``extra_forbidden``,
    ``missing``, ``string_pattern_mismatch``, ``enum``, etc.). We reshape
    these to be at least as clear as the jsonschema text that used to be
    emitted here.
    """
    etype = err.get("type", "")
    msg = err.get("msg", "")
    ctx = err.get("ctx") or {}
    inp = err.get("input")

    if etype == "extra_forbidden":
        return f"Additional properties are not allowed ('{err['loc'][-1]}' was unexpected)"
    if etype == "missing":
        return f"'{err['loc'][-1]}' is a required property"
    if etype == "enum":
        expected = ctx.get("expected", "")
        return f"{inp!r} is not one of {expected}"
    if etype == "string_pattern_mismatch":
        pat = ctx.get("pattern", "")
        return f"{inp!r} does not match pattern {pat!r}"
    if etype.startswith("string_too_short"):
        return msg
    if etype.startswith("too_short"):
        return msg
    if etype in {"greater_than_equal", "less_than_equal"}:
        return msg
    return msg


def schema_errors(kind: str) -> list[str]:
    model = NODE_MODELS[kind]
    errors: list[str] = []
    for path, node in iter_nodes(kind):
        try:
            model.model_validate(node)
        except ValidationError as exc:
            for e in exc.errors():
                loc = _fmt_loc(e.get("loc", ()))
                msg = _format_pydantic_error(e)
                errors.append(f"[{kind}] {path.name} :: {loc} — {msg}")
        except Exception as exc:  # pragma: no cover — safety net
            errors.append(f"[{kind}] {path.name} :: <root> — {exc}")
    return errors


def cross_invariants(warn: list[str], err: list[str]) -> None:
    """Cross-node invariants (§7 of DESIGN.md).

    These live in Python either way — they span multiple YAML files and
    cannot be expressed in a per-file JSON Schema.
    """
    tools = {n["id"]: n for _, n in iter_nodes("tools")}
    modes = {n["id"]: n for _, n in iter_nodes("failure_modes")}
    papers = {n["id"]: n for _, n in iter_nodes("papers")}
    taxonomies = {n["id"]: n for _, n in iter_nodes("taxonomies")}
    crosswalks = {n["id"]: n for _, n in iter_nodes("crosswalks")}

    for mode_id, mode in modes.items():
        for pid in mode.get("prior_work", []):
            if pid not in papers:
                err.append(f"[failure_modes] {mode_id} cites missing paper '{pid}'")
        for cw in mode.get("crosswalks", []) or []:
            tax_id = cw.get("taxonomy")
            if tax_id not in taxonomies:
                err.append(
                    f"[failure_modes] {mode_id} crosswalk references missing taxonomy"
                    f" '{tax_id}'"
                )
                continue
            # Inline FailureMode crosswalks: external_id must be a category of
            # the referenced taxonomy.
            known_ext_ids = {
                c["external_id"]
                for c in taxonomies[tax_id].get("categories", []) or []
                if isinstance(c, dict) and "external_id" in c
            }
            ext = cw.get("external_id")
            if ext is not None and ext not in known_ext_ids:
                err.append(
                    f"[failure_modes] {mode_id} crosswalk external_id '{ext}' "
                    f"is not a category of taxonomy '{tax_id}'"
                )

    # Standalone Crosswalk nodes: each mapping's external_id must exist in
    # the target taxonomy's categories.
    for cw_id, cw in crosswalks.items():
        tax_id = cw.get("taxonomy")
        if tax_id not in taxonomies:
            err.append(
                f"[crosswalks] {cw_id} references missing taxonomy '{tax_id}'"
            )
            continue
        known_ext_ids = {
            c["external_id"]
            for c in taxonomies[tax_id].get("categories", []) or []
            if isinstance(c, dict) and "external_id" in c
        }
        for m in cw.get("mappings", []) or []:
            if not isinstance(m, dict):
                continue
            ext = m.get("external_id")
            if ext is None:
                continue
            if ext not in known_ext_ids:
                err.append(
                    f"[crosswalks] {cw_id} mapping saica={m.get('saica_value')} -> "
                    f"external={ext} not a category of taxonomy '{tax_id}'"
                )

    known_modes = set(modes) | KNOWN_FAILURE_MODE_IDS

    composes: dict[str, set[str]] = defaultdict(set)
    supersedes_edges: list[tuple[str, str]] = []

    for tid, tool in tools.items():
        for pid in tool.get("cited_in", []) + tool.get("documented_in", []):
            if pid not in papers:
                err.append(f"[tools] {tid} cites missing paper '{pid}'")
        for fm in tool.get("addresses_failure_modes", []):
            if fm not in known_modes:
                err.append(f"[tools] {tid} addresses unknown FailureMode '{fm}'")
        for other in tool.get("composes_with", []) or []:
            composes[tid].add(other)
            if other not in tools:
                err.append(f"[tools] {tid} composes_with missing tool '{other}'")
        for succ in tool.get("supersedes", []) or []:
            supersedes_edges.append((tid, succ))
            if succ not in tools:
                err.append(f"[tools] {tid} supersedes missing tool '{succ}'")

        if tool.get("last_updated"):
            try:
                last = dt.date.fromisoformat(str(tool["last_updated"]))
                age = (dt.date.today() - last).days
                if (
                    age > STALE_AT_RISK_DAYS
                    and tool.get("maturity_status")
                    not in ("at_risk", "deprecated", "abandoned")
                ):
                    warn.append(
                        f"[tools] {tid}: last_updated is {age} days old; should be at_risk"
                    )
            except ValueError:
                err.append(
                    f"[tools] {tid}: last_updated '{tool['last_updated']}' is not ISO-8601 date"
                )

    for a, bs in composes.items():
        for b in bs:
            if b in tools and a not in composes.get(b, set()):
                warn.append(
                    f"[tools] composes_with is not symmetric: {a} → {b} but not {b} → {a}"
                )

    if has_cycle(supersedes_edges):
        err.append("[tools] supersedes graph contains a cycle")

    for tid, tool in tools.items():
        if not tool.get("signed_manifest") and not tool.get("security_notes"):
            warn.append(f"[tools] {tid}: neither signed_manifest nor security_notes populated")
        if not tool.get("cited_in"):
            warn.append(f"[tools] {tid}: no cited_in papers")

    mitigated: dict[str, set[str]] = defaultdict(set)
    for tid, tool in tools.items():
        for fm in tool.get("addresses_failure_modes", []):
            mitigated[fm].add(tid)
    for mode_id in modes:
        if len(mitigated[mode_id]) < 3:
            warn.append(
                f"[failure_modes] {mode_id}: only {len(mitigated[mode_id])} mitigating tools"
                f" (under-covered)"
            )

    # ID-immutability lock: every id in the committed MANIFEST.json must
    # still exist in the YAML corpus. A missing id means someone renamed
    # or deleted a node, breaking external citations.
    _check_manifest_lock(err, tools, modes, papers, taxonomies, crosswalks)


def _check_manifest_lock(
    err: list[str],
    tools: dict[str, Any],
    modes: dict[str, Any],
    papers: dict[str, Any],
    taxonomies: dict[str, Any],
    crosswalks: dict[str, Any],
) -> None:
    """If ``data/MANIFEST.json`` exists, every id it declares must still be
    present in the current corpus. This is the "external citations stay
    honest" guarantee — a rename shows up as ``old_id`` missing even if
    ``new_id`` has been added. The deeper contents of the manifest (count
    totals, URLs) are enforced by ``validator/generate_manifest.py --check``
    in CI; here we only check id membership so local ``validator/cli.py``
    runs stay useful even when the manifest is one commit behind.
    """
    if not MANIFEST_PATH.exists():
        return
    try:
        manifest = json.loads(MANIFEST_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        err.append(f"[manifest] data/MANIFEST.json is unreadable: {exc}")
        return

    declared = manifest.get("ids", {})
    current = {
        "tools": set(tools.keys()),
        "failure_modes": set(modes.keys()),
        "papers": set(papers.keys()),
        "taxonomies": set(taxonomies.keys()),
        "crosswalks": set(crosswalks.keys()),
    }
    for kind, live_ids in current.items():
        entry = declared.get(kind)
        if isinstance(entry, dict):
            declared_ids = set(entry.keys())
        elif isinstance(entry, list):
            declared_ids = set(entry)
        else:
            declared_ids = set()
        missing = declared_ids - live_ids
        for mid in sorted(missing):
            err.append(
                f"[manifest] {kind} id '{mid}' is in MANIFEST.json but no longer "
                f"present in data/{kind}/ — renames and deletions break external "
                f"citations. Restore the id or run "
                f"`python -m validator.generate_manifest` after confirming the "
                f"change is intentional."
            )


def has_cycle(edges: list[tuple[str, str]]) -> bool:
    graph: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        graph[a].append(b)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(int)

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for n in graph[node]:
            if color[n] == GRAY:
                return True
            if color[n] == WHITE and dfs(n):
                return True
        color[node] = BLACK
        return False

    return any(color[n] == WHITE and dfs(n) for n in list(graph))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    ap.add_argument(
        "--only", default="", help="Comma-separated node kinds to validate"
    )
    args = ap.parse_args()

    kinds = (
        list(NODE_MODELS.keys())
        if not args.only
        else [k.strip() for k in args.only.split(",")]
    )
    errors: list[str] = []
    warnings: list[str] = []

    for kind in kinds:
        if kind not in NODE_MODELS:
            errors.append(f"unknown kind '{kind}'")
            continue
        errors.extend(schema_errors(kind))

    cross_invariants(warnings, errors)

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)

    total_nodes = sum(len(iter_nodes(k)) for k in NODE_MODELS)
    print(f"\nValidated {total_nodes} nodes: {len(errors)} errors, {len(warnings)} warnings")

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
