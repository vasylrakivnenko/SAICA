"""KG loader for the MCP server.

Self-contained — does NOT import from ``pipeline.ask`` or ``pipeline.audit``.
We adapt the ``_load_node_yaml`` cache pattern from ``pipeline/ask/context.py``
but keep this module independent so the MCP server can start even when the
analyzer / Q&A backend is broken or being refactored.

The MCP server only needs to read tool YAMLs and (cheaply) iterate over them
to filter by failure mode + paradigm + integration_surfaces. All loads are
LRU-cached per-process; the YAML directory is small (~100 files) so we can
also pre-list the tool ids.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

log = logging.getLogger(__name__)

# Resolve the repo root from this file's location (pipeline/mcp/kg.py → repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "data" / "tools"
FAILURE_MODES_DIR = REPO_ROOT / "data" / "failure_modes"


def tool_yaml_path(tool_id: str) -> Path:
    """Return the canonical YAML path for ``tool_id`` (no existence check)."""
    return TOOLS_DIR / f"{tool_id}.yml"


@lru_cache(maxsize=1024)
def load_tool(tool_id: str) -> dict | None:
    """Load one tool YAML by id. Returns ``None`` if not found / unparseable."""
    for ext in (".yml", ".yaml"):
        path = TOOLS_DIR / f"{tool_id}{ext}"
        if path.exists():
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                log.warning("failed to load %s: %s", path, exc)
                return None
            return doc if isinstance(doc, dict) else None
    return None


@lru_cache(maxsize=1)
def all_tool_ids() -> tuple[str, ...]:
    """Return every tool id present on disk (cached for the process)."""
    if not TOOLS_DIR.is_dir():
        return ()
    ids: list[str] = []
    for path in sorted(TOOLS_DIR.iterdir()):
        if path.suffix in (".yml", ".yaml"):
            ids.append(path.stem)
    return tuple(ids)


def iter_tools() -> Iterable[dict]:
    """Yield every tool dict on disk. Skips files that fail to load."""
    for tid in all_tool_ids():
        doc = load_tool(tid)
        if doc is not None:
            yield doc


def tools_for_failure_mode(fm_id: str) -> list[dict]:
    """Return every tool YAML whose ``addresses_failure_modes`` contains ``fm_id``."""
    out: list[dict] = []
    for doc in iter_tools():
        fms = doc.get("addresses_failure_modes") or []
        if isinstance(fms, list) and fm_id in fms:
            out.append(doc)
    return out


__all__ = [
    "REPO_ROOT",
    "TOOLS_DIR",
    "FAILURE_MODES_DIR",
    "all_tool_ids",
    "iter_tools",
    "load_tool",
    "tool_yaml_path",
    "tools_for_failure_mode",
]
