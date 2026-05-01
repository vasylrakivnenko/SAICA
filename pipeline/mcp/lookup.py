"""``saica_lookup`` implementation.

Pure function (no MCP imports) — the MCP server in ``server.py`` thinly
wraps this for transport. Returning a strict ``ToolRecord`` keeps the wire
contract aligned with ``pipeline/audit/schemas.py`` and the /assess UI.
"""
from __future__ import annotations

from typing import Optional

from pipeline.mcp._schemas_compat import ToolRecord
from pipeline.mcp.kg import load_tool


def _as_str_list(val) -> list[str]:
    if not val:
        return []
    if isinstance(val, list):
        return [str(x) for x in val if x is not None]
    return [str(val)]


def _as_optional_str(val) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _as_optional_int(val) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def saica_lookup(tool_id: str) -> ToolRecord:
    """Return the full ``ToolRecord`` for ``tool_id``.

    Raises:
        ValueError: if ``tool_id`` is not present in the KG. The MCP layer
            surfaces this as an MCP error so the agent can self-correct.
    """
    if not tool_id or not isinstance(tool_id, str):
        raise ValueError("tool_id must be a non-empty string")

    doc = load_tool(tool_id)
    if doc is None:
        raise ValueError(
            f"unknown tool_id: {tool_id!r}; check /tool-coverage on the site "
            "or browse data/tools/ in the repo for the canonical id list"
        )

    canonical_id = str(doc.get("id") or tool_id)
    return ToolRecord(
        id=canonical_id,
        name=str(doc.get("name") or canonical_id),
        tagline=_as_optional_str(doc.get("tagline")),
        description=str(doc.get("description") or "").strip(),
        control_paradigm=str(doc.get("control_paradigm") or ""),
        temporal_phase=str(doc.get("temporal_phase") or ""),
        autonomy_level=str(doc.get("autonomy_level") or ""),
        addresses_failure_modes=_as_str_list(doc.get("addresses_failure_modes")),
        integration_surfaces=_as_str_list(doc.get("integration_surfaces")),
        locus_of_control=_as_str_list(doc.get("locus_of_control")),
        composes_with=_as_str_list(doc.get("composes_with")),
        feeds_into=_as_str_list(doc.get("feeds_into")),
        stars=_as_optional_int(doc.get("stars")),
        maturity_status=_as_optional_str(doc.get("maturity_status")),
        url=f"/tools/{canonical_id}",
    )


__all__ = ["saica_lookup"]
