"""Generate ``data/MANIFEST.json`` from the current YAML corpus.

The manifest is a committed, diff-reviewable snapshot of every canonical
node id in the knowledge graph, plus (for Tools) their canonical URL. It
serves two purposes:

1. **ID immutability lock.** CI re-runs this in ``--check`` mode on every
   PR. If a committed id disappears or gets silently renamed, the check
   fails — external citations stay honest. Rewriting the manifest is not a
   way around the lock: the write refuses to drop an id that has no entry
   in ``data/TOMBSTONES.yml``.
2. **Machine-readable index.** Today its readers are the validator, the two
   Markdown generators (for ``kg_version``) and a test; anything else can
   load one JSON file instead of walking ``data/``.

CLI:

.. code-block:: shell

    python -m validator.generate_manifest          # rewrite data/MANIFEST.json
    python -m validator.generate_manifest --check  # CI: diff; exit 1 on drift
    python -m validator.generate_manifest --check --manifest /tmp/m.json
    python -m validator.generate_manifest --data-dir /tmp/copy/data --manifest /tmp/m.json

``--manifest`` and ``--data-dir`` exist so that tests and trial runs never
touch the tracked ``data/MANIFEST.json``.
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


def _iter_yaml_files(kind: str, data_dir: Path | None = None) -> list[Path]:
    subdir = (data_dir or DATA_DIR) / kind
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


def _collect_ids(
    kind: str, data_dir: Path | None = None
) -> list[str] | dict[str, str | None]:
    entries = []
    for path in _iter_yaml_files(kind, data_dir):
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


def build_manifest(
    now: dt.datetime | None = None, data_dir: Path | None = None
) -> dict[str, Any]:
    """Return the in-memory manifest dict, without writing it to disk."""
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)

    ids: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for kind in ALL_KINDS:
        collected = _collect_ids(kind, data_dir)
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


_TOMBSTONE_KINDS = {
    "tool": "tools",
    "failure_mode": "failure_modes",
    "paper": "papers",
    "taxonomy": "taxonomies",
    "crosswalk": "crosswalks",
    "incident": "incidents",
    "recipe": "recipes",
}


def tombstoned_ids(data_dir: Path | None = None) -> dict[str, set[str]]:
    """Ids recorded as removed in ``TOMBSTONES.yml``, per node kind. A file
    that is missing or unreadable gives no ids (the validator reports it)."""
    out: dict[str, set[str]] = {kind: set() for kind in ALL_KINDS}
    path = (data_dir or DATA_DIR) / "TOMBSTONES.yml"
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return out
    entries = doc.get("tombstones") if isinstance(doc, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        kind = _TOMBSTONE_KINDS.get(str(entry.get("kind")))
        if kind and isinstance(entry.get("id"), str):
            out[kind].add(entry["id"])
    return out


def removed_ids(
    committed: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, list[str]]:
    """Ids the committed manifest lists that the current corpus lacks."""
    out: dict[str, list[str]] = {}
    for kind in ALL_KINDS:
        old = (committed.get("ids") or {}).get(kind) or []
        new = manifest["ids"][kind]
        gone = sorted(set(old) - set(new))
        if gone:
            out[kind] = gone
    return out


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Write or check the manifest of node ids (data/MANIFEST.json)."
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Compare regenerated manifest to committed file; exit 1 on mismatch.",
    )
    ap.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Manifest file to write or check (default: <data-dir>/MANIFEST.json).",
    )
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Node files to read (default: the repository's data/).",
    )
    args = ap.parse_args(argv)

    data_dir = args.data_dir.resolve() if args.data_dir else DATA_DIR
    if args.manifest is not None:
        manifest_path = args.manifest.resolve()
    elif args.data_dir is not None:
        manifest_path = data_dir / "MANIFEST.json"
    else:
        manifest_path = MANIFEST_PATH

    manifest = build_manifest(data_dir=data_dir)
    text = format_manifest(manifest)
    tombstones = tombstoned_ids(data_dir)

    committed: dict[str, Any] | None = None
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text())
            committed = loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError as exc:
            if args.check:
                print(f"manifest is not valid JSON: {exc}", file=sys.stderr)
                return 1

    if args.check:
        if committed is None:
            print(
                f"manifest missing: {_display(manifest_path)}\n"
                "Run `python -m validator.generate_manifest` and commit.",
                file=sys.stderr,
            )
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
                recorded = [m for m in missing if m in tombstones[kind]]
                silent = [m for m in missing if m not in tombstones[kind]]
                if recorded:
                    print(
                        f"  [{kind}] removed, recorded in TOMBSTONES.yml:"
                        f" {', '.join(recorded)}",
                        file=sys.stderr,
                    )
                if silent:
                    print(
                        f"  [{kind}] removed WITHOUT a tombstone (restore the node"
                        f" or record the removal): {', '.join(silent)}",
                        file=sys.stderr,
                    )
                if added:
                    print(f"  [{kind}] added:   {', '.join(added)}", file=sys.stderr)
            return 1
        print(f"manifest OK ({sum(manifest['counts'].values())} ids)")
        return 0

    # Write mode. The manifest is the lock on node ids, so rewriting it may
    # not quietly drop an id: a removed node needs a tombstone first.
    if committed is not None:
        silent = {
            kind: [i for i in gone if i not in tombstones[kind]]
            for kind, gone in removed_ids(committed, manifest).items()
        }
        silent = {kind: gone for kind, gone in silent.items() if gone}
        if silent:
            print(
                "refusing to rewrite the manifest: these ids are in it but no"
                " longer in the data, and have no entry in TOMBSTONES.yml:",
                file=sys.stderr,
            )
            for kind, gone in silent.items():
                print(f"  [{kind}] {', '.join(gone)}", file=sys.stderr)
            print(
                "Restore the node files, or add each id to data/TOMBSTONES.yml"
                " (id, kind, removed_on, reason) and run again.",
                file=sys.stderr,
            )
            return 1

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(text)
    print(f"wrote {_display(manifest_path)} ({sum(manifest['counts'].values())} ids)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
