"""A small, valid knowledge graph for tests.

The files under ``data/`` change every week. A test that reads them fails
when a curator removes a tool, which says nothing about the code under
test (three audit tests did exactly that for months). Tests of the served
modules therefore build their own KG with :func:`write_kg` and point the
loader at it::

    from pipeline import kg
    from pipeline.shared.kg_fixture import write_kg

    with kg.use_data_dir(write_kg(tmp_path)):
        ...

Every node written here passes the models in :mod:`pipeline.models`; the
fixture's own test loads it with ``strict=True``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pipeline.models import FAILURE_MODE_IDS


def tool(
    tool_id: str,
    paradigm: str = "detection",
    modes: tuple[str, ...] = ("security_vulnerability",),
    surfaces: tuple[str, ...] = ("cli",),
    **fields: Any,
) -> dict[str, Any]:
    """One valid tool node. ``fields`` override or add keys."""
    node: dict[str, Any] = {
        "id": tool_id,
        "name": fields.pop("name", tool_id.replace("-", " ").title()),
        "tagline": f"Fixture entry for {tool_id}.",
        "description": f"{tool_id} as described for a test.",
        "first_released": "2020-01-01",
        "maturity_status": "stable",
        "license": "MIT",
        "control_paradigm": paradigm,
        "temporal_phase": "post_generation",
        "autonomy_level": "fully_autonomous",
        "implementation": "deterministic",
        "addresses_failure_modes": list(modes),
        "integration_surfaces": list(surfaces),
        "stars": 1000,
        "inclusion_rationale": "Listed for the fixture.",
    }
    node.update(fields)
    return node


def default_tools() -> dict[str, dict[str, Any]]:
    """Seventeen tools: fifteen the audit can detect, two it cannot.

    ``sentrux`` is the only tool tagged for ``cascading_failure`` and
    ``dependency_blindness``, and no detection rule exists for it, so the
    audit cannot assess those two modes. ``daytona`` is a sandbox with
    ``recovery`` + ``fully_autonomous`` facets (the pair the old Ask prompt
    mistook for "the agent itself").
    """
    tools = [
        tool(
            "semgrep",
            modes=("security_vulnerability", "supply_chain_attack"),
            surfaces=("cli", "ci_app", "library"),
            name="Semgrep",
            stars=12000,
            supervises_targets=["python", "javascript", "typescript", "go"],
        ),
        tool(
            "snyk",
            modes=("security_vulnerability", "supply_chain_attack"),
            surfaces=("cli", "ci_app"),
            name="Snyk",
            stars=5000,
        ),
        tool(
            "socket",
            "prevention",
            ("supply_chain_attack",),
            ("ci_app",),
            name="Socket",
            stars=800,
        ),
        tool(
            "pr-agent",
            modes=("logic_error", "fabrication"),
            surfaces=("ci_app", "cli"),
            name="PR-Agent",
            stars=9000,
            implementation="llm_based",
        ),
        tool(
            "dependabot",
            "prevention",
            ("supply_chain_attack", "obsolescence"),
            ("ci_app",),
            name="Dependabot",
            stars=4000,
        ),
        tool(
            "renovate",
            "prevention",
            ("supply_chain_attack", "obsolescence"),
            ("ci_app",),
            name="Renovate",
            stars=18000,
        ),
        tool(
            "guardrails-ai",
            "prevention",
            ("fabrication", "context_pollution"),
            ("library",),
            name="Guardrails AI",
            stars=5500,
        ),
        tool(
            "litellm",
            "prevention",
            ("scope_creep",),
            ("library", "proxy_gateway"),
            name="LiteLLM",
            stars=30000,
        ),
        tool(
            "promptfoo",
            modes=("test_manipulation", "security_vulnerability"),
            surfaces=("cli", "library", "ci_app"),
            name="promptfoo",
            stars=9000,
        ),
        tool(
            "ruff",
            modes=("fabrication", "logic_error"),
            name="Ruff",
            stars=40000,
            supervises_targets=["python"],
        ),
        tool(
            "mypy",
            modes=("fabrication", "logic_error"),
            name="mypy",
            stars=19000,
            supervises_targets=["python"],
        ),
        tool(
            "pyright",
            modes=("fabrication", "obsolescence"),
            name="Pyright",
            stars=14000,
            supervises_targets=["python"],
        ),
        tool(
            "pytest",
            modes=("incomplete_execution", "logic_error"),
            name="pytest",
            stars=12000,
            supervises_targets=["python"],
        ),
        tool(
            "bandit",
            modes=("security_vulnerability",),
            name="Bandit",
            stars=6500,
            supervises_targets=["python"],
        ),
        tool(
            "eslint",
            modes=("logic_error", "security_vulnerability"),
            name="ESLint",
            stars=25000,
            supervises_targets=["javascript", "typescript"],
        ),
        tool(
            "sentrux",
            "prevention",
            ("cascading_failure", "dependency_blindness"),
            ("library",),
            name="Sentrux",
            stars=300,
        ),
        tool(
            "daytona",
            "recovery",
            ("scope_creep", "security_vulnerability"),
            ("cli", "http_service"),
            name="Daytona",
            stars=70000,
            temporal_phase="in_generation",
        ),
    ]
    return {t["id"]: t for t in tools}


def failure_mode(fm_id: str) -> dict[str, Any]:
    return {
        "id": fm_id,
        "name": fm_id.replace("_", " ").capitalize(),
        "tagline": f"Fixture text for {fm_id}.",
        "description": f"What {fm_id.replace('_', ' ')} means, for a test.",
        "prior_work": ["fixture-paper-2025"],
        "detection_signals": ["A signal a reviewer could look for."],
    }


def other_nodes() -> dict[str, dict[str, dict[str, Any]]]:
    """One valid node of each remaining kind, keyed by folder then id."""
    return {
        "papers": {
            "fixture-paper-2025": {
                "id": "fixture-paper-2025",
                "authors": ["Ada Example", "Bo Sample"],
                "year": 2025,
                "title": "A Fixture Paper",
                "tldr": "A short summary used by the tests.",
            }
        },
        "taxonomies": {
            "fixture-taxonomy": {
                "id": "fixture-taxonomy",
                "name": "Fixture taxonomy",
                "owner": "Test owners",
                "version": "1.0",
                "scope": "Failure classes named for a test.",
                "categories": [{"external_id": "FX-01", "label": "First class"}],
            }
        },
        "crosswalks": {
            "fixture-to-saica": {
                "id": "fixture-to-saica",
                "saica_axis": "failure_mode",
                "taxonomy": "fixture-taxonomy",
                "mappings": [
                    {
                        "saica_value": "fabrication",
                        "external_id": "FX-01",
                        "confidence": "related",
                    }
                ],
            }
        },
        "incidents": {
            "fixture-incident-2025": {
                "id": "fixture-incident-2025",
                "title": "A fixture incident",
                "tagline": "Something went wrong in a test.",
                "description": "A dated event written for the tests.",
                "incident_date": "2025-03-01",
                "harm_class": "user_reported",
                "reproducibility": "anecdotal",
                "exhibited_failure_modes": ["fabrication"],
                "affected_systems": ["fixture-agent"],
                "source_urls": ["https://example.com/incident"],
                "documented_by": [],
                "mitigated_by": [],
            }
        },
        "recipes": {
            "fixture-recipe": {
                "id": "fixture-recipe",
                "name": "Fixture recipe",
                "description": "Two tools used together in a test.",
                "targets_failure_modes": ["fabrication"],
                "stack": ["ruff", "mypy"],
                "evidence_tier": "anecdotal",
            }
        },
    }


def priorities() -> dict[str, Any]:
    """A priorities file with a weight for every failure mode."""
    return {
        "label": "fixture weights",
        "version": 1,
        "priorities": {
            fm_id: {"likelihood": round(0.9 - 0.05 * index, 2), "impact": 2}
            for index, fm_id in enumerate(sorted(FAILURE_MODE_IDS))
        },
    }


def write_kg(
    root: Path,
    *,
    tools: dict[str, dict[str, Any]] | None = None,
    failure_modes: tuple[str, ...] | None = None,
) -> Path:
    """Write a valid KG under ``root/data`` and return that directory.

    ``tools`` replaces the default tool set; ``failure_modes`` replaces the
    list of mode ids (default: every id in :mod:`pipeline.models`).
    """
    data = Path(root) / "data"
    folders: dict[str, dict[str, dict[str, Any]]] = {
        "tools": tools if tools is not None else default_tools(),
        "failure_modes": {
            fm_id: failure_mode(fm_id)
            for fm_id in (
                failure_modes if failure_modes is not None else FAILURE_MODE_IDS
            )
        },
        **other_nodes(),
    }
    for folder, nodes in folders.items():
        (data / folder).mkdir(parents=True, exist_ok=True)
        for node_id, node in nodes.items():
            (data / folder / f"{node_id}.yml").write_text(
                yaml.safe_dump(node, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
    (data / "failure_mode_priorities.yml").write_text(
        yaml.safe_dump(priorities(), sort_keys=False), encoding="utf-8"
    )
    return data


__all__ = [
    "default_tools",
    "failure_mode",
    "other_nodes",
    "priorities",
    "tool",
    "write_kg",
]
