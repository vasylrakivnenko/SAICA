"""Schema-generation parity: the normalized Pydantic ``model_json_schema()``
output must match each committed ``schema/*.json``.

If this test fails, run:

    python -m validator.generate_schemas

and commit the result. The goal is that Pydantic models (in
``pipeline.models``) remain the single source of truth; the JSON Schema files
are regenerated from them, never hand-edited.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from validator.generate_schemas import MODEL_OUTPUTS, build_schema, format_schema

REPO = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO / "schema"


@pytest.mark.parametrize(
    "model,filename,schema_id,description",
    MODEL_OUTPUTS,
    ids=[m[1] for m in MODEL_OUTPUTS],
)
def test_generated_matches_committed(
    model: type, filename: str, schema_id: str, description: str
) -> None:
    schema = build_schema(
        model,
        schema_id=schema_id,
        title=model.__name__,
        description=description,
    )
    committed = (SCHEMA_DIR / filename).read_text()
    assert (
        format_schema(schema) == committed
    ), f"schema/{filename} is stale — run `python -m validator.generate_schemas`"


def test_schema_ids_look_correct() -> None:
    """Guard against URL drift."""
    for model, filename, schema_id, _ in MODEL_OUTPUTS:
        committed = json.loads((SCHEMA_DIR / filename).read_text())
        assert committed["$id"] == schema_id
        assert committed["title"] == model.__name__
