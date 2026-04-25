"""SAICA-KG MCP server (stdio transport, FastMCP).

Run as::

    .venv/bin/python -m pipeline.mcp.server

This module is a *thin* transport wrapper: business logic lives in
``pipeline.mcp.lookup``, ``pipeline.mcp.preflight``, and (lazily)
``pipeline.audit``. Keeping the server file small means Claude Code's MCP
client can import it fast on every session start, and tests can exercise
the tools without touching the MCP machinery.
"""
from __future__ import annotations

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from pipeline.mcp._schemas_compat import AuditReport, PreflightResult, ToolRecord
from pipeline.mcp.lookup import saica_lookup as _saica_lookup
from pipeline.mcp.preflight import saica_preflight as _saica_preflight

log = logging.getLogger(__name__)

# Single FastMCP instance. The name is what Claude Code will surface to the
# user when listing connected MCP servers.
mcp = FastMCP("saica-kg")


@mcp.tool()
def saica_lookup(tool_id: str) -> ToolRecord:
    """Look up a SAICA-KG tool by id.

    Returns the full ToolRecord including control paradigm, temporal phase,
    autonomy level, integration_surfaces, and the failure modes the tool
    declares coverage for. Use this *after* ``saica_preflight`` recommends a
    tool so you can show the human the full facets.

    Args:
        tool_id: KG tool id, e.g. ``"semgrep"``, ``"promptfoo"``,
            ``"guardrails-ai"``. Must match the ``id`` field of a
            ``data/tools/<id>.yml`` file in the repo.

    Raises:
        ValueError: when ``tool_id`` is not in the KG. The error message
            includes a hint to call ``saica_search`` first (a v0.3 tool —
            for now, browse ``/tool-coverage`` on the site).
    """
    return _saica_lookup(tool_id)


@mcp.tool()
def saica_preflight(
    action: str,
    context: Optional[str] = None,
    agent_kind: Optional[str] = None,
) -> PreflightResult:
    """Get pre-action supervision advice for a proposed agent action.

    Hot path: agents may call this dozens of times per task. No LLM call
    is made; classification is keyword-based for predictable latency.

    Args:
        action: One-line description of what the agent is about to do,
            e.g. ``"edit src/auth.py"``, ``"pip install left-pad"``,
            ``"run shell command rm -rf node_modules"``.
        context: Optional surrounding context (file paths, prior diff,
            task description). Currently unused in classification but
            preserved in the contract for a future LLM-assisted version.
        agent_kind: Optional hint about which agent is asking
            (``"claude-code"``, ``"cursor"``, ``"windsurf"``, ``"aider"``,
            ``"codex-cli"``, ``"replit-agent"``). Influences which
            integration surfaces we prefer in recommendations.

    Returns:
        ``PreflightResult`` with ``risk_failure_modes``, an ``overall_risk``
        severity, 2–3 ranked ``recommended_supervisors``, and a one-sentence
        ``rationale``.
    """
    return _saica_preflight(action, context, agent_kind)


@mcp.tool()
def saica_audit_repo(repo_url: str) -> AuditReport:
    """Audit a public GitHub repo's supervision coverage.

    Delegates to ``pipeline.audit.audit_repo``. Imported lazily so the MCP
    server starts even if Agent A's analyzer module is not yet available;
    the agent will see a clear error message in that case.

    Args:
        repo_url: Public GitHub URL, e.g.
            ``"https://github.com/langfuse/langfuse"``.

    Returns:
        ``AuditReport`` with the detected stack, coverage grid, ranked
        gaps, recommendations, executive summary, and a Markdown rendering.

    Raises:
        RuntimeError: if the analyzer module is not importable.
    """
    try:
        from pipeline.audit import audit_repo  # type: ignore[attr-defined]
    except ImportError as exc:
        raise RuntimeError(
            "saica_audit_repo: the pipeline.audit analyzer module is not "
            "ready in this build (import failed: "
            f"{exc!s}). Use saica_lookup / saica_preflight in the meantime, "
            "or browse /tool-coverage on the SAICA-KG site."
        ) from exc
    return audit_repo(repo_url)


def main() -> None:  # pragma: no cover - executed only at runtime
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["mcp", "main", "saica_lookup", "saica_preflight", "saica_audit_repo"]
