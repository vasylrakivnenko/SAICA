"""The optional fields added on 2026-11-21 (review items E2, E3, E4, E6, E1).

Each field must be accepted with a valid value, rejected with an invalid
one, absent from ``required`` in the published JSON Schema, and enforced
by the gate where a cross-field rule goes with it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from kg_fixture import edit_yaml, run_gate
from pipeline.models import Crosswalk, Incident, Paper, Taxonomy, Tool

REPO = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO / "schema"

NEW_FIELDS = {
    "incident": ["kind"],
    "paper": ["provenance", "arxiv_version"],
    "tool": ["upstream_pushed_at", "last_reviewed", "archived"],
    "crosswalk": ["unmapped", "review_state"],
    "taxonomy": ["verified_against_source"],
}


@pytest.mark.parametrize("schema_name", sorted(NEW_FIELDS))
def test_published_schema_has_the_field_and_keeps_it_optional(schema_name: str) -> None:
    schema = json.loads((SCHEMA_DIR / f"{schema_name}.schema.json").read_text())
    for field in NEW_FIELDS[schema_name]:
        assert field in schema["properties"], f"{schema_name}.{field} missing"
        assert field not in schema["required"], f"{schema_name}.{field} is required"


def _incident(**extra: object) -> dict:
    return {
        "id": "x-1",
        "title": "t",
        "description": "d",
        "incident_date": "2025-01-01",
        "harm_class": "user_reported",
        "reproducibility": "plausible",
        "exhibited_failure_modes": ["fabrication"],
        "source_urls": ["https://example.org/a"],
        **extra,
    }


@pytest.mark.parametrize("kind", ["event", "study", "hypothetical", "pattern"])
def test_incident_kind_values(kind: str) -> None:
    assert Incident.model_validate(_incident(kind=kind)).kind.value == kind


def test_incident_kind_rejects_other_values() -> None:
    with pytest.raises(ValidationError):
        Incident.model_validate(_incident(kind="rumour"))
    assert Incident.model_validate(_incident()).kind is None


def _paper(**extra: object) -> dict:
    return {"id": "p-1", "authors": ["A B"], "year": 2025, "title": "T", **extra}


@pytest.mark.parametrize(
    "value",
    ["hand-curated", "s2-derived", "elicit-derived", "arxiv-api", "crossref-api"],
)
def test_paper_provenance_values(value: str) -> None:
    assert Paper.model_validate(_paper(provenance=value)).provenance.value == value


def test_paper_provenance_and_version_reject_bad_values() -> None:
    with pytest.raises(ValidationError):
        Paper.model_validate(_paper(provenance="guessed"))
    assert Paper.model_validate(_paper(arxiv_version="v3")).arxiv_version == "v3"
    for bad in ("3", "v0", "version 3", "v3.1"):
        with pytest.raises(ValidationError):
            Paper.model_validate(_paper(arxiv_version=bad))


def _tool(**extra: object) -> dict:
    return {
        "id": "t-1",
        "name": "T",
        "description": "d",
        "first_released": "2024-01-01",
        "maturity_status": "stable",
        "license": "MIT",
        "control_paradigm": "detection",
        "temporal_phase": "post_generation",
        "autonomy_level": "fully_autonomous",
        "implementation": "deterministic",
        "addresses_failure_modes": ["fabrication"],
        **extra,
    }


def test_tool_refresh_fields() -> None:
    tool = Tool.model_validate(
        _tool(
            upstream_pushed_at="2026-11-01", last_reviewed="2026-11-21", archived=True
        )
    )
    assert tool.upstream_pushed_at.isoformat() == "2026-11-01"
    assert tool.last_reviewed.isoformat() == "2026-11-21"
    assert tool.archived is True
    with pytest.raises(ValidationError):
        Tool.model_validate(_tool(upstream_pushed_at="last week"))


def _crosswalk(**extra: object) -> dict:
    return {
        "id": "c-1",
        "saica_axis": "failure_mode",
        "taxonomy": "tax-a",
        "mappings": [
            {"saica_value": "fabrication", "external_id": "TA-1", "confidence": "exact"}
        ],
        **extra,
    }


def test_crosswalk_unmapped_and_review_state() -> None:
    cw = Crosswalk.model_validate(
        _crosswalk(
            review_state="llm_drafted_unreviewed",
            unmapped=[{"category": "TA-2", "reason": "not a failure class"}],
        )
    )
    assert cw.review_state.value == "llm_drafted_unreviewed"
    assert cw.unmapped[0].category == "TA-2"
    with pytest.raises(ValidationError):
        Crosswalk.model_validate(_crosswalk(review_state="looks fine"))
    with pytest.raises(ValidationError):
        Crosswalk.model_validate(_crosswalk(unmapped=[{"category": "TA-2"}]))
    with pytest.raises(ValidationError):
        Crosswalk.model_validate(
            _crosswalk(unmapped=[{"category": "TA-2", "reason": ""}])
        )


def test_taxonomy_verified_against_source_is_a_date() -> None:
    base = {
        "id": "tax-a",
        "name": "n",
        "owner": "o",
        "version": "1",
        "categories": [{"external_id": "TA-1", "label": "l"}],
    }
    tax = Taxonomy.model_validate({**base, "verified_against_source": "2026-11-21"})
    assert tax.verified_against_source.isoformat() == "2026-11-21"
    with pytest.raises(ValidationError):
        Taxonomy.model_validate({**base, "verified_against_source": "yes"})


# --- gate rules that go with the fields ------------------------------------


def test_archived_but_stable_is_a_warning(kg: Path) -> None:
    edit_yaml(kg / "tools" / "alpha.yml", lambda d: d.update(archived=True))
    code, output = run_gate(kg)
    assert code == 0
    assert (
        "alpha: upstream repository is archived but maturity_status is 'stable'"
        in output
    )


def test_staleness_uses_the_review_date_not_the_clock(kg: Path) -> None:
    """A tool whose upstream was silent for over a year when it was last
    checked is flagged; the message does not change with the run date."""
    edit_yaml(
        kg / "tools" / "alpha.yml",
        lambda d: d.update(upstream_pushed_at="2024-12-01", last_updated="2024-12-01"),
    )
    first = run_gate(kg, "--as-of", "2026-11-21")[1]
    later = run_gate(kg, "--as-of", "2031-01-01")[1]
    line = "alpha: no upstream push for 486 days when last checked on 2026-04-01"
    assert line in first
    assert [w for w in first.splitlines() if w.startswith("WARN")] == [
        w for w in later.splitlines() if w.startswith("WARN")
    ]


def test_bench_release_id_is_accepted_in_evaluated_on(kg: Path) -> None:
    edit_yaml(
        kg / "tools" / "alpha.yml",
        lambda d: d.update(evaluated_on=["paper-a", "saica-bench-2026-11"]),
    )
    code, output = run_gate(kg)
    assert code == 0, output


def test_bench_release_id_needs_a_measured_row_when_results_exist(kg: Path) -> None:
    results = kg.parent / "site" / "public" / "bench" / "results.json"
    results.parent.mkdir(parents=True)
    results.write_text(
        json.dumps({"modes": [{"id": "fabrication", "rows": [{"kg_id": "beta"}]}]})
    )
    edit_yaml(
        kg / "tools" / "alpha.yml",
        lambda d: d.update(evaluated_on=["saica-bench-2026-11"]),
    )
    code, output = run_gate(kg)
    assert code == 1
    assert (
        "alpha evaluated_on 'saica-bench-2026-11' but the benchmark results have no row"
        in output
    )

    edit_yaml(kg / "tools" / "alpha.yml", lambda d: d.pop("evaluated_on"))
    edit_yaml(
        kg / "tools" / "beta.yml",
        lambda d: d.update(evaluated_on=["saica-bench-2026-11"]),
    )
    assert run_gate(kg)[0] == 0


def test_verified_taxonomy_may_quote_the_old_wording(kg: Path) -> None:
    """A retraction note that quotes "paraphrased for seed" is history once
    the file carries ``verified_against_source``."""
    edit_yaml(
        kg / "taxonomies" / "tax-a.yml",
        lambda d: d.update(
            notes='Rebuilt from the source. The old note said "paraphrased for seed".'
        ),
    )
    code, output = run_gate(kg)
    assert code == 0, output

    edit_yaml(
        kg / "taxonomies" / "tax-a.yml", lambda d: d.pop("verified_against_source")
    )
    code, output = run_gate(kg)
    assert code == 1
    assert "tax-a-to-saica maps to taxonomy 'tax-a'" in output


def test_soft_unverified_wording_is_a_warning(kg: Path) -> None:
    def change(doc: dict) -> None:
        doc.pop("verified_against_source")
        doc["notes"] = (
            "Labels paraphrased from a blog summary; pending full-text verification."
        )

    edit_yaml(kg / "taxonomies" / "tax-a.yml", change)
    code, output = run_gate(kg)
    assert code == 0, output
    assert "[taxonomies] tax-a: notes say the labels are not verified" in output


def test_only_limits_the_schema_pass_but_not_cross_checks(kg: Path) -> None:
    edit_yaml(kg / "papers" / "paper-b.yml", lambda d: d.update(year="2024"))
    edit_yaml(kg / "tools" / "alpha.yml", lambda d: d.update(feeds_into=["nope"]))
    code, output = run_gate(kg, "--only", "tools")
    assert code == 1
    assert "feeds_into missing tool 'nope'" in output
    assert "paper-b.yml :: year" not in output
    assert "paper-b.yml :: year" in run_gate(kg)[1]


def test_manifest_argument_points_the_lock_elsewhere(kg: Path, tmp_path: Path) -> None:
    other = tmp_path / "other-manifest.json"
    doc = json.loads((kg / "MANIFEST.json").read_text())
    doc["ids"]["papers"].append("paper-gone")
    other.write_text(json.dumps(doc))
    assert run_gate(kg)[0] == 0
    code, output = run_gate(kg, "--manifest", str(other))
    assert code == 1
    assert "papers id 'paper-gone' is in MANIFEST.json but no longer" in output
