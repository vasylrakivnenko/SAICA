"""SAICA MCP server (stdio transport, FastMCP).

Run as::

    .venv/bin/python -m pipeline.mcp.server          # serve on stdio
    .venv/bin/python -m pipeline.mcp.server --help   # print help and exit

Two tools are exposed:

* ``saica_lookup`` — one catalog entry by id.
* ``saica_recommend`` — catalog tools ranked by their tags: pass
  ``failure_modes=[...]`` for up to three tools per mode, or ``level`` for
  one of three tiers.

What the ranking is: an editorial weight per failure mode times the
tool's popularity (stars and maintenance status). A tag is what a tool
says it addresses. The one measured input: a tool is never offered for a
mode on which SAICA-Bench measured it below the floor. Measured picks are
on https://saica.ai/tool-coverage/.

This module is a thin transport wrapper: the logic lives in
``pipeline.mcp.lookup`` and ``pipeline.mcp.recommender`` and is tested
without the MCP machinery. Dependencies: ``requirements/mcp.txt``.
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from pipeline.audit.schemas import ToolRecord
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
    """Look up one tool of the SAICA catalog by id.

    Returns its record: control paradigm, temporal phase, autonomy level,
    integration surfaces and the failure modes it is tagged for (what the
    tool says it addresses; not a measurement).

    Args:
        tool_id: Catalog id, e.g. ``"semgrep"``, ``"promptfoo"``,
            ``"guardrails-ai"``: lower-case letters, digits and hyphens.

    Raises:
        ValueError: when ``tool_id`` is malformed or not in the catalog.
    """
    return _saica_lookup(tool_id)


@mcp.tool()
def saica_recommend(
    level: Optional[str] = None,
    failure_modes: Optional[list[str]] = None,
) -> dict[str, Any]:
    """List catalog tools for supervising an AI coding agent, ranked by tags.

    The ranking multiplies an editorial weight per failure mode
    (``data/failure_mode_priorities.yml``) by the tool's **popularity**
    (log of GitHub stars plus an adjustment for maintenance status). It is
    not a benchmark result. A tool is never listed for a failure mode on
    which SAICA-Bench measured it below the floor; for measured picks see
    https://saica.ai/tool-coverage/.

    Pass ``level`` for one of three tiers:

    * ``"minimum"`` — 1 tool: the first greedy pick.
    * ``"optimal"`` — 3 tools: the first three greedy picks.
    * ``"full"`` — picks until no tagged tool adds a failure mode. Modes
      left without a tool are returned in ``uncovered_failure_modes``.

    Or pass ``failure_modes=[...]`` for up to 3 tagged tools per mode.

    Default (no args) → ``"optimal"``. ``level`` and ``failure_modes``
    cannot be combined.

    Args:
        level: One of ``"minimum"``, ``"optimal"``, ``"full"``.
        failure_modes: Failure-mode ids of the catalog, e.g.
            ``scope_creep``, ``fabrication``, ``security_vulnerability``.
            An unknown id raises an error that lists the valid ones.

    Returns:
        Dict with ``mode``/``level``, ``agent_kind``, ``tools``,
        ``covered_failure_modes``, ``uncovered_failure_modes``,
        ``coverage_complete`` and ``summary`` (tiers), or
        ``by_failure_mode`` (targeted).

    Raises:
        ValueError: when ``level`` is unknown, ``failure_modes`` contains an
            unknown id, or both args are passed at once.
    """
    return _recommend(failure_modes, agent_kind=_agent_kind(), level=level)


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - runtime entry
    """Serve on stdio. ``--help`` prints help and exits without serving."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.mcp.server",
        description=(
            "SAICA MCP server on stdio: saica_lookup (one catalog entry) and "
            "saica_recommend (catalog tools ranked by their tags). It prints "
            "nothing until an MCP client connects."
        ),
        epilog=(
            "Optional environment: SAICA_AGENT_KIND (the id of the coding "
            "agent that asks). Dependencies: requirements/mcp.txt."
        ),
    )
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["mcp", "main", "saica_lookup", "saica_recommend"]
