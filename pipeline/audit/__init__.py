"""SAICA-KG audit analyzer.

Public entrypoint:
    from pipeline.audit import audit_repo
    report = audit_repo("https://github.com/owner/repo")
"""
from pipeline.audit.analyzer import audit_repo
from pipeline.audit.schemas import (
    AuditReport,
    CoverageCell,
    CoverageGrid,
    DetectedAgent,
    DetectedStack,
    DetectedTool,
    GapItem,
    Recommendation,
)

__all__ = [
    "AuditReport",
    "CoverageCell",
    "CoverageGrid",
    "DetectedAgent",
    "DetectedStack",
    "DetectedTool",
    "GapItem",
    "Recommendation",
    "audit_repo",
]
