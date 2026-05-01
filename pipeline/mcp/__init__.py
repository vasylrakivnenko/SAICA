"""SAICA-KG MCP server package.

Exposes two tools to MCP-speaking coding agents:
  - saica_lookup    : structured KG catalog lookup
  - saica_recommend : two-mode supervision recommendations
                      (targeted FMs or full-suite covering all 11 FMs)

The asking agent identifies itself via the ``SAICA_AGENT_KIND`` env var
on the MCP server's process so we never recommend a peer coding agent
to another coding agent.

Run as: ``python -m pipeline.mcp.server`` (stdio transport).
"""
