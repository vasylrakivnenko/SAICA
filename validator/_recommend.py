"""Shared plumbing for the two generators that publish tool suggestions
(``generate_recommendations`` and ``generate_skills``).

The selection logic itself lives in :mod:`pipeline.mcp.recommender`. This
module makes sure the published files obey four rules, whatever state the
recommender is in:

1. A tool is never listed for a failure mode where SAICA-Bench measured it
   below the site's floor, and an archived tool is never listed
   (:func:`measured_recommender` shows the recommender every tool through
   :func:`pipeline.maturity.evidence.measured_view`; :func:`assert_floor`
   then checks the finished payload and stops the build on a violation).
2. Within a mode, tools with a measured result come first.
3. Sentences say what was counted: tags are claims, measurements are named
   (:func:`describe_block`). "N tools cover 11 of 11 failure modes" is gone.
4. The score that orders tools is called what it is, popularity, and
   :func:`popularity_facts` reports any term beyond stars and status that
   moved a tool, instead of the text asserting a formula.

Nothing here reads the clock: the date printed in the files is the date of
``data/MANIFEST.json`` (:func:`kg_stamp`).
"""

from __future__ import annotations

import json
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from pipeline.maturity.evidence import Evidence, load_evidence, measured_view
from pipeline.models import FAILURE_MODE_IDS

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "data" / "MANIFEST.json"

KIT_BUILDER_URL = "https://saica.ai/tool-coverage/"
BACKEND_REQUEST = "research/fixes_20261121/requests/to_backend.md (kg_gate request 1)"

STATUSES = ("stable", "experimental", "at_risk", "deprecated", "abandoned")


# ---------------------------------------------------------------------------
# Stamp: KG version and date, from the manifest and not from the clock
# ---------------------------------------------------------------------------


def kg_stamp(manifest_path: Path | None = None) -> tuple[str, str]:
    """``(kg_version, date)`` of ``data/MANIFEST.json``; ``"unknown"`` for a
    part that cannot be read. The date is the manifest's ``generated_at``."""
    path = manifest_path or MANIFEST_PATH
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unknown", "unknown"
    if not isinstance(doc, dict):
        return "unknown", "unknown"
    version = doc.get("kg_version")
    stamp = doc.get("generated_at")
    return (
        str(version) if version else "unknown",
        str(stamp)[:10] if isinstance(stamp, str) and len(stamp) >= 10 else "unknown",
    )


def priorities_label(path: Path | None = None) -> str:
    """What ``data/failure_mode_priorities.yml`` says its numbers are (its
    top-level ``label``); a fixed plain description when it has none."""
    import yaml

    path = path or REPO_ROOT / "data" / "failure_mode_priorities.yml"
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        doc = None
    label = doc.get("label") if isinstance(doc, dict) else None
    if isinstance(label, str) and label.strip():
        return " ".join(label.split())
    return "editorial weights, no empirical calibration"


# ---------------------------------------------------------------------------
# Rule 1: the recommender sees tools through the measured view
# ---------------------------------------------------------------------------


@contextmanager
def measured_recommender(evidence: Evidence | None = None) -> Iterator[Evidence]:
    """While active, ``pipeline.mcp.recommender`` selects from tools whose
    ``addresses_failure_modes`` hold only the recommendable modes.

    The recommender has no parameter for the tool list, so this swaps its
    cached index and puts the old one back. Once the recommender applies
    ``measured_view`` in its own loader the swap changes nothing and can be
    deleted. If the names it relies on are gone, it stops with a message
    instead of publishing unfiltered picks.
    """
    from pipeline.mcp import recommender

    evidence = evidence if evidence is not None else load_evidence()
    loader = getattr(recommender, "_load_tools", None)
    if loader is None or not hasattr(recommender, "_TOOL_INDEX_CACHE"):
        raise RuntimeError(
            "pipeline.mcp.recommender no longer exposes _load_tools /"
            " _TOOL_INDEX_CACHE, so the generators cannot apply the measured"
            " floor from outside. Apply pipeline.maturity.evidence.measured_view"
            f" in its loader and remove this swap; see {BACKEND_REQUEST}."
        )
    original = loader()
    saved = recommender._TOOL_INDEX_CACHE
    recommender._TOOL_INDEX_CACHE = {
        tool_id: measured_view(tool, evidence)
        for tool_id, tool in sorted(original.items())
    }
    try:
        yield evidence
    finally:
        recommender._TOOL_INDEX_CACHE = saved


def catalogue_tools() -> dict[str, dict[str, Any]]:
    """The tool files as the recommender loaded them (untouched tags)."""
    from pipeline.mcp import recommender

    return dict(sorted(recommender._load_tools().items()))


def removed_pairs(
    tools: dict[str, dict[str, Any]], evidence: Evidence
) -> list[dict[str, Any]]:
    """Tagged tool × mode pairs that rule 1 removes, with the measured J."""
    out: list[dict[str, Any]] = []
    for tool_id, tool in sorted(tools.items()):
        tags = tool.get("addresses_failure_modes") or []
        if tool.get("archived") is True:
            out.extend(
                {"tool_id": tool_id, "failure_mode": fm, "reason": "archived"}
                for fm in tags
            )
            continue
        for fm, j in sorted(evidence.below_floor(tool_id).items()):
            if fm in tags:
                out.append(
                    {
                        "tool_id": tool_id,
                        "failure_mode": fm,
                        "reason": "measured below floor",
                        "j": round(j, 4),
                    }
                )
    return out


def annotate(rec: dict[str, Any], evidence: Evidence) -> dict[str, Any]:
    """Add what was measured to one recommendation dict; drop the dead
    ``trending`` flag."""
    out = {k: v for k, v in rec.items() if k != "trending"}
    tool_id = str(rec.get("tool_id") or "")
    modes = rec.get("addresses_failure_modes") or []
    passing = evidence.at_or_above_floor(tool_id)
    out["measured_j"] = {fm: round(passing[fm], 4) for fm in modes if fm in passing}
    return out


def measured_first(
    recs: list[dict[str, Any]], failure_mode: str, evidence: Evidence
) -> list[dict[str, Any]]:
    """Rule 2: tools measured on this mode first, best J first; the others
    keep the recommender's order."""

    def key(item: tuple[int, dict[str, Any]]) -> tuple[int, float, int]:
        index, rec = item
        j = evidence.at_or_above_floor(str(rec.get("tool_id") or "")).get(failure_mode)
        return (0, -j, index) if j is not None else (1, 0.0, index)

    return [rec for _, rec in sorted(enumerate(recs), key=key)]


def assert_floor(payload: Any, evidence: Evidence, tools: dict[str, Any]) -> None:
    """Stop the build if any published recommendation breaks rule 1."""
    problems: list[str] = []

    def visit(node: Any, mode: str | None = None) -> None:
        if isinstance(node, dict):
            tool_id = node.get("tool_id")
            if isinstance(tool_id, str):
                failed = evidence.below_floor(tool_id)
                listed = set(node.get("addresses_failure_modes") or [])
                if mode:
                    listed.add(mode)
                for fm in sorted(listed & set(failed)):
                    problems.append(f"{tool_id} for {fm} (J {failed[fm]:+.2f})")
                if tools.get(tool_id, {}).get("archived") is True:
                    problems.append(f"{tool_id} (archived)")
            for key, value in node.items():
                visit(value, key if key in FAILURE_MODE_IDS else mode)
        elif isinstance(node, list):
            for item in node:
                visit(item, mode)

    visit(payload)
    if problems:
        raise RuntimeError(
            "refusing to publish: the recommender returned picks that SAICA-Bench"
            f" measured below the floor (J {evidence.floor:.2f}) or that are"
            " archived: "
            + "; ".join(sorted(set(problems)))
            + f". See {BACKEND_REQUEST}."
        )


# ---------------------------------------------------------------------------
# Rule 3: sentences that say what was counted
# ---------------------------------------------------------------------------


def describe_block(block: dict[str, Any], evidence: Evidence) -> dict[str, Any]:
    """Rewrite one tier block: annotated tools and a summary that counts
    tags as tags and measurements as measurements."""
    out = dict(block)
    tools = [annotate(t, evidence) for t in block.get("tools") or []]
    out["tools"] = tools
    covered = list(block.get("covered_failure_modes") or [])
    pairs = sum(len(t.get("addresses_failure_modes") or []) for t in tools)
    measured = sum(len(t["measured_j"]) for t in tools)
    out["tagged_pairs"] = pairs
    out["measured_pairs"] = measured
    if not tools:
        out["summary"] = "No eligible tool found."
        return out
    count = f"{len(tools)} tool" + ("" if len(tools) == 1 else "s")
    whose = "Its tags name" if len(tools) == 1 else "Their tags name"
    if measured == 0:
        tested = "none of these tool-mode pairs was measured by SAICA-Bench"
    elif measured == 1:
        tested = (
            f"1 of the {pairs} tool-mode pairs was measured by SAICA-Bench"
            f" (J at or above {evidence.floor:.0%})"
        )
    else:
        tested = (
            f"{measured} of the {pairs} tool-mode pairs were measured by"
            f" SAICA-Bench (J at or above {evidence.floor:.0%})"
        )
    out["summary"] = (
        f"{count}. {whose} {len(covered)} of {len(FAILURE_MODE_IDS)} failure"
        f" modes; {tested}. A tag is the tool's own claim."
    )
    return out


def fmt_j(j: float) -> str:
    """Youden's J as a signed percentage; one decimal when it is small, so
    0.003 reads "+0.3%" and not "+0%"."""
    return f"{j:+.0%}" if abs(j) >= 0.095 else f"{j:+.1%}"


def evidence_phrase(rec: dict[str, Any], failure_mode: str | None = None) -> str:
    """``"measured J +85%"`` for one mode, or the list of measured modes,
    or ``"tag only, not measured"``."""
    measured = rec.get("measured_j") or {}
    if failure_mode is not None:
        j = measured.get(failure_mode)
        return f"measured J {fmt_j(j)}" if j is not None else "tag only, not measured"
    if not measured:
        return "tags only, not measured"
    return "measured: " + ", ".join(
        f"{fm} J {fmt_j(j)}"
        for fm, j in sorted(measured.items(), key=lambda kv: -kv[1])
    )


# ---------------------------------------------------------------------------
# Rule 4: what the ordering score really is
# ---------------------------------------------------------------------------


def popularity_facts(tools: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Describe the per-tool score the recommender multiplies coverage by,
    by probing it rather than by quoting its docstring.

    Returns the adjustment per ``maturity_status``, whether the stars term
    is ``log10(stars + 1)``, the tools whose score contains anything else
    (citations, a trending bonus), and the dates of the star counts.
    """
    from pipeline.shared import priorities

    score = getattr(priorities, "popularity", None) or priorities.reliability
    status_adjustment = {
        s: round(float(score({"stars": 0, "maturity_status": s})), 4) for s in STATUSES
    }
    probe = float(score({"stars": 999, "maturity_status": "stable"}))
    log_stars = abs(probe - status_adjustment["stable"] - 3.0) < 1e-6

    other_terms: dict[str, float] = {}
    dates: list[str] = []
    for tool_id, tool in sorted(tools.items()):
        stars = tool.get("stars")
        stars = float(stars) if isinstance(stars, (int, float)) else 0.0
        status = str(tool.get("maturity_status") or "")
        baseline = float(score({"stars": 0, "maturity_status": status}))
        extra = float(score(tool)) - (math.log10(max(stars, 0.0) + 1.0) + baseline)
        if abs(extra) > 0.005:
            other_terms[tool_id] = round(extra, 2)
        if tool.get("stars_updated_at"):
            dates.append(str(tool["stars_updated_at"])[:10])
    return {
        "name": "popularity",
        "function": f"pipeline.shared.priorities.{score.__name__}",
        "stars_term_is_log10": log_stars,
        "status_adjustment": status_adjustment,
        "tools_with_other_terms": other_terms,
        "stars_dated_from": min(dates) if dates else None,
        "stars_dated_to": max(dates) if dates else None,
    }
