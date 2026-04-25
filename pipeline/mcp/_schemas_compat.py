"""Defensive loader for ``pipeline.audit.schemas``.

Background: during Phase-1 parallel build, ``pipeline/audit/__init__.py``
eagerly imports ``pipeline.audit.analyzer`` (which Agent A is building in
parallel). If that module isn't on disk yet, ``import pipeline.audit``
raises ``ModuleNotFoundError`` — which would also break
``from pipeline.audit.schemas import ToolRecord``, because Python runs the
package ``__init__`` before reaching the submodule.

We can't edit ``pipeline/audit/__init__.py`` (out-of-scope for Agent B), so
we load ``schemas.py`` directly by file path using ``importlib.util``. Once
Agent A lands ``analyzer.py``, the standard ``from pipeline.audit.schemas
import ...`` form will also work, but this loader keeps working either way.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_schemas() -> ModuleType:
    # Try the normal path first — once Agent A's analyzer lands, this works
    # without the importlib detour and we benefit from the standard cache.
    try:
        from pipeline.audit import schemas as _real  # type: ignore[import-not-found]
        return _real
    except ImportError:
        pass

    # Fallback: load schemas.py directly. Stash it under a private name in
    # sys.modules so re-imports are cheap and downstream `isinstance` checks
    # against types defined here remain consistent across this process.
    cached = sys.modules.get("_saica_mcp_schemas_compat")
    if cached is not None:
        return cached

    schemas_path = (
        Path(__file__).resolve().parents[1] / "audit" / "schemas.py"
    )
    if not schemas_path.exists():
        raise ImportError(
            f"pipeline/audit/schemas.py not found at {schemas_path}; "
            "the SAICA-KG MCP server cannot start without the shared "
            "schema contract. Check your repo checkout."
        )
    spec = importlib.util.spec_from_file_location(
        "_saica_mcp_schemas_compat", schemas_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to build import spec for {schemas_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_saica_mcp_schemas_compat"] = module
    spec.loader.exec_module(module)
    return module


_schemas = _load_schemas()

AuditReport = _schemas.AuditReport
CoverageCell = _schemas.CoverageCell
CoverageGrid = _schemas.CoverageGrid
DetectedAgent = _schemas.DetectedAgent
DetectedStack = _schemas.DetectedStack
DetectedTool = _schemas.DetectedTool
GapItem = _schemas.GapItem
Paradigm = _schemas.Paradigm
PreflightInput = _schemas.PreflightInput
PreflightResult = _schemas.PreflightResult
Recommendation = _schemas.Recommendation
Severity = _schemas.Severity
Tier = _schemas.Tier
ToolRecord = _schemas.ToolRecord


__all__ = [
    "AuditReport",
    "CoverageCell",
    "CoverageGrid",
    "DetectedAgent",
    "DetectedStack",
    "DetectedTool",
    "GapItem",
    "Paradigm",
    "PreflightInput",
    "PreflightResult",
    "Recommendation",
    "Severity",
    "Tier",
    "ToolRecord",
]
