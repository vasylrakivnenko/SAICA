"""SAICA-KG MCP server (stdio transport, FastMCP).

Run as::

    .venv/bin/python -m pipeline.mcp.server

Two tools are exposed:

* ``saica_lookup`` — catalog lookup; returns full ToolRecord for a given id.
* ``saica_recommend`` — supervision recommendations. Two modes baked in:
  pass ``failure_modes=[...]`` for targeted recs, or omit it for the
  full-suite (greedy set-cover over all 11 FMs).

Both tools honor a coding-agent filter so a user of one coding agent never
gets recommendations to install another (Cursor users don't get told to
install Claude Code, etc.). The asking agent identifies itself via the
``SAICA_AGENT_KIND`` env var on the MCP server's process — set this once
in your Claude Code MCP config (see ``mcp_config.example.json``).

This module is a *thin* transport wrapper: business logic lives in
``pipeline.mcp.lookup`` and ``pipeline.mcp.recommender``. Keeping the
server file small means Claude Code's MCP client can import it fast on
every session start, and tests can exercise the tools without touching
the MCP machinery.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from pipeline.mcp._schemas_compat import ToolRecord
from pipeline.mcp.lookup import saica_lookup as _saica_lookup
from pipeline.mcp.recommender import recommend as _recommend

log = logging.getLogger(__name__)

# Single FastMCP instance. The name is what Claude Code will surface to the
# user when listing connected MCP servers.
mcp = FastMCP("saica-kg")


def _agent_kind() -> Optional[str]:
    """Read the asking agent's identity from ``SAICA_AGENT_KIND``.

    Set in your MCP config:
        "env": {"SAICA_AGENT_KIND": "claude-code"}
    """
    val = os.environ.get("SAICA_AGENT_KIND")
    return val.strip() if val and val.strip() else None


@mcp.tool()
def saica_lookup(tool_id: str) -> ToolRecord:
    """Look up a SAICA-KG tool by id.

    Returns the full ToolRecord including control paradigm, temporal phase,
    autonomy level, integration_surfaces, and the failure modes the tool
    declares coverage for. Useful after ``saica_recommend`` so you can show
    the human the full facets of a recommended tool.

    Args:
        tool_id: KG tool id, e.g. ``"semgrep"``, ``"promptfoo"``,
            ``"guardrails-ai"``. Must match the ``id`` field of a
            ``data/tools/<id>.yml`` file in the repo.

    Raises:
        ValueError: when ``tool_id`` is not in the KG.
    """
    return _saica_lookup(tool_id)


@mcp.tool()
def saica_recommend(
    failure_modes: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Recommend supervision tools. Two modes — choose by argument.

    **Mode 1 (targeted):** pass ``failure_modes=["scope_creep", "fabrication"]``
    and we return up to 3 supervisors per requested mode, ranked by
    paradigm preference (prevention/detection beats correction/recovery),
    then by rationale-evidence, then by stars.

    **Mode 2 (full suite, default):** omit ``failure_modes`` (or pass
    ``None``/empty list) and we return the minimum set of supervisors that
    *together* cover all 11 failure modes — greedy set-cover, then a
    small depth pad of high-stars remaining tools.

    The asking agent's identity is read from ``SAICA_AGENT_KIND`` env var
    set in your MCP config. If that var matches a known coding agent
    (cursor, claude-code, windsurf, aider, replit-agent, …), no other
    coding agent is recommended — only supervisors that compose with it.

    Args:
        failure_modes: Optional list of FM ids from SAICA-KG's 11-mode
            taxonomy (``fabrication``, ``obsolescence``, ``dependency_blindness``,
            ``logic_error``, ``security_vulnerability``, ``scope_creep``,
            ``context_pollution``, ``supply_chain_attack``, ``cascading_failure``,
            ``incomplete_execution``, ``test_manipulation``). Pass ``None`` for
            the default full-suite mode.

    Returns:
        Dict shaped per the mode chosen — see ``pipeline.mcp.recommender``
        for full payload structure.

    Raises:
        ValueError: when any element of ``failure_modes`` is not a known FM id.
    """
    return _recommend(failure_modes, agent_kind=_agent_kind())


def main() -> None:  # pragma: no cover - executed only at runtime
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["mcp", "main", "saica_lookup", "saica_recommend"]
