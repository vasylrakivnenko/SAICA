"""Shared helpers for the validator tests (imported as ``kg_fixture``; the
``kg`` pytest fixture itself is defined in ``conftest.py`` next to this file).

``make_kg(root)`` writes a small, valid knowledge graph (all eleven failure
modes, three tools, two papers, one taxonomy, one crosswalk, one incident,
one recipe, the two side files, a manifest and a tombstone list). Tests
break one thing in it and check that the gate says so. It does not depend
on the live ``data/`` directory, which other work may be changing.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any, Callable

import yaml

from pipeline.models import FAILURE_MODE_IDS
from validator import cli as validator_cli


def write_yaml(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def edit_yaml(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    doc = read_yaml(path)
    change(doc)
    write_yaml(path, doc)


def run_gate(data_dir: Path, *extra: str) -> tuple[int, str]:
    """Run the validator on ``data_dir``; return ``(exit code, all output)``."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = validator_cli.main(["--data-dir", str(data_dir), *extra])
    return code, out.getvalue() + err.getvalue()


def _tool(tool_id: str, modes: list[str], repo: str) -> dict[str, Any]:
    return {
        "id": tool_id,
        "name": tool_id.title(),
        "description": f"{tool_id} checks code.",
        "first_released": "2024-01-10",
        "last_updated": "2026-03-01",
        "upstream_pushed_at": "2026-03-01",
        "last_reviewed": "2026-04-01",
        "maturity_status": "stable",
        "repository_url": f"https://github.com/example/{repo}",
        "documentation_url": f"https://example.org/{repo}/docs",
        "license": "MIT",
        "control_paradigm": "detection",
        "temporal_phase": "post_generation",
        "autonomy_level": "fully_autonomous",
        "implementation": "deterministic",
        "addresses_failure_modes": modes,
        "integration_surfaces": ["cli"],
        "cited_in": ["paper-a"],
        "security_notes": "Runs offline.",
        "stars": 1200,
        "stars_updated_at": "2026-04-01",
    }


def make_kg(root: Path) -> Path:
    """Write the fixture graph under ``root/data`` and return that path."""
    data = root / "data"

    for mode_id in FAILURE_MODE_IDS:
        write_yaml(
            data / "failure_modes" / f"{mode_id}.yml",
            {
                "id": mode_id,
                "name": mode_id.replace("_", " ").capitalize(),
                "description": f"Definition of {mode_id}.",
                "related_modes": {
                    "fabrication": ["obsolescence"],
                    "obsolescence": ["fabrication"],
                }.get(mode_id, []),
                "prior_work": ["paper-a"],
                "detection_signals": ["A reviewer can see it in the diff."],
            },
        )

    write_yaml(
        data / "papers" / "paper-a.yml",
        {
            "id": "paper-a",
            "authors": ["Ada Lovelace", "Alan Turing"],
            "year": 2025,
            "title": "A Study of Coding Agent Failures",
            "venue": "arXiv",
            "url": "https://arxiv.org/abs/2501.00001",
            "doi": "10.1000/example.a",
            "arxiv_id": "2501.00001",
            "arxiv_version": "v2",
            "provenance": "hand-curated",
        },
    )
    write_yaml(
        data / "papers" / "paper-b.yml",
        {
            "id": "paper-b",
            "authors": ["Grace Hopper"],
            "year": 2024,
            "title": "Package Hallucinations in Practice",
            "url": "https://example.org/papers/b",
            "doi": "10.1000/example.b",
            "provenance": "s2-derived",
        },
    )

    write_yaml(
        data / "tools" / "alpha.yml",
        _tool("alpha", ["fabrication", "logic_error"], "alpha"),
    )
    write_yaml(
        data / "tools" / "beta.yml",
        _tool("beta", ["security_vulnerability"], "beta"),
    )
    write_yaml(
        data / "tools" / "gamma.yml",
        _tool("gamma", ["scope_creep"], "gamma"),
    )

    write_yaml(
        data / "taxonomies" / "tax-a.yml",
        {
            "id": "tax-a",
            "name": "Example taxonomy",
            "owner": "Example group",
            "version": "2026",
            "first_published": "2026-01-08",
            "url": "https://example.org/taxonomy",
            "paper_id": "paper-a",
            "categories": [
                {"external_id": "TA-1", "label": "Invented calls"},
                {"external_id": "TA-2", "label": "User interface"},
                {"external_id": "TA-3", "label": "Runtime"},
                {"external_id": "TA-3.1", "label": "Timeouts", "parent_id": "TA-3"},
            ],
            "verified_against_source": "2026-11-21",
            "notes": "Labels are the source's own headings.",
        },
    )
    write_yaml(
        data / "crosswalks" / "tax-a-to-saica.yml",
        {
            "id": "tax-a-to-saica",
            "saica_axis": "failure_mode",
            "taxonomy": "tax-a",
            "authored_by": ["some-model"],
            "review_state": "llm_drafted_unreviewed",
            "source_checked_on": "2026-11-21",
            "mappings": [
                {
                    "saica_value": "fabrication",
                    "external_id": "TA-1",
                    "confidence": "partial",
                }
            ],
            "unmapped": [
                {"category": "TA-2", "reason": "Not a failure of the code change."},
                {"category": "TA-3", "reason": "Runtime behaviour, out of scope."},
            ],
        },
    )

    write_yaml(
        data / "incidents" / "incident-a-2025.yml",
        {
            "id": "incident-a-2025",
            "title": "An agent deleted a database",
            "description": "A dated real event with a named system.",
            "kind": "event",
            "incident_date": "2025-07-18",
            "harm_class": "data_loss",
            "reproducibility": "plausible",
            "exhibited_failure_modes": ["scope_creep"],
            "affected_systems": ["Example Agent"],
            "source_urls": ["https://example.org/news/incident-a"],
            "documented_by": ["paper-b"],
            "mitigated_by": ["gamma"],
        },
    )
    write_yaml(
        data / "recipes" / "recipe-a.yml",
        {
            "id": "recipe-a",
            "name": "Two checks",
            "description": "alpha then beta.",
            "targets_failure_modes": ["fabrication", "security_vulnerability"],
            "stack": ["alpha", "beta"],
            "evidence_tier": "anecdotal",
        },
    )

    write_yaml(
        data / "failure_mode_priorities.yml",
        {
            "version": 1,
            "priorities": {
                mode_id: {"likelihood": 0.5, "impact": 2}
                for mode_id in FAILURE_MODE_IDS
            },
            "expected_priority_ordering": list(FAILURE_MODE_IDS),
        },
    )
    write_yaml(
        data / "failure_mode_synonyms.yml",
        {
            "version": 1,
            "fabrication": {
                "canonical": "Fabrication",
                "synonyms": ["hallucinated API"],
                "anchor_papers": ["paper-b"],
            },
        },
    )
    write_yaml(
        data / "TOMBSTONES.yml",
        {
            "tombstones": [
                {
                    "id": "incident-old",
                    "kind": "incident",
                    "removed_on": "2026-11-21",
                    "reason": "Retracted: the source does not say this.",
                    "successor": None,
                    "archived_at": "archive/retracted/incident-old.yml",
                }
            ]
        },
    )

    kept = root / "archive" / "retracted" / "incident-old.yml"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text("id: incident-old\n", encoding="utf-8")

    ids: dict[str, Any] = {}
    for kind in (
        "tools",
        "failure_modes",
        "papers",
        "taxonomies",
        "crosswalks",
        "incidents",
        "recipes",
    ):
        found = sorted(p.stem for p in (data / kind).glob("*.yml"))
        ids[kind] = {i: None for i in found} if kind == "tools" else found
    ids["incidents"] = sorted(ids["incidents"] + ["incident-old"])
    (data / "MANIFEST.json").write_text(
        json.dumps({"kg_version": "2026.11", "ids": ids}, indent=2) + "\n",
        encoding="utf-8",
    )
    return data
