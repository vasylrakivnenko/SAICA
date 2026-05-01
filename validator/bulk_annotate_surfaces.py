#!/usr/bin/env python3
"""Bulk-annotate ``data/tools/*.yml`` with the ``integration_surfaces`` field.

Reuses the inference logic that ``pipeline.ask.context`` already uses at
retrieval time (regex heuristics + per-id overrides), so the first pass
is deterministic and reviewable via ``git diff``. Subsequent edits by
humans are preserved — the script only WRITES the field when it is
absent, unless ``--overwrite`` is passed.

Run:

    .venv/bin/python -m validator.bulk_annotate_surfaces           # write missing
    .venv/bin/python -m validator.bulk_annotate_surfaces --dry     # preview only
    .venv/bin/python -m validator.bulk_annotate_surfaces --overwrite  # also rewrite existing

Placement: inserted right after ``locus_of_control`` in field order, matching
the Tool model in ``pipeline.models``. If ``locus_of_control`` is missing,
falls back to insertion right after ``addresses_failure_modes``.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

# Make the repo importable whether invoked as a module or a script.
REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ruamel.yaml import YAML  # noqa: E402

from pipeline.ask.context import _detect_integration_surfaces  # noqa: E402

TOOLS_DIR = REPO / "data" / "tools"
ANCHOR_KEYS = ("locus_of_control", "addresses_failure_modes")


def _make_yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # do not wrap long lines
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _insert_after(doc, anchor: str, key: str, value) -> bool:
    """Insert ``key: value`` into a ruamel CommentedMap right after ``anchor``.

    Returns True if the insert succeeded. When ``anchor`` is missing the caller
    should try the next fallback.
    """
    if anchor not in doc:
        return False
    # ruamel's CommentedMap supports .insert(pos, key, value, comment=None).
    keys = list(doc.keys())
    pos = keys.index(anchor) + 1
    doc.insert(pos, key, value)
    return True


def annotate_file(
    path: Path, *, yaml: YAML, overwrite: bool
) -> tuple[str, list[str] | None]:
    """Annotate one tool file.

    Returns ``(action, surfaces)`` where action is one of:
        skipped_has_field | skipped_no_surfaces_detected | wrote | rewrote
    """
    with path.open("r", encoding="utf-8") as fh:
        doc = yaml.load(fh)

    if doc is None:
        return ("skipped_no_surfaces_detected", None)

    already = doc.get("integration_surfaces")
    if already and not overwrite:
        return ("skipped_has_field", list(already))

    surfaces = list(_detect_integration_surfaces(doc))
    if not surfaces:
        return ("skipped_no_surfaces_detected", None)

    if "integration_surfaces" in doc:
        doc["integration_surfaces"] = surfaces
        action = "rewrote"
    else:
        inserted = False
        for anchor in ANCHOR_KEYS:
            if _insert_after(doc, anchor, "integration_surfaces", surfaces):
                inserted = True
                break
        if not inserted:
            doc["integration_surfaces"] = surfaces
        action = "wrote"

    # Round-trip dump to string first so we can avoid rewriting if no change.
    buf = io.StringIO()
    yaml.dump(doc, buf)
    new_text = buf.getvalue()
    old_text = path.read_text(encoding="utf-8")
    if new_text == old_text:
        return ("skipped_has_field", surfaces)
    path.write_text(new_text, encoding="utf-8")
    return (action, surfaces)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry", action="store_true", help="preview surfaces; do not write"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="rewrite files even when the field is already set",
    )
    args = parser.parse_args()

    yaml = _make_yaml()
    paths = sorted(TOOLS_DIR.glob("*.yml"))
    counts: dict[str, int] = {
        "wrote": 0,
        "rewrote": 0,
        "skipped_has_field": 0,
        "skipped_no_surfaces_detected": 0,
    }
    no_surface_ids: list[str] = []

    for path in paths:
        if args.dry:
            with path.open("r", encoding="utf-8") as fh:
                doc = yaml.load(fh)
            if doc is None:
                counts["skipped_no_surfaces_detected"] += 1
                no_surface_ids.append(path.stem)
                continue
            surfaces = list(_detect_integration_surfaces(doc))
            existing = doc.get("integration_surfaces")
            if surfaces:
                tag = "PREVIEW" if not existing else "EXISTS"
                print(f"  {path.name:40s} {tag}: {surfaces}")
            else:
                no_surface_ids.append(path.stem)
        else:
            action, surfaces = annotate_file(path, yaml=yaml, overwrite=args.overwrite)
            counts[action] = counts.get(action, 0) + 1
            if action.startswith("wrote") or action.startswith("rewrote"):
                print(f"  {action:8s} {path.name:40s} -> {surfaces}")
            elif action == "skipped_no_surfaces_detected":
                no_surface_ids.append(path.stem)

    print()
    print("summary:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    if no_surface_ids:
        print()
        print(
            f"no surfaces detected ({len(no_surface_ids)}): {', '.join(no_surface_ids)}"
        )
        print("(these tools need a manual entry or an override in _SURFACE_OVERRIDES)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
