"""Generate ``schema/*.json`` from :mod:`pipeline.models`.

Pydantic's default ``model_json_schema()`` diverges from the style of the
hand-written ``schema/*.json`` files in a few cosmetic ways:

* Pydantic adds ``$defs`` for nested models; ours inline them.
* Pydantic emits an auto-derived ``title`` on every field (e.g.
  ``"Openssf Scorecard Score"``); ours only carry titles on the top-level
  schema.
* Pydantic renders ``Optional[X]`` as ``{"anyOf":[{"type":X},{"type":"null"}]}``;
  the scorecard field in our hand-written schema uses ``{"type":["number","null"]}``.
* Pydantic emits ``"default": null`` for optional fields; we omit that.

The :func:`normalize_schema` function rewrites Pydantic's output to match the
committed style so diffs stay small and reviewable. Anything the normalizer
cannot rewrite is a deliberate representational choice that should land in a
human-reviewed commit.

CLI:

.. code-block:: shell

    python -m validator.generate_schemas            # write schema/*.json
    python -m validator.generate_schemas --check    # CI mode: diff; exit 1 on mismatch
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pipeline.models import (
    Crosswalk,
    FailureMode,
    Paper,
    Taxonomy,
    Tool,
)

REPO = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO / "schema"


# (model, output_filename, $id, description)
MODEL_OUTPUTS: list[tuple[type, str, str, str]] = [
    (
        Tool,
        "tool.schema.json",
        "https://saica-kg.dev/schema/tool.schema.json",
        "A software artifact that supervises AI coding agents.",
    ),
    (
        FailureMode,
        "failure_mode.schema.json",
        "https://saica-kg.dev/schema/failure_mode.schema.json",
        "A supervision-addressable failure class.",
    ),
    (
        Paper,
        "paper.schema.json",
        "https://saica-kg.dev/schema/paper.schema.json",
        "An academic or gray-literature reference used to ground nodes in SAICA-KG.",
    ),
    (
        Taxonomy,
        "taxonomy.schema.json",
        "https://saica-kg.dev/schema/taxonomy.schema.json",
        "An external failure-mode or risk taxonomy that SAICA-KG cross-walks into its own facets.",
    ),
    (
        Crosswalk,
        "crosswalk.schema.json",
        "https://saica-kg.dev/schema/crosswalk.schema.json",
        "A bulk mapping between a SAICA-KG axis and an external taxonomy's categories. Complements inline `crosswalks` declared on FailureMode nodes.",
    ),
]


# ---- Normalization -------------------------------------------------------


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    """Replace ``{"$ref": "#/$defs/Name"}`` with the inlined definition."""
    if isinstance(node, dict):
        if set(node.keys()) == {"$ref"}:
            ref = node["$ref"]
            if ref.startswith("#/$defs/"):
                target = defs[ref.split("/")[-1]]
                return _inline_refs(_copy(target), defs)
        return {k: _inline_refs(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline_refs(x, defs) for x in node]
    return node


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _collapse_optional(node: Any) -> Any:
    """Collapse Pydantic's two-arm ``anyOf`` for ``Optional[X]`` into a shape
    matching the committed schema style.

    Default behavior: strip the ``{"type":"null"}`` arm entirely (the field
    is simply "not required"; explicit null is not part of the data model).

    If the containing field carries the sentinel ``"_keep_null": true``
    (set via ``json_schema_extra``), preserve the null arm by rewriting
    to the committed ``{"type":["X","null"], ...}`` shape.
    """
    if isinstance(node, dict):
        if "anyOf" in node:
            arms = node["anyOf"]
            if (
                isinstance(arms, list)
                and len(arms) == 2
                and arms[1] == {"type": "null"}
                and isinstance(arms[0], dict)
            ):
                inner = dict(arms[0])
                outer = {k: v for k, v in node.items() if k != "anyOf"}
                keep_null = outer.pop("_keep_null", False)

                if keep_null and inner.get("type") in {
                    "string", "number", "integer", "boolean", "array", "object"
                }:
                    t = inner.pop("type")
                    merged = {"type": [t, "null"], **inner, **outer}
                else:
                    merged = {**inner, **outer}
                return {k: _collapse_optional(v) for k, v in merged.items()}
        return {k: _collapse_optional(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_collapse_optional(x) for x in node]
    return node


def _strip_titles(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove Pydantic's auto-derived ``"title"`` keys from property/subschema
    definitions. Preserves the top-level schema ``title`` (we set that).

    A key named ``title`` is stripped only when it appears as a JSON Schema
    keyword within a subschema (anything nested under ``properties``,
    ``items``, ``additionalProperties``, ``anyOf``, ``oneOf``, ``allOf``,
    ``$defs``). It is NEVER stripped when it appears as a property NAME
    (i.e., as a key inside a ``properties`` dict).
    """

    def walk_subschema(sub: Any) -> Any:
        if isinstance(sub, dict):
            out: dict[str, Any] = {}
            for k, v in sub.items():
                if k == "title" and isinstance(v, str):
                    # auto-derived pydantic title at subschema level — drop
                    continue
                if k == "properties" and isinstance(v, dict):
                    out[k] = {name: walk_subschema(inner) for name, inner in v.items()}
                elif k in {"items", "additionalProperties"} and isinstance(v, dict):
                    out[k] = walk_subschema(v)
                elif k in {"anyOf", "oneOf", "allOf", "prefixItems"} and isinstance(v, list):
                    out[k] = [walk_subschema(x) for x in v]
                elif k == "$defs" and isinstance(v, dict):
                    out[k] = {name: walk_subschema(inner) for name, inner in v.items()}
                else:
                    out[k] = v
            return out
        if isinstance(sub, list):
            return [walk_subschema(x) for x in sub]
        return sub

    # Walk top-level: preserve root title, but strip titles in subschemas.
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k == "properties" and isinstance(v, dict):
            out[k] = {name: walk_subschema(inner) for name, inner in v.items()}
        elif k in {"items", "additionalProperties"} and isinstance(v, dict):
            out[k] = walk_subschema(v)
        elif k in {"anyOf", "oneOf", "allOf", "prefixItems"} and isinstance(v, list):
            out[k] = [walk_subschema(x) for x in v]
        elif k == "$defs" and isinstance(v, dict):
            out[k] = {name: walk_subschema(inner) for name, inner in v.items()}
        else:
            out[k] = v
    return out


def _strip_defaults(node: Any) -> Any:
    """Drop ``"default": null`` entries — we don't carry them in the committed
    schema, and they obscure diffs.
    """
    if isinstance(node, dict):
        return {
            k: _strip_defaults(v)
            for k, v in node.items()
            if not (k == "default" and v is None)
        }
    if isinstance(node, list):
        return [_strip_defaults(x) for x in node]
    return node


def _reorder_schema_keys(schema: dict[str, Any]) -> dict[str, Any]:
    """Put top-level keys in the committed order:
    $schema, $id, title, description, type, required, properties,
    additionalProperties.
    """
    order = [
        "$schema",
        "$id",
        "title",
        "description",
        "type",
        "required",
        "properties",
        "additionalProperties",
    ]
    out: dict[str, Any] = {}
    for k in order:
        if k in schema:
            out[k] = schema[k]
    for k, v in schema.items():
        if k not in out:
            out[k] = v
    return out


def _reorder_object_keys(node: Any) -> Any:
    """Recursively reorder keys inside nested object subschemas so required →
    properties → additionalProperties match the committed style.
    """
    if isinstance(node, dict):
        out = dict(node)
        if out.get("type") == "object":
            order = [
                "type",
                "required",
                "properties",
                "additionalProperties",
            ]
            reordered: dict[str, Any] = {}
            for k in order:
                if k in out:
                    reordered[k] = out[k]
            for k, v in out.items():
                if k not in reordered:
                    reordered[k] = v
            out = reordered
        return {k: _reorder_object_keys(v) for k, v in out.items()}
    if isinstance(node, list):
        return [_reorder_object_keys(x) for x in node]
    return node


def _reorder_properties_by_model(
    schema: dict[str, Any], model: type
) -> dict[str, Any]:
    """Reorder ``properties`` to match the model's field-declaration order.

    Pydantic already emits properties in field order, but it may reorder
    after schema manipulation. Be explicit: use the model's declared order.
    """
    field_order = list(model.model_fields.keys())
    if "properties" in schema:
        props = schema["properties"]
        reordered = {name: props[name] for name in field_order if name in props}
        for k in props:
            if k not in reordered:
                reordered[k] = props[k]
        schema["properties"] = reordered
    return schema


def normalize_schema(
    pydantic_schema: dict[str, Any],
    *,
    model: type,
    schema_id: str,
    description: str,
    title: str,
) -> dict[str, Any]:
    """Convert Pydantic's output into our committed-style JSON Schema."""
    schema = _copy(pydantic_schema)
    defs = schema.pop("$defs", {})

    # Inline any $ref into the top-level schema.
    schema = _inline_refs(schema, defs)

    # Collapse Pydantic's Optional anyOf into single-type or ["X","null"]
    # shapes per field annotation.
    schema = _collapse_optional(schema)

    # Drop auto-derived titles and null defaults.
    schema = _strip_titles(schema)
    schema = _strip_defaults(schema)

    # Top-level metadata.
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = schema_id
    schema["title"] = title
    schema["description"] = description

    # Pydantic does not emit additionalProperties at the root when no extras
    # are allowed unless the class has extra='forbid'. It will be present but
    # let's guarantee it here for safety.
    schema.setdefault("additionalProperties", False)

    # Reorder properties by the model's declared field order (stable diffs).
    _reorder_properties_by_model(schema, model)

    # Normalize nested object ordering.
    schema = _reorder_object_keys(schema)

    # Final top-level key order.
    schema = _reorder_schema_keys(schema)

    return schema


# ---- CLI -----------------------------------------------------------------


def build_schema(model: type, *, schema_id: str, title: str, description: str) -> dict[str, Any]:
    raw = model.model_json_schema()
    return normalize_schema(
        raw,
        model=model,
        schema_id=schema_id,
        description=description,
        title=title,
    )


def format_schema(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Compare regenerated schemas to committed files; exit 1 on mismatch.",
    )
    args = ap.parse_args()

    mismatched: list[str] = []

    for model, filename, schema_id, description in MODEL_OUTPUTS:
        title = model.__name__
        schema = build_schema(
            model,
            schema_id=schema_id,
            title=title,
            description=description,
        )
        text = format_schema(schema)

        target = SCHEMA_DIR / filename

        if args.check:
            if not target.exists():
                mismatched.append(f"{filename}: missing committed file")
                continue
            existing = target.read_text()
            if existing != text:
                mismatched.append(filename)
        else:
            target.write_text(text)
            print(f"wrote {target.relative_to(REPO)}")

    if args.check:
        if mismatched:
            print(
                "schema drift detected in:\n  " + "\n  ".join(mismatched),
                file=sys.stderr,
            )
            print(
                "Run `python -m validator.generate_schemas` to regenerate.",
                file=sys.stderr,
            )
            return 1
        print("all schemas match committed copies")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
