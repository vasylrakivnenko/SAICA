"""Generate the static tool-suggestion files from the catalogue.

Writes two files to the repo root:

* ``RECOMMENDATIONS.md`` — for people;
* ``recommendations.json`` — the same content for programs.

What the files are: lists built from the catalogue's tags (what each tool
says it addresses), ordered by an editorial priority per failure mode and
by the tool's popularity. They are not benchmark results. Where
SAICA-Bench measured a tool on a mode the J is printed, and a tool is
never listed for a mode where it measured below the site's floor
(``validator/_recommend.py`` enforces this and stops the build otherwise).

The selection itself comes from ``pipeline.mcp.recommender.recommend``;
this module calls it, reorders within a mode so measured tools come first,
rewrites the summaries so they count tags as tags, and lays the result out.

Run from the repo root::

    python -m validator.generate_recommendations                  # write the files
    python -m validator.generate_recommendations --check          # CI: compare only
    python -m validator.generate_recommendations --out-dir /tmp/x # write elsewhere

The files carry the date of ``data/MANIFEST.json``, not today's date, so
two runs on the same repository state give byte-identical output and
``--check`` gives the same answer on every day. Regenerate after the
manifest, the tool files or ``site/public/bench/results.json`` change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pipeline.mcp.recommender import (
    CODING_AGENT_IDS,
    LEVELS,
    RECOMMENDATION_BLOCKLIST,
    recommend,
    recommend_for_failure_modes,
)
from pipeline.models import FAILURE_MODE_IDS
from pipeline.shared.priorities import all_priorities
from validator._recommend import (
    KIT_BUILDER_URL,
    annotate,
    assert_floor,
    catalogue_tools,
    describe_block,
    evidence_phrase,
    fmt_j,
    kg_stamp,
    measured_first,
    measured_recommender,
    popularity_facts,
    priorities_label,
    removed_pairs,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MD_PATH = REPO_ROOT / "RECOMMENDATIONS.md"
DEFAULT_JSON_PATH = REPO_ROOT / "recommendations.json"

# Tools listed per failure mode.
PER_MODE = 3

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


def build_payload(*, as_of: str | None = None) -> dict[str, Any]:
    """Run the recommender at all three levels for every agent + agnostic +
    every failure mode, through the measured view.

    ``as_of`` is the date printed in the files; it defaults to the date of
    ``data/MANIFEST.json`` and never to the clock.
    """
    kg_version, manifest_date = kg_stamp()
    if as_of is None:
        as_of = manifest_date

    tools = catalogue_tools()
    with measured_recommender() as evidence:
        by_agent: dict[str, dict[str, dict[str, Any]]] = {}
        for agent_id in sorted(CODING_AGENT_IDS):
            by_agent[agent_id] = {
                level: describe_block(
                    recommend(level=level, agent_kind=agent_id), evidence
                )
                for level in LEVELS
            }

        agnostic: dict[str, dict[str, Any]] = {
            level: describe_block(recommend(level=level, agent_kind=None), evidence)
            for level in LEVELS
        }

        by_failure_mode: dict[str, list[dict[str, Any]]] = {}
        for fm in FAILURE_MODE_IDS:
            # Every eligible tool tagged for the mode, in the recommender's
            # order; measured ones are then moved to the front.
            targeted = recommend_for_failure_modes([fm], agent_kind=None, per_fm=10_000)
            ranked = measured_first(targeted["by_failure_mode"][fm], fm, evidence)
            by_failure_mode[fm] = [annotate(r, evidence) for r in ranked[:PER_MODE]]

    payload = {
        "as_of": as_of,
        "kg_version": kg_version,
        "bench": {
            "source": evidence.source,
            "results_generated": evidence.generated,
            "floor": evidence.floor,
            "measured_tools": evidence.measured_tools,
            "unmapped_modes": list(evidence.unmapped_modes),
        },
        "not_listed": removed_pairs(tools, evidence),
        "popularity": popularity_facts(tools),
        "blocklist": sorted(RECOMMENDATION_BLOCKLIST),
        "priorities": all_priorities(),
        "priorities_label": priorities_label(),
        "by_agent": by_agent,
        "agnostic": agnostic,
        "by_failure_mode": by_failure_mode,
    }
    assert_floor(
        {k: payload[k] for k in ("by_agent", "agnostic", "by_failure_mode")},
        evidence,
        tools,
    )
    return payload


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

# Width target for the MD tables. Markdown renderers don't actually care,
# but cap roughly at 80-ish columns so the source file is reviewable.
_TAGLINE_COL_MAX = 70


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
        "| Tool | Paradigm | Phase | Surfaces | Stars | Tagged for | Measured |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]


def _why_table_header() -> list[str]:
    return [
        "| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]


def _row(rec: dict[str, Any]) -> str:
    tagged = ", ".join(f"`{fm}`" for fm in rec.get("addresses_failure_modes") or [])
    measured = evidence_phrase(rec)
    measured = (
        "—" if measured.startswith("tags only") else measured[len("measured: ") :]
    )
    return (
        f"| {_md_link(rec)} "
        f"| {rec.get('control_paradigm') or '—'} "
        f"| {rec.get('temporal_phase') or '—'} "
        f"| {_surfaces(rec)} "
        f"| {_stars(rec)} "
        f"| {tagged or '—'} "
        f"| {measured} |"
    )


def _row_with_why(rec: dict[str, Any], fm: str) -> str:
    why = _truncate(str(rec.get("tagline") or ""), _TAGLINE_COL_MAX)
    # Escape pipes inside taglines so they don't break the table.
    why = why.replace("|", "\\|")
    return (
        f"| {_md_link(rec)} "
        f"| {evidence_phrase(rec, fm)} "
        f"| {rec.get('control_paradigm') or '—'} "
        f"| {rec.get('temporal_phase') or '—'} "
        f"| {_surfaces(rec)} "
        f"| {_stars(rec)} "
        f"| {why} |"
    )


_LEVEL_HEADINGS: dict[str, str] = {
    "minimum": "One tool (`minimum`)",
    "optimal": "Three tools (`optimal`)",
    "full": "Widest reach of tags with the fewest tools (`full`)",
}


def _render_level_block(level: str, payload: dict[str, Any]) -> list[str]:
    """Render one of the three stacks (minimum / optimal / full)."""
    out: list[str] = [f"**{_LEVEL_HEADINGS[level]}** — {payload.get('summary','')}", ""]
    tools = payload.get("tools") or []
    if not tools:
        out.append("_(no eligible tool found at this level)_")
        out.append("")
        return out
    out.extend(_coverage_table_header())
    out.extend(_row(r) for r in tools)
    out.append("")
    uncov = payload.get("uncovered_failure_modes") or []
    if level == "full" and uncov:
        out.append(
            "_No eligible tool is tagged for: "
            + ", ".join(f"`{u}`" for u in uncov)
            + " (tools measured below the floor on a mode do not count for it)._"
        )
        out.append("")
    return out


def _render_agent_section(
    agent_id: str, levels_payload: dict[str, dict[str, Any]]
) -> list[str]:
    """One ``### If you use **<Agent>**`` block, all three stacks."""
    lines: list[str] = [f"### If you use **{_agent_display(agent_id)}**", ""]
    for level in LEVELS:
        lines.extend(_render_level_block(level, levels_payload[level]))
    return lines


def _render_failure_mode_section(fm: str, recs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = [f"### {_failure_mode_display(fm)}", ""]
    if not recs:
        lines.append(
            "_(no eligible tool is tagged for this failure mode, or every tagged"
            " tool measured below the floor)_"
        )
        lines.append("")
        return lines
    lines.extend(_why_table_header())
    lines.extend(_row_with_why(r, fm) for r in recs)
    lines.append("")
    return lines


def _same_picks(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two tier blocks list the same tools in the same order."""
    return [t.get("tool_id") for t in a.get("tools") or []] == [
        t.get("tool_id") for t in b.get("tools") or []
    ]


def _render_not_listed(payload: dict[str, Any]) -> list[str]:
    rows = payload.get("not_listed") or []
    floor = payload["bench"]["floor"]
    out = ["## Tagged, measured, not listed", ""]
    if not rows:
        out.append(
            "No tagged tool-mode pair has a measured J below the floor"
            f" ({floor:.0%}) in the current results."
        )
        out.append("")
        return out
    out.append(
        f"These tools are tagged for the mode in the catalogue, but SAICA-Bench"
        f" measured them below J {floor:.0%} on it (or their repository is"
        " archived), so no list in this file names them for that mode."
    )
    out.append("")
    out.append("| Tool | Failure mode | Why not listed |")
    out.append("| --- | --- | --- |")
    for row in rows:
        why = (
            f"measured J {fmt_j(row['j'])}"
            if "j" in row
            else "upstream repository is archived"
        )
        out.append(
            f"| [{row['tool_id']}](data/tools/{row['tool_id']}.yml) "
            f"| `{row['failure_mode']}` | {why} |"
        )
    out.append("")
    return out


def _render_method(payload: dict[str, Any]) -> list[str]:
    pop = payload.get("popularity") or {}
    bench = payload["bench"]
    out = ["## Method", ""]
    out.append(
        "Each failure mode has a weight (likelihood × impact) in"
        " `data/failure_mode_priorities.yml`, which describes its own numbers"
        f" as: \"{payload.get('priorities_label')}\". They were set by hand;"
        " no likelihood comes from a count of real failures."
    )
    out.append("")
    adj = pop.get("status_adjustment") or {}
    adj_text = ", ".join(f"{s} {v:+.1f}" for s, v in adj.items())
    stars_text = (
        "log10(GitHub stars + 1)"
        if pop.get("stars_term_is_log10")
        else "a function of GitHub stars"
    )
    out.append(
        f"Each tool has a **popularity** score: {stars_text} plus an adjustment"
        f" for the curated `maturity_status` ({adj_text}). It says how widely a"
        " tool is used, not how well it works."
    )
    if pop.get("stars_dated_from"):
        out.append(
            f"Star counts in the tool files date from {pop['stars_dated_from']}"
            f" to {pop['stars_dated_to']}."
        )
    others = pop.get("tools_with_other_terms") or {}
    if others:
        listed = ", ".join(f"`{t}` {v:+.2f}" for t, v in others.items())
        out.append(
            f"For {len(others)} tool(s) the score in the code"
            f" (`{pop.get('function')}`) also contains a term beyond stars and"
            f" status (a bonus per citing paper or for a trending repository):"
            f" {listed}."
        )
    out.append("")
    out.append("The three stacks:")
    out.append("")
    out.append(
        "- **`minimum`** — the one tool with the largest sum of weights over"
        " its tagged modes × (1 + popularity)."
    )
    out.append(
        "- **`optimal`** — three tools picked one after another by the same"
        " score, each time counting only modes not yet reached."
    )
    out.append(
        "- **`full`** — the same greedy pick, continued until no eligible"
        " tool adds a mode."
    )
    out.append("")
    out.append(
        "Per failure mode: tools with a measured J at or above the floor come"
        " first, highest J first. Then tools with a tag only, in the"
        " recommender's order: prevention and detection before correction and"
        " recovery, then tools whose rationale text names the mode, then stars."
    )
    out.append("")
    out.append(
        f"Measured results: `{bench.get('source') or 'no results file found'}`"
        f", generated {bench.get('results_generated') or 'unknown'}; "
        f"{len(bench.get('measured_tools') or [])} catalogue tools have at"
        f" least one measured row; floor J {bench['floor']:.0%}."
    )
    if bench.get("unmapped_modes"):
        out.append(
            "Benchmark modes that could not be matched to a failure mode and"
            " were therefore not used: "
            + ", ".join(f"`{m}`" for m in bench["unmapped_modes"])
            + "."
        )
    out.append("")
    blocklist = ", ".join(f"`{b}`" for b in payload.get("blocklist", []))
    out.append(
        f"Never listed, whatever their tags: {blocklist or '_nothing_'}"
        " (role too unclear to suggest)."
    )
    out.append("")
    out.append("Weight per failure mode (likelihood × impact, descending):")
    out.append("")
    out.append("| Failure mode | weight |")
    out.append("| --- | ---: |")
    for fm, p in payload.get("priorities", {}).items():
        out.append(f"| `{fm}` | {p:.2f} |")
    out.append("")
    out.append(
        "This file is regenerated from `data/tools/*.yml`,"
        " `data/failure_mode_priorities.yml` and the benchmark results by"
        " `validator/generate_recommendations.py`."
    )
    out.append("")
    return out


def render_markdown(payload: dict[str, Any]) -> str:
    """Pure rendering — payload in, MD text out."""
    bench = payload["bench"]
    out: list[str] = []
    out.append("# SAICA-KG — Tool suggestions from the catalogue")
    out.append("")
    out.append("> These lists come from the catalogue's **tags**: what each tool's own")
    out.append(
        "> documentation says it addresses. A tag is a claim, not a measurement."
    )
    out.append("> Where SAICA-Bench measured a tool on a failure mode, the J is shown,")
    out.append(
        f"> and a tool is never listed for a mode where it measured below J {bench['floor']:.0%}."
    )
    out.append(f"> For picks built from measured results only, use {KIT_BUILDER_URL}.")
    out.append("")
    out.append(
        "Pre-computed. Regenerate with "
        "`python -m validator.generate_recommendations`."
    )
    out.append(
        f"Generated from KG version {payload['kg_version']} (manifest of "
        f"{payload['as_of']}); benchmark results of "
        f"{bench.get('results_generated') or 'unknown date'}."
    )
    out.append("")
    out.append("---")
    out.append("")

    # ---- The three stacks -----------------------------------------------
    out.append("## Three stacks by tag coverage")
    out.append("")
    out.append(
        "Tools are picked for how many weighted failure modes their tags"
        " name, times their popularity. See Method at the end."
    )
    out.append("")
    for level in LEVELS:
        out.extend(_render_level_block(level, payload["agnostic"][level]))

    # ---- Per coding agent -----------------------------------------------
    differing = {
        agent_id: levels
        for agent_id, levels in sorted(payload["by_agent"].items())
        if not all(
            _same_picks(levels[level], payload["agnostic"][level]) for level in LEVELS
        )
    }
    out.append("## By coding agent")
    out.append("")
    if not differing:
        out.append(
            f"The picks are the same for all {len(payload['by_agent'])} coding"
            " agents the recommender knows by name (Cursor, Claude Code, Codex"
            " CLI and others): no coding agent is in the catalogue, so there"
            " is nothing to filter out for any of them."
        )
        out.append("")
    else:
        out.append(
            "A coding agent is never suggested to itself or to another coding"
            " agent. Agents whose picks differ from the stacks above:"
        )
        out.append("")
        for agent_id, levels in differing.items():
            out.extend(_render_agent_section(agent_id, levels))
    out.append("---")
    out.append("")

    # ---- Per failure mode ------------------------------------------------
    out.append("## By failure mode")
    out.append("")
    out.append(
        f"Up to {PER_MODE} tools per failure mode. Measured tools first; a row"
        ' that says "tag only" has not been tested on this mode.'
    )
    out.append("")
    for fm in FAILURE_MODE_IDS:
        out.extend(
            _render_failure_mode_section(fm, payload["by_failure_mode"].get(fm, []))
        )

    out.append("---")
    out.append("")
    out.extend(_render_not_listed(payload))
    out.append("---")
    out.append("")
    out.extend(_render_method(payload))

    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _serialize_json(payload: dict[str, Any]) -> str:
    """JSON dump with stable key ordering and a trailing newline."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_outputs(payload: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
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
