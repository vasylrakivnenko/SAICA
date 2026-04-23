# SAICA-KG MCP Server

A thin MCP server that exposes three agent-facing tools over the SAICA-KG knowledge graph.

## Tools

- `search_supervision_tools(...)` — faceted filter over Tool nodes. Filters: `control_paradigm`, `temporal_phase`, `autonomy_level`, `failure_mode`, `min_maturity`, `language`, `license_allowlist`, `max_results`.
- `explain_failure_mode_crosswalk(failure_mode)` — SAICA-KG definition plus crosswalks into external taxonomies (OWASP Agentic Top 10 2026, MAST, DAPLab 9 Patterns, etc.) and mitigating tools.
- `get_kg_snapshot(version?)` — full graph as JSON at a pinned version.

Every response is wrapped in a uniform envelope:

```json
{
  "results": ...,
  "ranking_criteria": [...],
  "query_echo": {...},
  "total_matched": <int>,
  "kg_version": "2026.04",
  "kg_last_updated": "2026-04-22T...Z",
  "disclaimer": "SAICA-KG is navigational, not evaluative..."
}
```

## Running

From the repo root with the validator venv already set up:

```bash
.venv/bin/pip install -r mcp_server/requirements.txt
.venv/bin/python -m mcp_server.server
```

The server speaks stdio transport by default.

## Why 3 tools and not 8

The v0.1 spec proposed 8 tools. Research on existing MCP benchmarks (MCP-Universe, MCPToolBench++) suggests agents query a small stable surface; we ship 3 tools, instrument query telemetry, and add more when usage reveals they are needed. See `../research/SYNTHESIS.md`.
