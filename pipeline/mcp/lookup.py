"""``saica_lookup`` implementation.

Pure function (no MCP imports); ``server.py`` wraps it for transport.
The tool is read through :mod:`pipeline.kg`, so it is a validated node.

The id is checked before anything is looked up: it must match
``^[a-z0-9][a-z0-9-]*$`` and be the id of a tool in the catalog. An
earlier version joined the caller's string into a file path, so
``../failure_modes/scope_creep`` returned a "tool" (review 2026-11-21, H10).
"""

from __future__ import annotations

import re

from pipeline import kg
from pipeline.audit.schemas import ToolRecord

TOOL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def saica_lookup(tool_id: str) -> ToolRecord:
    """Return the ``ToolRecord`` for ``tool_id``.

    Raises:
        ValueError: if ``tool_id`` is not a well-formed id or not a tool in
            the catalog. The MCP layer surfaces this as an MCP error so the
            agent can correct itself.
    """
    if not isinstance(tool_id, str) or not tool_id:
        raise ValueError("tool_id must be a non-empty string")
    if len(tool_id) > 100 or not TOOL_ID_RE.fullmatch(tool_id):
        raise ValueError(
            "tool_id must be a catalog id: lower-case letters, digits and "
            "hyphens (for example 'semgrep')"
        )
    doc = kg.load_tools().get(tool_id)
    if doc is None:
        raise ValueError(
            f"unknown tool_id: {tool_id!r}; the ids are listed at "
            "https://saica.ai/tools/ and in data/tools/ of the repository"
        )

    return ToolRecord(
        id=doc["id"],
        name=doc["name"],
        tagline=doc.get("tagline"),
        description=str(doc["description"]).strip(),
        control_paradigm=doc["control_paradigm"],
        temporal_phase=doc["temporal_phase"],
        autonomy_level=doc["autonomy_level"],
        addresses_failure_modes=list(doc["addresses_failure_modes"]),
        integration_surfaces=list(doc.get("integration_surfaces") or []),
        locus_of_control=list(doc.get("locus_of_control") or []),
        composes_with=list(doc.get("composes_with") or []),
        feeds_into=list(doc.get("feeds_into") or []),
        stars=doc.get("stars"),
        maturity_status=doc.get("maturity_status"),
        url=f"/tools/{doc['id']}",
    )


__all__ = ["TOOL_ID_RE", "saica_lookup"]
