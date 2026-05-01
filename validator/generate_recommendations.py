"""Generate the static SAICA-KG recommendation artifacts.

Writes two files to the repo root:

* ``RECOMMENDATIONS.md`` — human-facing supervisor recommendations,
  segmented by coding agent and by failure mode.
* ``recommendations.json`` — same content in machine-readable form,
  intended to be ``curl``-ed from raw.githubusercontent.com by agents
  that don't speak MCP.

This module is a pure orchestrator: every ranking decision comes from
``pipeline.mcp.recommender.recommend``. We just call it for every coding
agent + an agnostic baseline + once per failure mode for the targeted
view, and lay the results out for humans and machines.

Run from the repo root::

    python -m validator.generate_recommendations          # write the files
    python -m validator.generate_recommendations --check  # CI: diff-only

The MD file embeds the date (no sub-day timestamp) and the KG version so
that running the generator twice on the same KG produces byte-identical
output.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from pipeline.mcp.recommender import (
    ALL_FAILURE_MODES,
    CODING_AGENT_IDS,
    LEVELS,
    RECOMMENDATION_BLOCKLIST,
    recommend,
)
from pipeline.shared.priorities import all_priorities
from pipeline.shared.trending import (
    TRENDING_BOOST,
    trending_repository_urls,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MD_PATH = REPO_ROOT / "RECOMMENDATIONS.md"
DEFAULT_JSON_PATH = REPO_ROOT / "recommendations.json"
MANIFEST_PATH = REPO_ROOT / "data" / "MANIFEST.json"

# Canonical agent display names — keeps the MD headers and quickstart
# entries proofreader-friendly. Anything not in this dict falls back to a
# title-cased version of the id.
_AGENT_DISPLAY_NAMES: dict[str, str] = {
    "cursor": "Cursor",
    "windsurf": "Windsurf",
    "zed-agent": "Zed Agent",
    "replit-agent": "Replit Agent",
    "v0": "v0",
    "devin": "Devin",
    "github-copilot": "GitHub Copilot",
    "continue-dev": "Continue.dev",
    "sourcegraph-cody": "Sourcegraph Cody",
    "claude-code": "Claude Code",
    "aider": "Aider",
    "openhands": "OpenHands",
    "swe-agent": "SWE-agent",
    "codex-cli": "Codex CLI",
    "gemini-cli": "Gemini CLI",
    "cline": "Cline",
}


def _agent_display(agent_id: str) -> str:
    return _AGENT_DISPLAY_NAMES.get(agent_id, agent_id.replace("-", " ").title())


def _failure_mode_display(fm: str) -> str:
    """``security_vulnerability`` → ``Security vulnerability``."""
    return fm.replace("_", " ").capitalize()


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------


def _kg_version() -> str:
    """Return ``kg_version`` from data/MANIFEST.json, or ``"unknown"``."""
    if not MANIFEST_PATH.exists():
        return "unknown"
    try:
        with MANIFEST_PATH.open(encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return "unknown"
    val = doc.get("kg_version")
    return str(val) if val else "unknown"


def build_payload(*, today: str | None = None) -> dict[str, Any]:
    """Run the recommender at all three levels for every agent + agnostic + every FM.

    Returns the JSON-shape payload documented in this module's docstring.
    All ranking is delegated to ``recommender.recommend``; this function
    only orchestrates calls and aggregates results.
    """
    if today is None:
        today = _dt.date.today().isoformat()

    by_agent: dict[str, dict[str, dict[str, Any]]] = {}
    for agent_id in sorted(CODING_AGENT_IDS):
        by_agent[agent_id] = {
            level: recommend(level=level, agent_kind=agent_id) for level in LEVELS
        }

    agnostic: dict[str, dict[str, Any]] = {
        level: recommend(level=level, agent_kind=None) for level in LEVELS
    }

    by_failure_mode: dict[str, list[dict[str, Any]]] = {}
    for fm in ALL_FAILURE_MODES:
        # Targeted with a single FM, agnostic asker so the per-FM tables
        # aren't filtered by any particular coding-agent peer rule.
        targeted = recommend(failure_modes=[fm], agent_kind=None)
        by_failure_mode[fm] = targeted["by_failure_mode"][fm]

    trending_urls = trending_repository_urls()

    return {
        "generated_at": today,
        "kg_version": _kg_version(),
        "trending_count": len(trending_urls),
        "trending_boost": TRENDING_BOOST,
        "blocklist": sorted(RECOMMENDATION_BLOCKLIST),
        "priorities": all_priorities(),
        "by_agent": by_agent,
        "agnostic": agnostic,
        "by_failure_mode": by_failure_mode,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

# Width target for the MD tables. Markdown renderers don't actually care,
# but cap roughly at 80-ish columns so the source file is reviewable.
_TAGLINE_COL_MAX = 70


def _trending_marker(rec: dict[str, Any]) -> str:
    return "\U0001f525" if rec.get("trending") else ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _md_link(rec: dict[str, Any]) -> str:
    """Markdown link to the tool YAML; falls back to plain name on missing id."""
    tid = rec.get("tool_id") or ""
    name = rec.get("tool_name") or tid or "?"
    if not tid:
        return name
    return f"[{name}](data/tools/{tid}.yml)"


def _surfaces(rec: dict[str, Any]) -> str:
    surfaces = rec.get("integration_surfaces") or []
    return ", ".join(str(s) for s in surfaces) if surfaces else "—"


def _stars(rec: dict[str, Any]) -> str:
    val = rec.get("stars")
    if val is None:
        return "—"
    return f"{int(val):,}"


def _coverage_table_header() -> list[str]:
    return [
        "| Tool | Paradigm | Phase | Surfaces | Stars | Trending |",
        "| --- | --- | --- | --- | ---: | :---: |",
    ]


def _why_table_header() -> list[str]:
    return [
        "| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |",
        "| --- | --- | --- | --- | ---: | :---: | --- |",
    ]


def _row(rec: dict[str, Any]) -> str:
    return (
        f"| {_md_link(rec)} "
        f"| {rec.get('control_paradigm') or '—'} "
        f"| {rec.get('temporal_phase') or '—'} "
        f"| {_surfaces(rec)} "
        f"| {_stars(rec)} "
        f"| {_trending_marker(rec)} |"
    )


def _row_with_why(rec: dict[str, Any]) -> str:
    why = _truncate(str(rec.get("tagline") or ""), _TAGLINE_COL_MAX)
    # Escape pipes inside taglines so they don't break the table.
    why = why.replace("|", "\\|")
    return (
        f"| {_md_link(rec)} "
        f"| {rec.get('control_paradigm') or '—'} "
        f"| {rec.get('temporal_phase') or '—'} "
        f"| {_surfaces(rec)} "
        f"| {_stars(rec)} "
        f"| {_trending_marker(rec)} "
        f"| {why} |"
    )


_LEVEL_HEADINGS: dict[str, str] = {
    "minimum": "Minimum (1 tool — best starter)",
    "optimal": "Optimal (3 tools — best responsible kit)",
    "full": "Full / MECE (minimum tools to cover all 11 failure modes)",
}


def _render_level_block(level: str, payload: dict[str, Any]) -> list[str]:
    """Render one of the 3 tier blocks (minimum / optimal / full)."""
    out: list[str] = [f"**{_LEVEL_HEADINGS[level]}** — {payload.get('summary','')}", ""]
    tools = payload.get("tools") or []
    if not tools:
        out.append("_(no eligible tool found at this level)_")
        out.append("")
        return out
    out.extend(_coverage_table_header())
    out.extend(_row(r) for r in tools)
    out.append("")
    if level == "full":
        uncov = payload.get("uncovered_failure_modes") or []
        if uncov:
            out.append(
                f"_Uncovered failure modes (no eligible tool declares coverage): "
                f"`{', '.join(uncov)}`._"
            )
            out.append("")
    return out


def _render_agent_section(
    agent_id: str, levels_payload: dict[str, dict[str, Any]]
) -> list[str]:
    """One ``### If you use **<Agent>**`` block, all three tiers."""
    lines: list[str] = [f"### If you use **{_agent_display(agent_id)}**", ""]
    for level in LEVELS:
        lines.extend(_render_level_block(level, levels_payload[level]))
    return lines


def _render_failure_mode_section(fm: str, recs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = [f"### {_failure_mode_display(fm)}", ""]
    if not recs:
        lines.append("_(no eligible tools declare coverage for this failure mode)_")
        lines.append("")
        return lines
    lines.append(f"Top {len(recs)} supervisors:")
    lines.append("")
    lines.extend(_why_table_header())
    lines.extend(_row_with_why(r) for r in recs)
    lines.append("")
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    """Pure rendering — payload in, MD text out."""
    out: list[str] = []
    out.append("# SAICA-KG — Supervision recommendations")
    out.append("")
    out.append("> Read once at project setup. Don't poll this file per-task.")
    out.append("> For per-action agent guidance, see `SKILLS.md` (drop into your")
    out.append(
        "> `.claude/skills/`, `.cursor/rules/`, or equivalent skills directory)."
    )
    out.append("")
    out.append(
        "Pre-computed from the KG. Regenerate with "
        "`python -m validator.generate_recommendations`."
    )
    out.append(
        f"Last regenerated: {payload['generated_at']} from "
        f"KG version {payload['kg_version']}."
    )
    out.append("")
    out.append(
        "> \U0001f525 marks repos currently on github.com/trending. "
        "Trending tools win ties"
    )
    out.append(
        f"> against non-trending peers with up to ~+30% more raw stars "
        f"(boost = {payload['trending_boost']:.2f}×; see"
    )
    out.append("> `pipeline/shared/trending.py`).")
    out.append("")
    out.append(
        f"This regeneration saw **{payload['trending_count']}** trending "
        f"repositor{'y' if payload['trending_count'] == 1 else 'ies'} "
        f"in `data/trending.json`."
    )
    out.append("")
    out.append("---")
    out.append("")

    # ---- Agent quickstart ----------------------------------------------
    out.append("## Quickstart — pick by which agent you use")
    out.append("")
    out.append(
        "If you already use one of these coding agents, install the "
        "supervisors below for full 11-failure-mode coverage. None of "
        "these are competing coding agents — they all *compose with* "
        "the agent you have."
    )
    out.append("")

    for agent_id in sorted(payload["by_agent"].keys()):
        out.extend(_render_agent_section(agent_id, payload["by_agent"][agent_id]))

    out.append("---")
    out.append("")

    # ---- Agnostic baseline ---------------------------------------------
    out.append("## Agnostic baseline (no specific coding agent)")
    out.append("")
    out.append(
        "If you don't use one of the listed coding agents — or you're "
        "evaluating supervisors without a fixed asker — these are the "
        "three tiers without a peer-coding-agent filter. The blocklist "
        "still applies."
    )
    out.append("")
    for level in LEVELS:
        out.extend(_render_level_block(level, payload["agnostic"][level]))
    out.append("---")
    out.append("")

    # ---- Per-FM quickstart ---------------------------------------------
    out.append("## Quickstart — pick by failure mode")
    out.append("")
    out.append(
        "Top 3 supervisors per failure mode (agnostic; pick the row whose "
        "paradigm and surfaces fit your workflow)."
    )
    out.append("")
    for fm in ALL_FAILURE_MODES:
        out.extend(
            _render_failure_mode_section(fm, payload["by_failure_mode"].get(fm, []))
        )

    out.append("---")
    out.append("")

    # ---- Methodology ---------------------------------------------------
    out.append("## Methodology")
    out.append("")
    out.append(
        "Selection is by **likelihood × impact × reliability**. Per-FM "
        "likelihood and impact live in `data/failure_mode_priorities.yml` "
        "(hybrid: KG tool-coverage prior + editorial calibration against "
        "Shah 2026 / DAPLab evidence). Reliability is a bounded combiner "
        "of log-stars, github-trending bump, citation count, and maturity."
    )
    out.append("")
    out.append("Three tiers per asker:")
    out.append("")
    out.append(
        "- **Minimum (1 tool)** — single tool maximising "
        "Σ priority(fm) over its addressed FMs × its reliability."
    )
    out.append("- **Optimal (3 tools)** — greedy weighted set cover capped at 3.")
    out.append(
        "- **Full / MECE** — greedy weighted set cover until every FM is "
        "covered (no pad). Typically 4-5 tools."
    )
    out.append("")
    out.append(
        "Coding-agent peers are filtered out per asker (the user has a "
        "coding agent already; we recommend supervisors, not peers)."
    )
    blocklist = ", ".join(f"`{b}`" for b in payload.get("blocklist", []))
    out.append(
        f"The blocklist (currently: {blocklist or '_empty_'}) excludes "
        "tools whose role is too ambiguous."
    )
    out.append("")
    out.append("Priority order (likelihood × impact, descending):")
    out.append("")
    out.append("| Failure mode | priority |")
    out.append("| --- | ---: |")
    for fm, p in payload.get("priorities", {}).items():
        out.append(f"| `{fm}` | {p:.2f} |")
    out.append("")
    out.append(
        "This file is regenerated from `data/tools/*.yml` and "
        "`data/failure_mode_priorities.yml` by "
        "`validator/generate_recommendations.py`."
    )
    out.append("")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _serialize_json(payload: dict[str, Any]) -> str:
    """JSON dump with stable key ordering and a trailing newline."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_outputs(payload: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    md_path = out_dir / "RECOMMENDATIONS.md"
    json_path = out_dir / "recommendations.json"
    md_text = render_markdown(payload)
    if not md_text.endswith("\n"):
        md_text += "\n"
    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(_serialize_json(payload), encoding="utf-8")
    return md_path, json_path


def _check_outputs(payload: dict[str, Any], out_dir: Path) -> int:
    """Compare on-disk files to freshly rendered. Return exit code."""
    md_path = out_dir / "RECOMMENDATIONS.md"
    json_path = out_dir / "recommendations.json"
    expected_md = render_markdown(payload)
    if not expected_md.endswith("\n"):
        expected_md += "\n"
    expected_json = _serialize_json(payload)
    diffs: list[str] = []
    if not md_path.exists() or md_path.read_text(encoding="utf-8") != expected_md:
        diffs.append(str(md_path))
    if not json_path.exists() or json_path.read_text(encoding="utf-8") != expected_json:
        diffs.append(str(json_path))
    if diffs:
        sys.stderr.write(
            "generate_recommendations --check: out-of-date files:\n  "
            + "\n  ".join(diffs)
            + "\nRun `python -m validator.generate_recommendations` to regenerate.\n"
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate_recommendations",
        description=(
            "Regenerate RECOMMENDATIONS.md and recommendations.json from " "the KG."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Verify the committed files match what would be regenerated; "
            "exit 1 on diff."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT,
        help="Override the output directory (default: repo root).",
    )
    args = parser.parse_args(argv)

    payload = build_payload()

    if args.check:
        return _check_outputs(payload, args.out_dir)

    md_path, json_path = _write_outputs(payload, args.out_dir)
    sys.stdout.write(f"wrote {md_path}\nwrote {json_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
