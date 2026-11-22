"""What SAICA-Bench measured for the tools in the catalogue.

A tag in ``addresses_failure_modes`` is a claim: the tool's own
documentation says it deals with that failure mode. The benchmark tested
some of those claims. This module reads the published results and answers
two questions for the recommender and the generators:

* ``Evidence.measured(tool_id)`` — best measured Youden's J per failure
  mode for a catalogue tool (rows of ``site/public/bench/results.json``
  that carry a ``kg_id``);
* ``recommendable_modes(tool)`` — the modes a tool may be recommended for:
  its tags, minus every mode where its best measured J is below the site's
  floor (``floor`` in ``site/public/bench/kit.json``, 0.25 when absent),
  and nothing at all when the upstream repository is archived.

The result files are rebuilt by other jobs and their shape can grow, so
every read is defensive: a missing file, key or number never raises; it
just means "not measured". Benchmark mode ids that cannot be matched to a
failure-mode id are reported in ``Evidence.unmapped_modes`` instead of
being dropped silently.

Standard library only; importable from the generators (``validator/``) and
from the served recommender (``pipeline/mcp``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
RESULTS_PATH = REPO / "site" / "public" / "bench" / "results.json"
KIT_PATH = REPO / "site" / "public" / "bench" / "kit.json"

DEFAULT_FLOOR = 0.25

# Benchmark mode ids that differ from the failure-mode id by more than a
# hyphen. ``kit.json`` carries the mapping (``id`` → ``fm``); these are the
# fall-back when it is missing.
_MODE_ALIASES = {
    "security": "security_vulnerability",
    "supply_chain": "supply_chain_attack",
}


def _failure_mode_ids() -> frozenset[str]:
    from pipeline.models import FAILURE_MODE_IDS

    return frozenset(FAILURE_MODE_IDS)


@dataclass(frozen=True)
class Evidence:
    """Measured results for catalogue tools, as read from the bench files."""

    floor: float = DEFAULT_FLOOR
    generated: str | None = None
    source: str | None = None
    best: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    unmapped_modes: tuple[str, ...] = ()

    def measured(self, tool_id: str) -> dict[str, float]:
        """``{failure_mode_id: best J}`` for one tool; empty when not run."""
        return {fm: row["j"] for fm, row in self.best.get(tool_id, {}).items()}

    def below_floor(self, tool_id: str) -> dict[str, float]:
        """Modes where the tool's best measured J is below the floor."""
        return {fm: j for fm, j in self.measured(tool_id).items() if j < self.floor}

    def at_or_above_floor(self, tool_id: str) -> dict[str, float]:
        return {fm: j for fm, j in self.measured(tool_id).items() if j >= self.floor}

    def label(self, tool_id: str, failure_mode: str) -> str | None:
        """Name of the configuration that produced the best J."""
        row = self.best.get(tool_id, {}).get(failure_mode)
        return row.get("label") if row else None

    @property
    def measured_tools(self) -> list[str]:
        return sorted(self.best)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value:  # NaN
        return None
    return float(value)


def _kit_mode_map(kit: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    modes = kit.get("modes") if isinstance(kit, dict) else None
    for mode in modes if isinstance(modes, list) else []:
        if isinstance(mode, dict) and isinstance(mode.get("id"), str):
            if isinstance(mode.get("fm"), str):
                out[mode["id"]] = mode["fm"]
    return out


def failure_mode_of(mode: Any, kit_map: dict[str, str] | None = None) -> str | None:
    """Failure-mode id for one entry of ``results.json`` ``modes``; None
    when it cannot be told."""
    if not isinstance(mode, dict):
        return None
    known = _failure_mode_ids()
    candidates = [
        mode.get("fm"),
        (kit_map or {}).get(str(mode.get("id"))),
        _MODE_ALIASES.get(str(mode.get("id"))),
        str(mode.get("id") or "").replace("-", "_"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate in known:
            return candidate
    return None


def read_evidence(
    results_path: Path | None = None, kit_path: Path | None = None
) -> Evidence:
    """Read the bench files. Never raises on a missing or odd-shaped file."""
    results_path = results_path or RESULTS_PATH
    kit_path = kit_path or KIT_PATH
    results = _read_json(results_path)
    kit = _read_json(kit_path)

    floor = None
    for doc in (results, kit):
        if isinstance(doc, dict):
            floor = _number(doc.get("floor"))
            if floor is not None:
                break
    if floor is None:
        floor = DEFAULT_FLOOR

    if not isinstance(results, dict):
        return Evidence(floor=floor)

    kit_map = _kit_mode_map(kit)
    best: dict[str, dict[str, dict[str, Any]]] = {}
    unmapped: list[str] = []
    modes = results.get("modes")
    for mode in modes if isinstance(modes, list) else []:
        rows = mode.get("rows") if isinstance(mode, dict) else None
        rows = rows if isinstance(rows, list) else []
        fm = failure_mode_of(mode, kit_map)
        if fm is None:
            if any(isinstance(r, dict) and r.get("kg_id") for r in rows):
                unmapped.append(str(mode.get("id") if isinstance(mode, dict) else mode))
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            tool_id, j = row.get("kg_id"), _number(row.get("j"))
            if not isinstance(tool_id, str) or not tool_id or j is None:
                continue
            current = best.setdefault(tool_id, {}).get(fm)
            if current is None or j > current["j"]:
                best[tool_id][fm] = {
                    "j": j,
                    "label": (
                        row.get("tool") if isinstance(row.get("tool"), str) else None
                    ),
                }

    generated = results.get("generated")
    try:
        source = str(results_path.resolve().relative_to(REPO))
    except ValueError:
        source = str(results_path)
    return Evidence(
        floor=floor,
        generated=generated if isinstance(generated, str) else None,
        source=source,
        best=best,
        unmapped_modes=tuple(sorted(set(unmapped))),
    )


@lru_cache(maxsize=1)
def load_evidence() -> Evidence:
    """The evidence in the repository's own bench files, read once per
    process. Call ``load_evidence.cache_clear()`` after rewriting them."""
    return read_evidence()


def recommendable_modes(
    tool: dict[str, Any], evidence: Evidence | None = None
) -> list[str]:
    """Failure modes this tool may be recommended for.

    Its tags in order, minus the modes where its best measured J is below
    the floor. An archived tool is recommended for nothing.
    """
    if tool.get("archived") is True:
        return []
    evidence = evidence if evidence is not None else load_evidence()
    failed = evidence.below_floor(str(tool.get("id") or ""))
    tags = tool.get("addresses_failure_modes")
    return [fm for fm in (tags if isinstance(tags, list) else []) if fm not in failed]


def measured_view(
    tool: dict[str, Any], evidence: Evidence | None = None
) -> dict[str, Any]:
    """Copy of a tool dict as the recommender should see it:
    ``addresses_failure_modes`` holds only the recommendable modes.
    Applying it twice changes nothing."""
    view = dict(tool)
    view["addresses_failure_modes"] = recommendable_modes(tool, evidence)
    return view


__all__ = [
    "DEFAULT_FLOOR",
    "Evidence",
    "KIT_PATH",
    "RESULTS_PATH",
    "failure_mode_of",
    "load_evidence",
    "measured_view",
    "read_evidence",
    "recommendable_modes",
]
