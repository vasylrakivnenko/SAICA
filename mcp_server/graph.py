"""In-memory SAICA-KG graph built from YAML data files."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml


REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

KG_VERSION = "2026.04"


def _coerce(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _coerce(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce(v) for v in value]
    return value


def _load_dir(subdir: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    d = DATA / subdir
    if not d.exists():
        return out
    for p in sorted(d.glob("*.yml")) + sorted(d.glob("*.yaml")):
        with p.open() as fh:
            node = _coerce(yaml.safe_load(fh))
        if not isinstance(node, dict) or "id" not in node:
            raise ValueError(f"{p}: missing top-level 'id'")
        out[node["id"]] = node
    return out


@dataclass
class Graph:
    tools: dict[str, dict] = field(default_factory=dict)
    failure_modes: dict[str, dict] = field(default_factory=dict)
    papers: dict[str, dict] = field(default_factory=dict)
    taxonomies: dict[str, dict] = field(default_factory=dict)
    crosswalks: dict[str, dict] = field(default_factory=dict)

    last_updated: str = field(default_factory=lambda: dt.datetime.utcnow().isoformat(timespec="seconds") + "Z")

    @classmethod
    def load(cls) -> "Graph":
        return cls(
            tools=_load_dir("tools"),
            failure_modes=_load_dir("failure_modes"),
            papers=_load_dir("papers"),
            taxonomies=_load_dir("taxonomies"),
            crosswalks=_load_dir("crosswalks"),
        )

    def mitigators_for(self, mode_id: str) -> list[dict]:
        return [t for t in self.tools.values()
                if mode_id in (t.get("addresses_failure_modes") or [])]

    def search_tools(
        self,
        control_paradigm: str | None = None,
        temporal_phase: str | None = None,
        autonomy_level: str | None = None,
        failure_mode: str | None = None,
        min_maturity: str | None = None,
        language: str | None = None,
        license_allowlist: list[str] | None = None,
        max_results: int = 20,
    ) -> list[dict]:
        MATURITY_RANK = {"experimental": 1, "stable": 2, "at_risk": 1, "deprecated": 0, "abandoned": 0}
        min_rank = MATURITY_RANK.get(min_maturity or "", 0)

        def keep(t: dict) -> bool:
            if control_paradigm and t.get("control_paradigm") != control_paradigm:
                return False
            if temporal_phase and t.get("temporal_phase") != temporal_phase:
                return False
            if autonomy_level and t.get("autonomy_level") != autonomy_level:
                return False
            if failure_mode and failure_mode not in (t.get("addresses_failure_modes") or []):
                return False
            if MATURITY_RANK.get(t.get("maturity_status", ""), 0) < min_rank:
                return False
            if language and language not in (t.get("supervises_targets") or []):
                return False
            if license_allowlist and t.get("license") not in license_allowlist:
                return False
            return True

        results = [t for t in self.tools.values() if keep(t)]
        results.sort(key=lambda t: (
            -MATURITY_RANK.get(t.get("maturity_status", ""), 0),
            str(t.get("last_updated", "")),
            t.get("id", ""),
        ), reverse=False)
        return results[:max_results]

    def explain_failure_mode(self, mode_id: str) -> dict:
        mode = self.failure_modes.get(mode_id)
        if not mode:
            return {"error": f"unknown failure_mode '{mode_id}'", "known": sorted(self.failure_modes)}
        mitigators = self.mitigators_for(mode_id)
        prior_work = [self.papers.get(p, {"id": p, "missing": True}) for p in (mode.get("prior_work") or [])]
        crosswalks = []
        for cw in (mode.get("crosswalks") or []):
            tax = self.taxonomies.get(cw["taxonomy"])
            entry = {"taxonomy": cw["taxonomy"], "external_id": cw["external_id"], "confidence": cw["confidence"]}
            if tax:
                match = next((c for c in tax.get("categories", []) if c["external_id"] == cw["external_id"]), None)
                if match:
                    entry["external_label"] = match.get("label")
                    entry["external_description"] = match.get("description")
                entry["taxonomy_name"] = tax.get("name")
                entry["taxonomy_owner"] = tax.get("owner")
            if cw.get("note"):
                entry["note"] = cw["note"]
            crosswalks.append(entry)
        return {
            "id": mode["id"],
            "name": mode["name"],
            "description": mode["description"],
            "aliases": mode.get("aliases") or [],
            "related_modes": mode.get("related_modes") or [],
            "detection_signals": mode.get("detection_signals") or [],
            "prior_work": prior_work,
            "crosswalks": crosswalks,
            "mitigators": [{
                "id": t["id"],
                "name": t["name"],
                "control_paradigm": t["control_paradigm"],
                "temporal_phase": t["temporal_phase"],
                "autonomy_level": t["autonomy_level"],
            } for t in mitigators],
        }

    def snapshot(self) -> dict:
        return {
            "kg_version": KG_VERSION,
            "kg_last_updated": self.last_updated,
            "counts": {
                "tools": len(self.tools),
                "failure_modes": len(self.failure_modes),
                "papers": len(self.papers),
                "taxonomies": len(self.taxonomies),
                "crosswalks": len(self.crosswalks),
            },
            "nodes": {
                "tools": self.tools,
                "failure_modes": self.failure_modes,
                "papers": self.papers,
                "taxonomies": self.taxonomies,
                "crosswalks": self.crosswalks,
            },
        }


DISCLAIMER = (
    "SAICA-KG is navigational, not evaluative. Ranked sets reflect aggregate "
    "criteria; no single tool is endorsed."
)


def envelope(results: Any, query: dict, ranking_criteria: list[str], total: int, g: Graph) -> dict:
    return {
        "results": results,
        "ranking_criteria": ranking_criteria,
        "query_echo": query,
        "total_matched": total,
        "kg_version": KG_VERSION,
        "kg_last_updated": g.last_updated,
        "disclaimer": DISCLAIMER,
    }
