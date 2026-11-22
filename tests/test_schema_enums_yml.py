"""``schema/enums.yml`` is a hand-kept, human-readable copy of the enums in
``pipeline/models.py``. Nothing reads it, so nothing noticed when it fell
behind (two enums were missing in November 2026). This test keeps the two
lists equal: same enums, same values, same order.
"""

from __future__ import annotations

import enum
from pathlib import Path

import yaml

import pipeline.models as models

ENUMS_YML = Path(__file__).resolve().parents[1] / "schema" / "enums.yml"

# The YAML names the failure-mode enum after the node, not after the id type.
YAML_NAME = {"FailureModeId": "FailureMode"}


def _model_enums() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, obj in vars(models).items():
        if (
            isinstance(obj, type)
            and issubclass(obj, enum.Enum)
            and obj is not enum.Enum
        ):
            out[YAML_NAME.get(name, name)] = [member.value for member in obj]
    return out


def test_enums_yml_lists_every_enum_with_the_same_values() -> None:
    documented = yaml.safe_load(ENUMS_YML.read_text(encoding="utf-8"))
    in_models = _model_enums()
    assert set(documented) == set(in_models), (
        f"only in enums.yml: {sorted(set(documented) - set(in_models))};"
        f" only in pipeline/models.py: {sorted(set(in_models) - set(documented))}"
    )
    for name, values in in_models.items():
        assert list(documented[name]["values"]) == values, name


def test_every_enum_and_value_has_a_description() -> None:
    documented = yaml.safe_load(ENUMS_YML.read_text(encoding="utf-8"))
    for name, block in documented.items():
        assert str(block.get("description") or "").strip(), f"{name}: no description"
        for value, entry in block["values"].items():
            assert str(
                (entry or {}).get("description") or ""
            ).strip(), f"{name}.{value}: no description"


def test_failure_modes_are_described_as_tags_not_a_partition() -> None:
    block = yaml.safe_load(ENUMS_YML.read_text(encoding="utf-8"))["FailureMode"]
    assert block["partition"] is False
    assert "overlapping tags, not a partition" in " ".join(block["description"].split())
