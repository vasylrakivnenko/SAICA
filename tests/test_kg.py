"""Tests for :mod:`pipeline.kg`, the one KG loader of the served surface.

Everything runs on a fixture KG written to a temp directory
(:mod:`pipeline.shared.kg_fixture`), except the last test, which loads the
repository's own ``data/`` once and checks no counts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pipeline import kg
from pipeline.models import FAILURE_MODE_IDS, FailureMode, Tool
from pipeline.shared.kg_fixture import default_tools, tool, write_kg


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return write_kg(tmp_path)


def _dump(path: Path, node: dict) -> None:
    path.write_text(yaml.safe_dump(node, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# What a load returns
# ---------------------------------------------------------------------------


def test_fixture_kg_loads_strictly_and_returns_validated_objects(data_dir: Path):
    snapshot = kg.KG(data_dir, strict=True)
    assert snapshot.errors == ()
    assert set(snapshot.tools) == set(default_tools())
    assert all(isinstance(t, Tool) for t in snapshot.tools.values())
    assert all(isinstance(m, FailureMode) for m in snapshot.failure_modes.values())
    # The model object and the plain mapping describe the same node.
    semgrep = snapshot.tools["semgrep"]
    as_dict = snapshot.tool_dicts()["semgrep"]
    assert semgrep.control_paradigm.value == as_dict["control_paradigm"] == "detection"
    assert [m.value for m in semgrep.addresses_failure_modes] == as_dict[
        "addresses_failure_modes"
    ]
    # Dates are ISO strings in the mapping and dates on the object.
    assert as_dict["first_released"] == "2020-01-01"
    assert semgrep.first_released.isoformat() == "2020-01-01"


def test_nodes_are_sorted_by_id_and_every_kind_is_loaded(data_dir: Path):
    snapshot = kg.KG(data_dir)
    for kind in kg.KINDS:
        ids = list(snapshot.dicts(kind))
        assert ids == sorted(ids) and ids, kind
    assert snapshot.find("semgrep")[0] == "tool"
    assert snapshot.find("fabrication")[0] == "failure_mode"
    assert snapshot.find("fixture-paper-2025")[0] == "paper"
    assert snapshot.find("fixture-taxonomy")[0] == "taxonomy"
    assert snapshot.find("fixture-incident-2025")[0] == "incident"
    assert snapshot.find("fixture-recipe")[0] == "recipe"
    assert snapshot.find("no-such-node") is None
    assert "fixture-to-saica" in snapshot.ids()


def test_failure_mode_list_comes_from_the_folder(tmp_path: Path):
    """Drop one mode file and the list is one shorter: nothing is typed in."""
    data = write_kg(tmp_path, failure_modes=("fabrication", "scope_creep"))
    snapshot = kg.KG(data)
    assert snapshot.failure_mode_ids() == ("fabrication", "scope_creep")
    assert snapshot.failure_mode_names() == {
        "fabrication": "Fabrication",
        "scope_creep": "Scope creep",
    }


def test_priorities_are_likelihood_times_impact(data_dir: Path):
    snapshot = kg.KG(data_dir)
    table = snapshot.priority_records()
    weights = snapshot.priorities()
    assert set(weights) == set(FAILURE_MODE_IDS)
    for fm_id, record in table.items():
        assert weights[fm_id] == pytest.approx(record["likelihood"] * record["impact"])


# ---------------------------------------------------------------------------
# One error policy
# ---------------------------------------------------------------------------


def _break(data_dir: Path) -> dict[str, str]:
    """Add six files that must be left out; return ``{file name: reason}``."""
    tools = data_dir / "tools"
    (tools / "not-yaml.yml").write_text("id: [unclosed\n", encoding="utf-8")
    (tools / "a-list.yml").write_text("- one\n- two\n", encoding="utf-8")
    (tools / "twice.yml").write_text(
        yaml.safe_dump(tool("twice"), sort_keys=False) + "name: Second name\n",
        encoding="utf-8",
    )
    _dump(tools / "wrong-name.yml", tool("another-id"))
    _dump(tools / "unknown-mode.yml", tool("unknown-mode", modes=("made_up_mode",)))
    _dump(tools / "old-extension.yaml", tool("old-extension"))
    (tools / "latin1.yml").write_bytes("id: latin1\nname: caf\xe9\n".encode("latin-1"))
    return {
        "not-yaml.yml": "cannot be read as YAML",
        "a-list.yml": "top level must be a mapping",
        "twice.yml": "written twice",
        "wrong-name.yml": "does not equal the file name",
        "unknown-mode.yml": "addresses_failure_modes",
        "old-extension.yaml": ".yml extension",
        "latin1.yml": "cannot be read",
    }


def test_a_broken_file_is_left_out_and_reported(data_dir: Path, caplog):
    expected = _break(data_dir)
    with caplog.at_level("WARNING", logger="pipeline.kg"):
        snapshot = kg.KG(data_dir)
    # The good nodes are all still there; none of the broken ones is.
    assert set(snapshot.tools) == set(default_tools())
    reported = {e.file: e.message for e in snapshot.errors}
    assert set(reported) == set(expected)
    for name, reason in expected.items():
        assert reason in reported[name], (name, reported[name])
    # Each one is logged, so a served process says what it dropped.
    assert sum("KG file left out" in r.message for r in caplog.records) == len(expected)


def test_strict_load_raises_and_names_the_files(data_dir: Path):
    _break(data_dir)
    with pytest.raises(kg.KGError) as excinfo:
        kg.KG(data_dir, strict=True)
    assert len(excinfo.value.errors) == 7
    assert "not-yaml.yml" in str(excinfo.value)


def test_a_missing_or_malformed_priorities_file_is_an_error_not_a_crash(data_dir: Path):
    (data_dir / "failure_mode_priorities.yml").unlink()
    snapshot = kg.KG(data_dir)
    assert snapshot.priorities() == {}
    assert [e.file for e in snapshot.errors] == ["failure_mode_priorities.yml"]

    (data_dir / "failure_mode_priorities.yml").write_text(
        "priorities:\n  fabrication: {likelihood: high, impact: 2}\n"
        "  scope_creep: {likelihood: 0.5, impact: 2}\n",
        encoding="utf-8",
    )
    snapshot = kg.KG(data_dir)
    assert snapshot.priorities() == {"scope_creep": 1.0}
    assert "fabrication" in snapshot.errors[0].message


def test_fields_added_to_the_schema_in_november_are_accepted(tmp_path: Path):
    tools = default_tools()
    tools["semgrep"].update(
        upstream_pushed_at="2026-11-01", last_reviewed="2026-11-21", archived=False
    )
    data = write_kg(tmp_path, tools=tools)
    (data / "TOMBSTONES.yml").write_text(
        "tombstones:\n  - {id: gone, kind: tool, removed_on: 2026-11-21, reason: test}\n",
        encoding="utf-8",
    )
    snapshot = kg.KG(data, strict=True)
    assert snapshot.tools["semgrep"].archived is False
    # The tombstone file is not a node and is not read as one.
    assert "gone" not in snapshot.ids()


# ---------------------------------------------------------------------------
# The process-wide default
# ---------------------------------------------------------------------------


def test_use_data_dir_switches_the_default_and_restores_it(data_dir: Path):
    before = kg.default_data_dir()
    calls: list[str] = []
    hook = lambda: calls.append("reset")  # noqa: E731
    kg.on_reset(hook)
    try:
        with kg.use_data_dir(data_dir) as snapshot:
            assert kg.default_data_dir() == data_dir
            assert kg.load() is snapshot is kg.load()
            assert set(kg.load_tools()) == set(default_tools())
            assert kg.failure_mode_ids() == tuple(sorted(FAILURE_MODE_IDS))
            assert set(kg.load_priorities()) == set(FAILURE_MODE_IDS)
        assert kg.default_data_dir() == before
        # Derived caches were told to drop on the way in and on the way out.
        assert calls == ["reset", "reset"]
    finally:
        kg._reset_hooks.remove(hook)


def test_load_caches_per_directory_and_strict_reuses_the_parse(data_dir: Path):
    try:
        first = kg.load(data_dir)
        assert kg.load(data_dir) is first
        assert kg.load(data_dir, strict=True) is first
        _break(data_dir)
        # Still the cached parse until reset.
        assert kg.load(data_dir).errors == ()
        kg.reset()
        assert len(kg.load(data_dir).errors) == 7
        with pytest.raises(kg.KGError):
            kg.load(data_dir, strict=True)
    finally:
        kg.reset()


# ---------------------------------------------------------------------------
# The repository's own data (no counts)
# ---------------------------------------------------------------------------


def test_repository_kg_has_the_modes_of_the_enum():
    """One list of modes: the folder and ``pipeline.models`` agree.

    Reads the live ``data/``. If this fails while data is being edited, the
    gate (``validator/cli.py``) fails for the same reason.
    """
    snapshot = kg.load()
    assert set(snapshot.failure_mode_ids()) == set(FAILURE_MODE_IDS)
    assert set(snapshot.priorities()) == set(FAILURE_MODE_IDS)
