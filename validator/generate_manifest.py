"""Generate ``data/MANIFEST.json`` from the current YAML corpus.

The manifest is a committed, diff-reviewable snapshot of every canonical
node id in the knowledge graph, plus (for Tools) their canonical URL. It
serves two purposes:

1. **ID immutability lock.** CI re-runs this in ``--check`` mode on every
   PR. If a committed id disappears or gets silently renamed, the check
   fails — external citations stay honest.
2. **Machine-readable index for downstream Tools.** Consumers (the Next.js
   site, the MCP server, external integrations) can load a single JSON
   file instead of walking ``data/`` themselves.

CLI:

.. code-block:: shell

    python -m validator.generate_manifest          # rewrite data/MANIFEST.json
    python -m validator.generate_manifest --check  # CI: diff; exit 1 on drift
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
MANIFEST_PATH = DATA_DIR / "MANIFEST.json"

# Ensure the repo root is importable whether invoked directly or via -m.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline.dedup import canonical_github_url  # noqa: E402

# Node kinds in the order they should appear in the manifest. Tools are a
# mapping (id -> url); everything else is a sorted list of ids.
NODE_KINDS_LIST = (
    "failure_modes",
    "papers",
    "taxonomies",
    "crosswalks",
    "incidents",
    "recipes",
)
ALL_KINDS = ("tools",) + NODE_KINDS_LIST


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level must be a mapping")
    return data


def _iter_yaml_files(kind: str) -> list[Path]:
    subdir = DATA_DIR / kind
    if not subdir.exists():
        return []
    return sorted(list(subdir.glob("*.yml")) + list(subdir.glob("*.yaml")))


def _tool_url(node: dict[str, Any]) -> str | None:
    """Canonical URL for a Tool: prefer canonical github URL, fall back to
    documentation_url, else None.
    """
    repo = node.get("repository_url")
    if isinstance(repo, str) and repo.strip():
        canon = canonical_github_url(repo)
        if canon:
            return canon
    doc = node.get("documentation_url")
    if isinstance(doc, str) and doc.strip():
        return doc.strip()
    return None


def _collect_ids(kind: str) -> list[str] | dict[str, str | None]:
    entries = []
    for path in _iter_yaml_files(kind):
        node = _load_yaml(path)
        node_id = node.get("id")
        if not isinstance(node_id, str):
            raise ValueError(f"{path}: missing or non-string 'id'")
        entries.append((node_id, node))

    if kind == "tools":
        # Sorted by id; values are canonical URLs (or None).
        return {
            node_id: _tool_url(node)
            for node_id, node in sorted(entries, key=lambda t: t[0])
        }
    return sorted(node_id for node_id, _ in entries)


def _kg_version(now: dt.datetime | None = None) -> str:
    """Year-month string. The KG has no independent semver; tie it to the
    month the manifest was regenerated so it monotonically advances."""
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    return f"{now.year:04d}.{now.month:02d}"


def build_manifest(now: dt.datetime | None = None) -> dict[str, Any]:
    """Return the in-memory manifest dict, without writing it to disk."""
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)

    ids: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for kind in ALL_KINDS:
        collected = _collect_ids(kind)
        ids[kind] = collected
        counts[kind] = len(collected)

    return {
        "generated_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "kg_version": _kg_version(now),
        "counts": counts,
        "ids": ids,
    }


def format_manifest(manifest: dict[str, Any]) -> str:
    """Serialize the manifest deterministically (trailing newline, indent=2)."""
    return json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def _stable_for_diff(manifest: dict[str, Any]) -> dict[str, Any]:
    """Strip the time-varying fields so ``--check`` compares only the part
    that must stay stable between runs (counts + ids)."""
    return {"counts": manifest["counts"], "ids": manifest["ids"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Compare regenerated manifest to committed file; exit 1 on mismatch.",
    )
    args = ap.parse_args()

    manifest = build_manifest()
    text = format_manifest(manifest)

    if args.check:
        if not MANIFEST_PATH.exists():
            print(
                f"manifest missing: {MANIFEST_PATH.relative_to(REPO)}\n"
                "Run `python -m validator.generate_manifest` and commit.",
                file=sys.stderr,
            )
            return 1
        try:
            committed = json.loads(MANIFEST_PATH.read_text())
        except json.JSONDecodeError as exc:
            print(f"manifest is not valid JSON: {exc}", file=sys.stderr)
            return 1

        if _stable_for_diff(manifest) != _stable_for_diff(committed):
            print(
                "MANIFEST.json drift detected.\n"
                "Run `python -m validator.generate_manifest` and commit the result.",
                file=sys.stderr,
            )
            # Surface a minimal diff so reviewers can triage quickly.
            for kind in ALL_KINDS:
                committed_kind = committed.get("ids", {}).get(kind)
                current_kind = manifest["ids"][kind]
                if committed_kind == current_kind:
                    continue
                if isinstance(current_kind, dict):
                    committed_keys = set((committed_kind or {}).keys())
                    current_keys = set(current_kind.keys())
                else:
                    committed_keys = set(committed_kind or [])
                    current_keys = set(current_kind)
                missing = sorted(committed_keys - current_keys)
                added = sorted(current_keys - committed_keys)
                if missing:
                    print(f"  [{kind}] removed: {', '.join(missing)}", file=sys.stderr)
                if added:
                    print(f"  [{kind}] added:   {', '.join(added)}", file=sys.stderr)
            return 1
        print(f"manifest OK ({sum(manifest['counts'].values())} ids)")
        return 0

    MANIFEST_PATH.write_text(text)
    print(f"wrote {MANIFEST_PATH.relative_to(REPO)} ({sum(manifest['counts'].values())} ids)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
