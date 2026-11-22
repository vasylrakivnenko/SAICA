"""SAICA MCP server package.

Two tools for MCP-speaking coding agents:
  - saica_lookup    : one catalog entry by id
  - saica_recommend : catalog tools ranked by their tags (tiers, or per
                      failure mode); never a tool for a mode on which
                      SAICA-Bench measured it below the floor

Run as: ``python -m pipeline.mcp.server`` (stdio transport).
Dependencies: ``requirements/mcp.txt``.
"""
