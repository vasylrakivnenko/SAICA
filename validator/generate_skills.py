"""Generate ``SKILLS.md`` — the SAICA-KG agent-context skill file.

Background
----------
SAICA-KG is a *curated knowledge corpus*, not a runtime service. The
practical way agents consume it is via injection into their context
(``.claude/skills/``, ``.cursor/rules/``, Replit's skills directory,
etc.) — not by RPC. This generator distils the highest-priority
material (failure-mode descriptions, detection signals, top supervisor
recommendations, real-world incidents, hand-coded pre-action heuristics)
into a single Markdown file that drops cleanly into any of those
context-injection spots.

It mirrors ``validator/generate_recommendations.py``:

* ``build_payload(today=None) → dict`` — pure data assembly, calls into
  the existing recommender + priorities helpers.
* ``render_markdown(payload) → str`` — pure rendering.
* ``_write_outputs(payload, out_dir)`` / ``_check_outputs(payload, out_dir)``
  for ``--check`` mode.
* ``main(argv)`` with argparse: ``--check``, ``--out-dir <path>``.

Idempotent: running twice on identical KG state yields byte-identical
output.

Run from the repo root::

    python -m validator.generate_skills          # write SKILLS.md
    python -m validator.generate_skills --check  # CI: diff-only
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from pipeline.mcp.recommender import (
    recommend_for_failure_modes,
    recommend_full,
    recommend_minimum,
    recommend_optimal,
)
from pipeline.shared.priorities import all_priorities

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MD_PATH = REPO_ROOT / "SKILLS.md"
MANIFEST_PATH = REPO_ROOT / "data" / "MANIFEST.json"
FM_DIR = REPO_ROOT / "data" / "failure_modes"
INCIDENT_DIR = REPO_ROOT / "data" / "incidents"

# How many supervisors to surface per FM. Two is enough for skim-reading
# without turning the file into a directory dump; users who want more
# should consult RECOMMENDATIONS.md.
_TOP_SUPERVISORS_PER_FM: int = 2

# Reproducibility tier ordering — higher = preferred when picking the
# "headline" incident per FM.
_REPRO_RANK: dict[str, int] = {
    "confirmed": 3,
    "plausible": 2,
    "anecdotal": 1,
}


# ---------------------------------------------------------------------------
# Pre-action heuristics — hand-curated. The most important content in the
# file: agents reading SKILLS.md need a concrete "before you do X, do Y"
# rule per FM. Generic advice is useless; these must be specific.
# ---------------------------------------------------------------------------

_PRE_ACTION_HEURISTICS: dict[str, str] = {
    "scope_creep": (
        "If you're about to edit a file the user did not name, install a "
        "package they did not ask for, or chain follow-on cleanup that "
        "wasn't requested, **stop and ask first**. Surface the unrelated "
        "issue in your reply but don't auto-fix it."
    ),
    "fabrication": (
        "If you're about to import a package or call an API you didn't see "
        "in the existing `requirements.txt` / `package.json` / `go.mod`, "
        "first verify it actually exists — check the lockfile, run "
        "`pip show` / `npm view`, or grep the codebase. Never invent "
        "package names; if unsure, ask the user which library they want."
    ),
    "security_vulnerability": (
        "If you're about to write SQL, shell, HTML/template, or auth code, "
        "first check whether the surrounding code uses parameterised "
        "queries, escaped templates, and a vetted crypto library. Match "
        "those patterns. Never hardcode secrets — read them from env/"
        "config. Run a static analyser (semgrep, bandit) on the diff if "
        "available."
    ),
    "supply_chain_attack": (
        "If you're about to run `pip install <name>` / `npm install "
        "<name>` for a package not already in the lockfile, first "
        "confirm the package exists on the public registry, has a "
        "non-trivial download history, and matches the spelling the user "
        "or docs gave you. Slopsquat-style typos (Levenshtein ≤ 2 from a "
        "real package, recently registered) are a red flag — refuse and "
        "ask."
    ),
    "logic_error": (
        "If you're about to claim a function works, run its tests (or "
        "a quick sandbox invocation with representative inputs) before "
        'saying so. "Type-checks clean" ≠ "correct". Property-based '
        "or boundary-case checks beat happy-path-only assertions."
    ),
    "cascading_failure": (
        "If your last fix attempt produced a *different* error than the "
        "previous one — and that's now happened twice — **stop iterating** "
        "and summarise the spiral for the user. Recovery loops compound; "
        "the third attempt rarely converges. Revert to a known-good "
        "state instead of layering more changes."
    ),
    "context_pollution": (
        "If you find yourself referencing facts, file paths, or symbols "
        "that you can't trace back to the user's prompt or an actual tool "
        "output earlier in the session, **re-ground**. Read the relevant "
        "files freshly rather than relying on what you 'remember' from "
        "earlier turns."
    ),
    "obsolescence": (
        "If you're emitting code against a fast-moving library "
        "(framework, ORM, cloud SDK, ML lib), first check the project's "
        "pinned version and the library's current release notes. Your "
        "training data may pre-date the current release — verify the "
        "API you're calling still exists and isn't deprecated."
    ),
    "test_manipulation": (
        "If a test is failing, **never edit the test to make it pass** "
        "unless the user has explicitly said the test itself is wrong. "
        "Don't add `pytest.mark.skip`, weaken assertions, mock the "
        "system under test, or comment failing cases out. Fix the code, "
        "or report the failure honestly and ask."
    ),
    "dependency_blindness": (
        "Before writing a utility function from scratch, grep the repo "
        "and skim the declared dependencies for an existing equivalent. "
        "Reimplementing `urljoin`, `dataclass`, retry-with-backoff, etc. "
        "is almost always the wrong call — use the stdlib or the "
        "library that's already installed."
    ),
    "incomplete_execution": (
        'Before claiming "done", grep your own diff for `TODO`, `FIXME`, '
        "`NotImplementedError`, bare `pass`, and `...` — and verify each "
        "subtask the user named is actually implemented (not just stubbed "
        "with a docstring). If something is incomplete, say so explicitly "
        "rather than declaring success."
    ),
}


# ---------------------------------------------------------------------------
# KG access
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


def _priorities_version() -> str:
    """Return the version field from data/failure_mode_priorities.yml."""
    path = REPO_ROOT / "data" / "failure_mode_priorities.yml"
    if not path.exists():
        return "unknown"
    with path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    val = (doc or {}).get("version")
    return str(val) if val is not None else "unknown"


def _load_failure_modes() -> dict[str, dict[str, Any]]:
    """Load all FM YAMLs as a dict keyed by id."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(glob.glob(str(FM_DIR / "*.yml"))):
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        if isinstance(doc, dict) and doc.get("id"):
            out[str(doc["id"])] = doc
    return out


def _load_incidents() -> list[dict[str, Any]]:
    """Load all incident YAMLs as a list."""
    out: list[dict[str, Any]] = []
    for path in sorted(glob.glob(str(INCIDENT_DIR / "*.yml"))):
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        if isinstance(doc, dict) and doc.get("id"):
            out.append(doc)
    return out


def _pick_headline_incident(
    fm_id: str, incidents: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Pick the most authoritative incident for ``fm_id``.

    Highest reproducibility tier wins; ties broken by most-recent
    ``incident_date``. Returns ``None`` if no incident lists this FM.
    """
    candidates = [
        inc for inc in incidents if fm_id in (inc.get("exhibited_failure_modes") or [])
    ]
    if not candidates:
        return None

    def _key(inc: dict[str, Any]) -> tuple[int, str]:
        repro = str(inc.get("reproducibility") or "anecdotal").lower()
        date = str(inc.get("incident_date") or "")
        return (_REPRO_RANK.get(repro, 0), date)

    candidates.sort(key=_key, reverse=True)
    return candidates[0]


def _normalize_text(text: str) -> str:
    """Collapse YAML folded-block whitespace into a single line."""
    return " ".join((text or "").split()).strip()


def _truncate(text: str, limit: int) -> str:
    text = _normalize_text(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------


def build_payload(*, today: str | None = None) -> dict[str, Any]:
    """Assemble per-FM data for SKILLS.md rendering.

    Per-FM ordering is priority-descending (from
    :func:`pipeline.shared.priorities.all_priorities`). Within each FM,
    the supervisor recommendations come from
    :func:`recommend_for_failure_modes` (agnostic asker, top 2).
    """
    if today is None:
        today = _dt.date.today().isoformat()

    fms = _load_failure_modes()
    incidents = _load_incidents()
    incident_index = {str(inc.get("id")): inc for inc in incidents}
    priorities = all_priorities()  # already sorted desc

    # Order the FMs by priority desc, but only those that exist in the FM
    # YAMLs — the priorities YAML and the FM YAMLs should match, but be
    # defensive in case one drifts ahead of the other.
    ordered_fms = [fm for fm in priorities if fm in fms]
    # Append any FM YAML the priorities file doesn't know about, sorted
    # for stability — keeps the file deterministic.
    ordered_fms += sorted(set(fms) - set(ordered_fms))

    fm_blocks: list[dict[str, Any]] = []
    for fm_id in ordered_fms:
        fm_doc = fms[fm_id]

        # Top 2 supervisors for this FM, agnostic.
        rec_payload = recommend_for_failure_modes(
            [fm_id],
            agent_kind=None,
            per_fm=_TOP_SUPERVISORS_PER_FM,
        )
        supervisors = list(rec_payload["by_failure_mode"].get(fm_id, []))

        # Headline incident, if any.
        incident = _pick_headline_incident(fm_id, incidents)
        incident_block: dict[str, Any] | None = None
        if incident is not None:
            incident_block = {
                "id": str(incident.get("id")),
                "tagline": _normalize_text(str(incident.get("tagline") or "")),
                "summary": _normalize_text(
                    str(incident.get("summary") or incident.get("description") or "")
                ),
                "incident_date": str(incident.get("incident_date") or ""),
            }

        fm_blocks.append(
            {
                "id": fm_id,
                "name": str(fm_doc.get("name") or fm_id),
                "description": _normalize_text(str(fm_doc.get("description") or "")),
                "detection_signals": list(fm_doc.get("detection_signals") or []),
                "supervisors": supervisors,
                "incident": incident_block,
                "heuristic": _PRE_ACTION_HEURISTICS.get(fm_id, ""),
                "priority": float(priorities.get(fm_id, 0.0)),
            }
        )

    # Three pre-baked recommendation tiers (agnostic, no agent-kind
    # filter). v0.6: these used to be served by the MCP server's
    # ``saica_recommend`` tool; baking them into the skill removes the
    # marketplace plugin's runtime dependency on Python.
    tiers = {
        "minimum": recommend_minimum(agent_kind=None),
        "optimal": recommend_optimal(agent_kind=None),
        "full": recommend_full(agent_kind=None),
    }

    # Sanity index used by tests — every (incident_id, tool_id) we cite
    # must resolve in the KG. Caller-side asserts use these.
    return {
        "generated_at": today,
        "kg_version": _kg_version(),
        "priorities_version": _priorities_version(),
        "failure_modes": fm_blocks,
        "tiers": tiers,
        "_incident_index_keys": sorted(incident_index.keys()),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _supervisor_line(rec: dict[str, Any]) -> str:
    """Render one supervisor as a bullet line."""
    tid = rec.get("tool_id") or ""
    name = rec.get("tool_name") or tid or "?"
    paradigm = rec.get("control_paradigm") or "—"
    phase = rec.get("temporal_phase") or "—"
    surfaces = rec.get("integration_surfaces") or []
    surfaces_str = ", ".join(str(s) for s in surfaces) if surfaces else "—"
    tagline = _truncate(str(rec.get("tagline") or ""), 110)
    name_link = f"[`{tid}`](data/tools/{tid}.yml)" if tid else f"`{name}`"
    return (
        f"- {name_link} — {paradigm}/{phase}, surfaces: {surfaces_str}; " f"{tagline}"
    )


def _render_tier(level: str, payload: dict[str, Any]) -> list[str]:
    """Render one tier (minimum / optimal / full) as a Markdown sub-section.

    Each tier carries a ``summary`` line, the list of recommended
    supervisors, and (for the ``full`` tier) the union of failure
    modes covered. Pre-baked into SKILL.md by v0.6 so the agent can
    consult the recommendation without an MCP roundtrip.
    """
    out: list[str] = []
    out.append(f"### `{level}` tier")
    out.append("")
    summary = payload.get("summary")
    if summary:
        out.append(f"_{summary}_")
        out.append("")
    tools = payload.get("tools") or []
    if not tools:
        out.append("- _(no tools — recommender returned empty for this tier)_")
        out.append("")
        return out
    for t in tools:
        out.append(_supervisor_line(t))
    out.append("")
    covered = payload.get("covered_failure_modes") or []
    if level == "full" and covered:
        out.append(
            f"Covers {len(covered)} of 11 failure modes: "
            + ", ".join(f"`{c}`" for c in covered)
            + "."
        )
        out.append("")
    return out


def _render_tiers_section(tiers: dict[str, Any]) -> list[str]:
    out: list[str] = []
    out.append("## Recommended supervision stack — three tiers")
    out.append("")
    out.append(
        "Pre-baked from the SAICA-KG corpus. Pick a tier that matches "
        "the team's appetite. Same picks the MCP server would return "
        "from `saica_recommend(level=...)` — embedded here so no "
        "runtime service call is needed."
    )
    out.append("")
    out.append("- **`minimum`** — the single best tool to start with.")
    out.append("- **`optimal`** — three tools, the responsible default.")
    out.append(
        "- **`full`** — the minimum set that covers all 11 failure " "modes (MECE)."
    )
    out.append("")
    for level in ("minimum", "optimal", "full"):
        body = tiers.get(level)
        if not isinstance(body, dict):
            continue
        out.extend(_render_tier(level, body))
    return out


def _render_failure_mode(fm: dict[str, Any]) -> list[str]:
    out: list[str] = []
    out.append(f"### `{fm['id']}` — {fm['name']}")
    out.append("")
    out.append(f"**What it is:** {fm['description']}")
    out.append("")
    out.append("**Detection signals (from `data/failure_modes/" f"{fm['id']}.yml`):**")
    for sig in fm["detection_signals"]:
        out.append(f"- {sig}")
    out.append("")

    incident = fm.get("incident")
    if incident:
        # Keep the snippet short — full details live in the YAML.
        summary_short = _truncate(incident["summary"], 220)
        out.append(
            f"**Real incident:** \"{incident['tagline']}\" — "
            f"{summary_short} [`{incident['id']}`]"
        )
    else:
        out.append("**Real incident:** no documented incident yet.")
    out.append("")

    out.append(
        "**Recommended supervisors "
        f"(from `saica_recommend(failure_modes=['{fm['id']}'])`):**"
    )
    if fm["supervisors"]:
        for rec in fm["supervisors"]:
            out.append(_supervisor_line(rec))
    else:
        out.append(
            "- _(no eligible supervisor declares coverage; see "
            "RECOMMENDATIONS.md for the agnostic baseline)_"
        )
    out.append("")

    out.append("**Pre-action heuristic for an agent:**")
    heuristic = fm.get("heuristic") or (
        "Pause before acting and re-read the user's request to confirm "
        "this action is in scope and grounded."
    )
    out.append(f"> {heuristic}")
    out.append("")
    return out


_WORKING_AGREEMENT_BULLETS: list[str] = [
    "**Plan first** for changes >50 LOC or touching >3 files. State "
    "the plan before editing — small, single-file changes can skip "
    "this but must still respect the scope rule below.",
    "**Default to read-only investigation before edits.** Read the "
    "file, run the test, grep the codebase — *then* plan the diff.",
    "**Only edit files relevant to the requested task.** If you spot "
    "an unrelated issue (typo, lint warning, stale TODO), surface it "
    "in your reply but **do not auto-fix unless asked** "
    "(`scope_creep`).",
    "**Pre-commit must pass.** Never bypass with `--no-verify`, "
    "`--no-gpg-sign`, or analogous escape hatches unless the user "
    "explicitly authorises it. If a hook denies, fix the underlying "
    "issue and re-stage; do not skip (`incomplete_execution`).",
    "**Use the failure-mode vocabulary** when surfacing supervision "
    "concerns. Quote the snake_case IDs (`scope_creep`, "
    "`fabrication`, `test_manipulation`, …) verbatim — they are the "
    "stable interface to this corpus.",
    "**Cite incident IDs** when warning a user about a known failure "
    "pattern. e.g. `[replit-agent-saastr-database-deletion-2025]` "
    "for autonomous destructive DB ops, "
    "`[huggingface-cli-slopsquat-lanyado-2024]` for slopsquatting. "
    "An agent with KG access can resolve them.",
    "**Never run destructive shell commands** (`rm -rf`, `git push "
    "--force`, `DROP TABLE`, `git reset --hard`, `chmod -R`) without "
    "explicit per-instance authorisation. Code-freeze and "
    "production-data labels are absolute.",
    "**When in doubt, ask.** A clarifying question costs less than "
    "unwinding an out-of-scope or destructive edit — especially in "
    "agentic-AI workflows whose stated mission is to study exactly "
    "these failure modes.",
]


def render_markdown(payload: dict[str, Any]) -> str:
    """Pure rendering — payload in, MD text out."""
    out: list[str] = []

    # ---- Title + framing ------------------------------------------------
    out.append("# SAICA-KG — Agent skills file")
    out.append("")
    out.append(
        "You are reading this because a human dropped this file into your "
        "skills / rules / context directory. It distils the SAICA-KG corpus"
    )
    out.append(
        "(https://github.com/vasylrakivnenko/SAICA) into actionable "
        "guidance for when you're writing or modifying code. Use it as "
        "context, not as a"
    )
    out.append(
        "service to call. Treat the failure-mode IDs (snake_case) as the "
        "canonical vocabulary."
    )
    out.append("")

    # ---- How to use this file -------------------------------------------
    out.append("## How this file is meant to be used")
    out.append("")
    out.append(
        "- Drop into `.claude/skills/saica-kg.md`, "
        "`.cursor/rules/saica-kg.md`, Replit's skills directory, or any "
        "equivalent context-injection spot."
    )
    out.append(
        "- Reload after major project changes "
        "(`python -m validator.generate_skills`)."
    )
    out.append(
        "- Failure-mode IDs in this file (e.g. `scope_creep`) are stable "
        "identifiers — quote them verbatim when surfacing supervision "
        "concerns."
    )
    out.append("")

    # ---- Recommended supervision stack (three tiers, pre-baked) -------
    tiers = payload.get("tiers") or {}
    if tiers:
        out.extend(_render_tiers_section(tiers))

    # ---- Per-FM sections ------------------------------------------------
    out.append("## Failure modes — what to watch for and what to do")
    out.append("")
    out.append(
        "One subsection per failure mode, in priority-descending order "
        "(likelihood × impact, see `data/failure_mode_priorities.yml`)."
    )
    out.append("")

    for fm in payload["failure_modes"]:
        out.extend(_render_failure_mode(fm))

    # ---- Cross-cutting working agreement --------------------------------
    out.append("## Cross-cutting working agreement")
    out.append("")
    out.append(
        "Stable across projects. Distilled from this repo's own "
        "`CLAUDE.md` plus general agentic-AI hygiene."
    )
    out.append("")
    for bullet in _WORKING_AGREEMENT_BULLETS:
        out.append(f"- {bullet}")
    out.append("")

    # ---- Where to learn more --------------------------------------------
    out.append("## Where to learn more")
    out.append("")
    out.append("- Live KG: https://github.com/vasylrakivnenko/SAICA")
    out.append(
        "- Browse the catalog: see `data/tools/`, `data/failure_modes/`, "
        "`data/incidents/`, `data/papers/`, `data/crosswalks/`"
    )
    out.append("- Run an audit on a repo: " "`python -m pipeline.audit.cli <repo-url>`")
    out.append(
        "- Get a tailored recommendation: "
        "`python -m pipeline.mcp.server` (MCP) or fetch "
        "`recommendations.json` from the repo"
    )
    out.append("")

    # ---- Provenance -----------------------------------------------------
    out.append("## Provenance")
    out.append("")
    out.append(
        f"- Generated from KG version {payload['kg_version']} on "
        f"{payload['generated_at']} by `validator/generate_skills.py`."
    )
    out.append(
        f"- Priorities: `data/failure_mode_priorities.yml` "
        f"v{payload['priorities_version']}."
    )
    out.append("- Re-run after `data/*` changes.")
    out.append("")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI / write / check
# ---------------------------------------------------------------------------


def _render_text(payload: dict[str, Any]) -> str:
    """Render with a guaranteed trailing newline."""
    text = render_markdown(payload)
    if not text.endswith("\n"):
        text += "\n"
    return text


# Plugin SKILL.md frontmatter — must stay in sync with whatever Claude
# Code expects (see plugin/.claude-plugin/plugin.json). The body
# below is the SKILLS.md content stripped of its top preamble (which
# tells humans how to install it; redundant inside a plugin).
_PLUGIN_SKILL_PATH = REPO_ROOT / "plugin" / "skills" / "saica-supervise" / "SKILL.md"
# Cross-agent install path — `npx skills add vasylrakivnenko/SAICA` looks
# here. Same body as the Claude Code plugin SKILL.md.
_PUBLIC_SKILL_PATH = REPO_ROOT / "skills" / "saica-supervise" / "SKILL.md"
_PLUGIN_SKILL_FRONTMATTER = """---
name: saica-supervise
description: Watch for the 11 known AI-coding-agent failure modes (fabrication, scope_creep, security_vulnerability, etc.) — consult this skill before edits, dependency adds, completion claims, or anything that could trip a known supervision concern. Quote the snake_case failure-mode ids verbatim when flagging risks.
---

# SAICA supervision skill

This skill encodes per-action heuristics distilled from the SAICA-KG
corpus (https://github.com/vasylrakivnenko/SAICA). Use it as context
to decide *what to be careful about* when writing or modifying code.
The failure-mode IDs (snake_case) are the canonical vocabulary —
quote them verbatim when surfacing concerns.

The skill is **self-contained** — three pre-baked recommendation
tiers (`minimum` / `optimal` / `full`-MECE) appear right below, so
the agent doesn't need to call out to a service to get the
recommended stack. For richer / live querying (per-tool facet
lookup, agent-kind-aware filtering, repo audit), the parent SAICA-KG
project ships an MCP server separately — see
https://github.com/vasylrakivnenko/SAICA#claude-code-plugin.

"""


def _render_plugin_skill(payload: dict[str, Any]) -> str:
    """SKILLS.md text rewrapped as a Claude Code plugin skill.

    Drops the SKILLS.md "How this file is meant to be used" preamble
    (humans installing manually need it; plugin users don't) but
    PRESERVES the v0.6 "Recommended supervision stack" tiers section.
    Result: frontmatter + a custom plugin preamble + tiers + per-FM
    sections + working agreement + provenance.
    """
    body = _render_text(payload)
    # Slice from the recommended-stacks header onward — that drops the
    # SKILLS.md title + "How to use" preamble but keeps everything that
    # matters (tiers, per-FM sections, working agreement, provenance).
    marker = "## Recommended supervision stack"
    i = body.find(marker)
    if i < 0:
        # Fallback if v0.6 tiers section ever gets removed.
        marker = "## Failure modes"
        i = body.find(marker)
    if i < 0:
        return _PLUGIN_SKILL_FRONTMATTER + body
    return _PLUGIN_SKILL_FRONTMATTER + body[i:]


def _write_outputs(payload: dict[str, Any], out_dir: Path) -> Path:
    md_path = out_dir / "SKILLS.md"
    md_path.write_text(_render_text(payload), encoding="utf-8")
    rendered_skill = _render_plugin_skill(payload)
    # Mirror to the plugin's SKILL.md so the plugin stays in sync
    # with the canonical SKILLS.md without a separate generator run.
    if _PLUGIN_SKILL_PATH.parent.exists():
        _PLUGIN_SKILL_PATH.write_text(rendered_skill, encoding="utf-8")
    # Also mirror to the cross-agent install path (`skills/<name>/SKILL.md`)
    # so `npx skills add vasylrakivnenko/SAICA` resolves without --full-depth.
    _PUBLIC_SKILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PUBLIC_SKILL_PATH.write_text(rendered_skill, encoding="utf-8")
    return md_path


def _check_outputs(payload: dict[str, Any], out_dir: Path) -> int:
    md_path = out_dir / "SKILLS.md"
    expected = _render_text(payload)
    if not md_path.exists() or md_path.read_text(encoding="utf-8") != expected:
        sys.stderr.write(
            "generate_skills --check: out-of-date file:\n  "
            f"{md_path}\n"
            "Run `python -m validator.generate_skills` to regenerate.\n"
        )
        return 1
    # Same drift check for the plugin SKILL.md and the public skill mirror.
    rendered_skill = _render_plugin_skill(payload)
    for path in (_PLUGIN_SKILL_PATH, _PUBLIC_SKILL_PATH):
        if path is _PLUGIN_SKILL_PATH and not path.parent.exists():
            continue
        if not path.exists() or path.read_text(encoding="utf-8") != rendered_skill:
            sys.stderr.write(
                "generate_skills --check: out-of-date file:\n  "
                f"{path}\n"
                "Run `python -m validator.generate_skills` to regenerate.\n"
            )
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate_skills",
        description=("Regenerate SKILLS.md — the SAICA-KG agent-context skill file."),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Verify the committed file matches what would be regenerated; "
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

    md_path = _write_outputs(payload, args.out_dir)
    sys.stdout.write(f"wrote {md_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
