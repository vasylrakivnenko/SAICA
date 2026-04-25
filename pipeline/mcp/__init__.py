"""SAICA-KG MCP server package.

Exposes three tools to MCP-speaking coding agents:
  - saica_lookup       : structured KG catalog lookup
  - saica_preflight    : pre-action supervision advice (hot path)
  - saica_audit_repo   : delegates to pipeline.audit (one-shot per session)

Run as: ``python -m pipeline.mcp.server`` (stdio transport).
"""
