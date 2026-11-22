"""Tests for ``validator.generate_maturity`` (activity bands, review E9 / E11).

The output must be a function of the tool files alone: the date recency is
judged against is taken from the data and stored in the file, never read
from the clock, so ``--check`` cannot turn red on a calendar date.
"""

from __future__ import annotations

import inspect
import json
from datetime import date
from pathlib import Path

import yaml

from pipeline.maturity import score as score_module
from validator import generate_maturity as gm


def _tools(tmp_path: Path) -> Path:
    tools = tmp_path / "tools"
    tools.mkdir()
    docs = [
        {
            "id": "busy",
            "stars": 30000,
            "maturity_status": "stable",
            "integration_surfaces": ["cli", "ci_app", "ide_plugin"],
            "upstream_pushed_at": "2026-11-01",
            "last_reviewed": "2026-11-21",
        },
        {
            "id": "quiet",
            "stars": 400,
            "maturity_status": "stable",
            "integration_surfaces": ["cli"],
            "last_updated": "2024-02-01",
            "stars_updated_at": "2026-04-23",
        },
        {
            "id": "shelved",
            "stars": 70000,
            "maturity_status": "stable",
            "integration_surfaces": ["cli", "http_service"],
            "upstream_pushed_at": "2026-10-01",
            "last_reviewed": "2026-11-21",
            "archived": True,
        },
    ]
    for doc in docs:
        (tools / f"{doc['id']}.yml").write_text(yaml.safe_dump(doc))
    return tools


def test_as_of_comes_from_the_data_and_is_stored(tmp_path: Path) -> None:
    payload = gm.build_payload(tools_dir=_tools(tmp_path))
    assert payload["as_of"] == "2026-11-21"
    assert payload["version"] == 2
    assert payload["tools"]["busy"]["facets"]["recent_push"] == 2.0
    assert payload["tools"]["quiet"]["facets"]["recent_push"] == 0.0


def test_bands_are_letters_and_archived_is_f(tmp_path: Path) -> None:
    tools = gm.build_payload(tools_dir=_tools(tmp_path))["tools"]
    assert {t["band"] for t in tools.values()} <= set("ABCDEF")
    assert tools["shelved"]["band"] == "F"
    assert any("archived" in note for note in tools["shelved"]["notes"])
    for row in tools.values():
        # Old key names carry the same letters until the site switches over.
        assert (
            row["tier"] == row["band"] and row["computed_tier"] == row["computed_band"]
        )


def test_scale_text_does_not_promise_evidence(tmp_path: Path) -> None:
    scale = gm.build_payload(tools_dir=_tools(tmp_path))["scale"]
    assert scale["name"] == "activity band"
    assert "not a level of evidence" in scale["description"]
    assert sorted(scale["bands"]) == list("ABCDEF")
    blob = json.dumps(scale["bands"]).lower()
    assert "paper" not in blob and "peer" not in blob


def test_no_clock_anywhere() -> None:
    for module in (gm, score_module):
        source = inspect.getsource(module)
        assert ".today(" not in source and ".now(" not in source, module.__name__


def test_explicit_as_of_moves_the_recency_facet(tmp_path: Path) -> None:
    tools_dir = _tools(tmp_path)
    later = gm.build_payload(as_of=date(2028, 6, 1), tools_dir=tools_dir)
    assert later["as_of"] == "2028-06-01"
    assert later["tools"]["busy"]["facets"]["recent_push"] == 0.0


def test_out_dir_write_and_check(tmp_path: Path) -> None:
    tracked = gm.DEFAULT_OUT.read_bytes()
    out_dir = tmp_path / "out"
    assert gm.main(["--out-dir", str(out_dir)]) == 0
    written = out_dir / "maturity.json"
    assert written.exists()
    assert gm.DEFAULT_OUT.read_bytes() == tracked
    assert gm.main(["--check", "--out-dir", str(out_dir)]) == 0
    doc = json.loads(written.read_text())
    doc["tools"][next(iter(doc["tools"]))]["band"] = "Z"
    written.write_text(json.dumps(doc))
    assert gm.main(["--check", "--out-dir", str(out_dir)]) == 1


def test_live_catalogue_scores_without_error() -> None:
    payload = gm.build_payload()
    assert payload["tools"], "no tools scored"
    assert date.fromisoformat(payload["as_of"])
