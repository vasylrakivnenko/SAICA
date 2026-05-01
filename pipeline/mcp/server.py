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
    level: Optional[str] = None,
    failure_modes: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Recommend supervision tools. Three coverage tiers + a targeted mode.

    Picks tools by **likelihood × impact** of each failure mode (per
    ``data/failure_mode_priorities.yml``) multiplied by tool **reliability**
    (log-stars + trending boost + citation count + maturity).

    Pass ``level`` for one of three tiers:

    * ``"minimum"`` — **1 tool**: the single highest-priority × reliability
      tool. Best starter; covers the most weighted-priority FMs in one pick.
    * ``"optimal"`` — **3 tools**: greedy weighted set cover capped at 3.
      Best "responsible kit" — high coverage, low friction.
    * ``"full"``    — **N tools (typically 4–5)**: minimum weighted set
      cover until ALL 11 failure modes are covered. The MECE answer.

    Or pass ``failure_modes=[...]`` for the targeted mode (3 supervisors
    per requested FM).

    Default (no args) → ``"optimal"``. Cannot pass both ``level`` and
    ``failure_modes`` in the same call.

    The asking agent's identity is read from the ``SAICA_AGENT_KIND`` env
    var. If that matches a known coding agent (``cursor``, ``claude-code``,
    ``windsurf``, ``aider``, ``replit-agent``, …), no peer coding agent is
    recommended — only supervisors that compose with it.

    Args:
        level: One of ``"minimum"``, ``"optimal"``, ``"full"``.
            Defaults to ``"optimal"`` when both args are omitted.
        failure_modes: Optional list of FM ids from SAICA-KG's 11-mode
            taxonomy (``fabrication``, ``obsolescence``, ``dependency_blindness``,
            ``logic_error``, ``security_vulnerability``, ``scope_creep``,
            ``context_pollution``, ``supply_chain_attack``, ``cascading_failure``,
            ``incomplete_execution``, ``test_manipulation``).

    Returns:
        Dict with ``mode``/``level``, ``agent_kind``, ``tools`` (list of
        recommendations), ``covered_failure_modes``, ``uncovered_failure_modes``,
        ``coverage_complete``, ``summary``. See ``pipeline.mcp.recommender``
        for the exact shape per mode.

    Raises:
        ValueError: when ``level`` is unknown, ``failure_modes`` contains an
            unknown FM id, or both args are passed at once.
    """
    return _recommend(failure_modes, agent_kind=_agent_kind(), level=level)


def main() -> None:  # pragma: no cover - executed only at runtime
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["mcp", "main", "saica_lookup", "saica_recommend"]
