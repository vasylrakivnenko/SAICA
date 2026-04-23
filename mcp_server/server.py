"""SAICA-KG MCP server — 3 tools over the knowledge graph.

Run with:
    uv run mcp_server/server.py       # stdio transport
    python mcp_server/server.py       # from venv with deps installed

The server loads the graph once at startup. To reload after editing YAML,
restart the server. A hot-reload watcher is out of scope for v0.1.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server.graph import DISCLAIMER, Graph, KG_VERSION, envelope


_graph: Graph | None = None


def graph() -> Graph:
    global _graph
    if _graph is None:
        _graph = Graph.load()
    return _graph


mcp = FastMCP("saica-kg")


@mcp.tool()
def search_supervision_tools(
    control_paradigm: str | None = None,
    temporal_phase: str | None = None,
    autonomy_level: str | None = None,
    failure_mode: str | None = None,
    min_maturity: str | None = None,
    language: str | None = None,
    license_allowlist: list[str] | None = None,
    max_results: int = 20,
) -> dict[str, Any]:
    """Find supervision tools matching any combination of facets.

    Args:
        control_paradigm: prevention | detection | correction | recovery
        temporal_phase:   pre_generation | in_generation | post_generation
        autonomy_level:   fully_autonomous | graduated_hitl | full_hitl
        failure_mode:     One of the 8 SAICA-KG FailureMode ids.
        min_maturity:     experimental | stable
        language:         Target language ecosystem (python, typescript, ...)
        license_allowlist: SPDX identifiers to restrict to.
        max_results:      Default 20, max 100.

    Returns a response envelope with:
        results, ranking_criteria, query_echo, total_matched, kg_version,
        kg_last_updated, disclaimer.
    """
    g = graph()
    max_results = min(max(1, max_results), 100)
    results = g.search_tools(
        control_paradigm=control_paradigm,
        temporal_phase=temporal_phase,
        autonomy_level=autonomy_level,
        failure_mode=failure_mode,
        min_maturity=min_maturity,
        language=language,
        license_allowlist=license_allowlist,
        max_results=max_results,
    )
    return envelope(
        results=[{
            "id": t["id"],
            "name": t["name"],
            "tagline": t.get("tagline"),
            "control_paradigm": t["control_paradigm"],
            "temporal_phase": t["temporal_phase"],
            "autonomy_level": t["autonomy_level"],
            "addresses_failure_modes": t["addresses_failure_modes"],
            "maturity_status": t.get("maturity_status"),
            "license": t.get("license"),
            "url": t.get("repository_url") or t.get("documentation_url"),
        } for t in results],
        query={
            "control_paradigm": control_paradigm,
            "temporal_phase": temporal_phase,
            "autonomy_level": autonomy_level,
            "failure_mode": failure_mode,
            "min_maturity": min_maturity,
            "language": language,
            "license_allowlist": license_allowlist,
            "max_results": max_results,
        },
        ranking_criteria=["maturity_status", "recency", "id"],
        total=len(results),
        g=g,
    )


@mcp.tool()
def explain_failure_mode_crosswalk(failure_mode: str) -> dict[str, Any]:
    """Return a structured explanation of a failure mode with crosswalks.

    Args:
        failure_mode: One of the 8 SAICA-KG FailureMode ids.

    Returns SAICA-KG's canonical definition, prior-work citations,
    detection signals, mitigating tools, and explicit mappings
    (crosswalks) into external taxonomies (OWASP Agentic Top 10, MAST,
    DAPLab 9 Patterns, etc.).
    """
    g = graph()
    data = g.explain_failure_mode(failure_mode)
    return envelope(
        results=data,
        query={"failure_mode": failure_mode},
        ranking_criteria=["control_paradigm_coverage", "maturity", "recency"],
        total=len(data.get("mitigators", [])) if isinstance(data, dict) else 0,
        g=g,
    )


@mcp.tool()
def get_kg_snapshot(version: str | None = None) -> dict[str, Any]:
    """Return the full KG as JSON at a pinned version.

    Args:
        version: Version identifier (e.g. '2026.04'). If omitted, returns
                 the latest loaded version.

    Returns the complete set of nodes. Use this when an agent wants to
    reason over the graph locally without multiple round-trips.
    """
    g = graph()
    snap = g.snapshot()
    if version and version != KG_VERSION:
        return envelope(
            results={"error": f"version '{version}' not available; latest is '{KG_VERSION}'"},
            query={"version": version},
            ranking_criteria=[],
            total=0,
            g=g,
        )
    return envelope(
        results=snap,
        query={"version": version or KG_VERSION},
        ranking_criteria=[],
        total=sum(snap["counts"].values()),
        g=g,
    )


if __name__ == "__main__":
    mcp.run()
