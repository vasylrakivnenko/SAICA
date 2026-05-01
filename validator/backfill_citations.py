#!/usr/bin/env python3
"""Conservatively backfill ``cited_in`` on tool YAMLs from paper text.

Today only a handful of tools in ``data/tools/*.yml`` have any paper
reference; meanwhile, ``data/papers/*.yml`` contains paper records whose
``title``/``tldr``/``notes``/``abstract`` fields occasionally name specific
tools or repositories. This script scans those text fields, proposes
``(paper_id, tool_id)`` matches with a confidence score, and (in apply
mode) appends the paper id to the tool's ``cited_in`` list — preserving
all other fields, ordering, comments, and quote styles via ruamel.

Conservative matching rules
---------------------------
For each (paper, tool) pair, evidence comes from these paper text fields:

    title, tldr, notes, abstract  (plus ``keywords`` if present)

A match is recorded with one of two confidences:

  * 1.0 — the paper text contains the tool's literal ``repository_url``,
    or its ``owner/repo`` GitHub slug as a standalone token.
  * 0.9 — the paper text contains the tool's ``name`` as a non-word-
    bounded phrase (case-insensitive by default; case-SENSITIVE for
    borderline english-word names like ``Continue``, ``Guidance``,
    ``Aider``, ``Modal``, etc.).
    - Borderline single-word names (``rebuff``, ``aider``, ``manifest``,
      ``helm``, ``modal``, ``continue``, ``guidance``, etc. — common
      english or k8s-overlap words) are accepted only when the
      surrounding 60-character window contains a corroborating signal
      (``LLM``, ``agent``, ``code``, ``coding``, ``model``, ``tool``,
      ``eval``, ``benchmark``, ``framework``, ``sandbox``).
    - Proprietary / academic products without a GitHub repo
      (``Claude Code``, ``Cursor``, ``Devin``, ``Windsurf``,
      ``GitHub Copilot``, ``LangSmith``, ``Modal``, ``Replit Agent``,
      ``v0``) require both the brand name AND a context signal in the
      surrounding window. Single-word brands that overlap with English
      nouns (``cursor``, ``modal``, ``windsurf``) additionally require
      exact-case matching to weed out the noun usage from the brand.

Sub-threshold candidates (e.g. confidence 0.7 if we ever introduce one)
are listed in the report under "Candidates needing review" and never
written to YAML.

Auto-apply requires confidence ``>= --threshold`` (default 0.9). Lower-
confidence matches are listed in the report under "Candidates needing
review" and never written to YAML.

Idempotency
-----------
If a paper id is already in a tool's ``cited_in`` list, it is not
re-added. Running twice on the same data produces the same YAML and the
same report (modulo the timestamp header).

Schema constraint
-----------------
``cited_in`` is the ONLY field this script ever modifies. No other
fields — including ``documented_in``, ``evaluated_on``, ``provenance``
— are touched. Per the user's instructions: an absent ``cited_in`` must
NOT be created as ``cited_in: []``; it is only populated when at least
one match is added.

Run
---
    .venv/bin/python -m validator.backfill_citations              # apply (default)
    .venv/bin/python -m validator.backfill_citations --dry        # preview only
    .venv/bin/python -m validator.backfill_citations --threshold 0.8  # looser
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import yaml as _yaml  # PyYAML for read-only paper loads (validator/cli pattern)
from ruamel.yaml import YAML  # noqa: E402

PAPERS_DIR = REPO / "data" / "papers"
TOOLS_DIR = REPO / "data" / "tools"
REPORT_DIR = REPO / "validator"

# --------------------------------------------------------------------------- #
# Matching configuration
# --------------------------------------------------------------------------- #

# Text fields on a paper YAML that can be searched for tool mentions.
PAPER_TEXT_FIELDS = ("title", "tldr", "notes", "abstract")

# Tool ids whose ``name`` is a borderline english / overloaded term. We only
# match these when surrounding context contains a corroborating signal.
BORDERLINE_TOOL_IDS: frozenset[str] = frozenset({
    "aider",       # English word "aider" (helper)
    "agno",        # short token, can collide
    "agenta",      # short token
    "cody",        # name; could be unrelated
    "cline",       # CLI tool but short
    "continue-dev", # name "Continue" is a keyword
    "evals",       # common word
    "garak",       # rare proper noun, but borderline
    "guidance",    # common english word
    "helm",        # k8s helm overlap
    "helicone",    # OK but borderline in context
    "instructor",  # english word
    "letta",       # short proper noun
    "logfire",     # short proper noun
    "manifest",    # english word
    "modal",       # english word + lib name + product
    "nono",        # nonsense token, often false positive
    "outlines",    # english plural
    "phoenix",     # multi-meaning (city / framework / "Phoenix")
    "rebuff",      # english verb
    "snyk",        # OK but short
    "socket",      # english word
    "v0",          # too short to match safely
})

# Names where there is no GitHub repo to disambiguate (proprietary /
# academic products). Require corroborating context word in same sentence.
NO_REPO_TOOL_IDS: frozenset[str] = frozenset({
    "braintrust",
    "claude-code",
    "cursor",
    "devin",
    "github-copilot",
    "langsmith",
    "modal",
    "replit-agent",
    "v0",
    "windsurf",
})

# Single-word brand names that overlap with common English nouns/verbs.
# When matching these as ``no_repo`` brands, we additionally require an
# exact-case occurrence (``Cursor`` not ``cursor``, ``Modal`` not ``modal``).
_LOWERCASE_WORD_BRANDS: frozenset[str] = frozenset({
    "cursor", "modal", "windsurf", "v0",
})

# Tools whose ``name`` is a generic technology term and would over-match
# (e.g. ``browser-mcp``'s name is "mcp" — any mention of the Model Context
# Protocol concept would falsely cite this tool). For these, only repo URL
# or owner/repo slug matches count; name matches are SUPPRESSED entirely.
URL_ONLY_TOOL_IDS: frozenset[str] = frozenset({
    "browser-mcp",          # name == "mcp" (Model Context Protocol concept)
    "magic-mcp",            # name == "magic-mcp"; OK actually, but stay strict
    "mcp-playwright",       # generic protocol prefix
    "mcp-server-browserbase",
    "mcp-toolbox",          # name is "genai-toolbox" — keep but treat strict
    "playwright-mcp",
    "pathway-llm-app",      # name == "llm-app" (very generic)
    "openai-evals",         # name == "evals" (handled by BORDERLINE too)
})

# Corroborating signals — words/phrases that, if present in the surrounding
# 60-char window, lift a borderline match to the 0.9 tier.
CONTEXT_SIGNALS = (
    "llm", "agent", "agentic", "code", "coding", "model", "tool",
    "eval", "evaluation", "benchmark", "framework", "sandbox",
    "framework", "ai", "ide", "cli",
)
_SIGNAL_RE = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in CONTEXT_SIGNALS) + r")\b",
    re.IGNORECASE,
)

# Window radius for context-signal lookup around a borderline name match.
CONTEXT_WINDOW = 60

# Width of the evidence snippet stored in the report.
SNIPPET_RADIUS = 40


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ToolMeta:
    id: str
    name: str
    repo_url: str
    repo_slug: str  # "owner/repo" or ""

    @property
    def is_no_repo(self) -> bool:
        return self.id in NO_REPO_TOOL_IDS or not self.repo_slug


@dataclass(frozen=True)
class Match:
    paper_id: str
    tool_id: str
    field: str
    matched_text: str
    snippet: str
    confidence: float
    rule: str  # "url" | "slug" | "name" | "name+context"

    def sort_key(self) -> tuple:
        return (self.tool_id, self.paper_id, -self.confidence, self.rule)


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def _make_yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _load_paper(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return _yaml.safe_load(fh) or {}


def _load_tool_readonly(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return _yaml.safe_load(fh) or {}


def _slug_from_repo(url: str) -> str:
    """Extract ``owner/repo`` from a GitHub URL, or return ``""``."""
    if not url:
        return ""
    m = re.search(r"github\.com/([^/]+)/([^/?#\s]+?)(?:\.git)?(?:[/?#].*)?$", url, re.I)
    if not m:
        return ""
    return f"{m.group(1)}/{m.group(2)}"


def load_tools() -> list[ToolMeta]:
    out: list[ToolMeta] = []
    for tp in sorted(TOOLS_DIR.glob("*.yml")):
        d = _load_tool_readonly(tp)
        out.append(ToolMeta(
            id=d.get("id", tp.stem),
            name=str(d.get("name") or "").strip(),
            repo_url=str(d.get("repository_url") or "").strip(),
            repo_slug=_slug_from_repo(str(d.get("repository_url") or "")),
        ))
    return out


def load_papers() -> dict[str, dict]:
    """Return ``{paper_id: paper_dict}`` for every YAML in ``data/papers/``."""
    out: dict[str, dict] = {}
    for pp in sorted(PAPERS_DIR.glob("*.yml")):
        d = _load_paper(pp)
        pid = d.get("id") or pp.stem
        out[pid] = d
    return out


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #

def _iter_text_fields(paper: dict) -> Iterable[tuple[str, str]]:
    """Yield ``(field_name, text)`` pairs from a paper, skipping non-strings."""
    for fld in PAPER_TEXT_FIELDS:
        v = paper.get(fld)
        if isinstance(v, str) and v.strip():
            yield fld, v
    # ``keywords`` / ``relevance_tags`` are arrays of strings; flatten them so
    # a tool name appearing as a keyword still counts.
    for fld in ("keywords", "relevance_tags"):
        v = paper.get(fld)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item.strip():
                    yield fld, item


def _snippet_of(text: str, span_start: int, span_end: int) -> str:
    """One-line snippet centered on the matched span."""
    a = max(0, span_start - SNIPPET_RADIUS)
    b = min(len(text), span_end + SNIPPET_RADIUS)
    snip = text[a:b].replace("\n", " ").replace("  ", " ").strip()
    if a > 0:
        snip = "…" + snip
    if b < len(text):
        snip = snip + "…"
    return snip


def _has_context_signal(text: str, span_start: int, span_end: int) -> bool:
    a = max(0, span_start - CONTEXT_WINDOW)
    b = min(len(text), span_end + CONTEXT_WINDOW)
    return bool(_SIGNAL_RE.search(text[a:b]))


def _find_repo_url(text: str, repo_url: str) -> tuple[int, int] | None:
    """Search for the literal repo URL (case-insensitive)."""
    if not repo_url:
        return None
    idx = text.lower().find(repo_url.lower())
    if idx < 0:
        return None
    return (idx, idx + len(repo_url))


def _find_slug(text: str, slug: str) -> tuple[int, int] | None:
    """Search for the ``owner/repo`` slug as a standalone token."""
    if not slug:
        return None
    pat = re.compile(r"(?<![\w/])" + re.escape(slug) + r"(?![\w/])", re.IGNORECASE)
    m = pat.search(text)
    return m.span() if m else None


# Names that are too short to safely substring-match.
_MIN_NAME_LEN = 3


def _find_name(
    text: str, name: str, *, case_sensitive: bool = False,
) -> tuple[int, int] | None:
    """Search for ``name`` as a non-word-bounded phrase.

    Tolerates ``space ↔ hyphen`` differences: a tool whose ``name`` is
    ``Gemini CLI`` will match either ``Gemini CLI`` or ``Gemini-CLI`` in the
    paper text. Names shorter than ``_MIN_NAME_LEN`` are ignored.

    With ``case_sensitive=True`` the match is exact-case — used to
    distinguish English verbs/nouns (``continue``, ``guidance``) from the
    proper-noun tool names (``Continue``, ``Guidance``).
    """
    if not name or len(name) < _MIN_NAME_LEN:
        return None
    # Replace internal whitespace with a "[ -]" character class so the
    # pattern matches both ``Gemini CLI`` and ``Gemini-CLI``.
    parts = re.split(r"\s+", name.strip())
    body = r"[ \-]+".join(re.escape(p) for p in parts if p)
    if not body:
        return None
    # Require non-word, non-hyphen on each side so we don't half-match
    # ``garak`` inside ``garak-eval`` or ``Aider`` inside ``Aiderbot``.
    flags = 0 if case_sensitive else re.IGNORECASE
    pat = re.compile(r"(?<![\w-])(?:" + body + r")(?![\w-])", flags)
    m = pat.search(text)
    return m.span() if m else None


def match_paper_to_tool(
    paper_id: str,
    paper: dict,
    tool: ToolMeta,
) -> Match | None:
    """Return the best (highest-confidence) match of ``tool`` in any text
    field of ``paper``, or ``None`` if no match meets our rules.
    """
    best: Match | None = None
    for field, text in _iter_text_fields(paper):
        # 1. Repo URL — strongest signal.
        if tool.repo_url:
            span = _find_repo_url(text, tool.repo_url)
            if span:
                m = Match(
                    paper_id=paper_id, tool_id=tool.id, field=field,
                    matched_text=tool.repo_url,
                    snippet=_snippet_of(text, *span),
                    confidence=1.0, rule="url",
                )
                if best is None or m.confidence > best.confidence:
                    best = m
                continue

        # 2. owner/repo slug — strong signal.
        if tool.repo_slug:
            span = _find_slug(text, tool.repo_slug)
            if span:
                m = Match(
                    paper_id=paper_id, tool_id=tool.id, field=field,
                    matched_text=tool.repo_slug,
                    snippet=_snippet_of(text, *span),
                    confidence=1.0, rule="slug",
                )
                if best is None or m.confidence > best.confidence:
                    best = m
                continue

        # 3. Name match.
        if tool.name and tool.id not in URL_ONLY_TOOL_IDS:
            multi_word = " " in tool.name.strip()
            is_borderline = tool.id in BORDERLINE_TOOL_IDS and not multi_word
            # For borderline single-word names that are also common English
            # words ("continue", "guidance", "manifest", "instructor", "modal",
            # "outlines", "rebuff"), require an exact-case match to weed out
            # the verb/noun usages from the brand usages.
            case_sensitive = is_borderline
            span = _find_name(text, tool.name, case_sensitive=case_sensitive)
            if span:
                if is_borderline:
                    if not _has_context_signal(text, *span):
                        continue
                    rule, conf = "name+context", 0.9
                elif tool.is_no_repo:
                    # Proprietary / academic product: require a
                    # corroborating context word in the surrounding window.
                    # Per the spec ("full tool name + code-related context
                    # word in the same sentence"), this is treated as a
                    # high-confidence match. Single-word brand names that
                    # are also common English words (``cursor``, ``modal``)
                    # additionally require exact-case matching to weed out
                    # the noun usage from the brand usage.
                    if not _has_context_signal(text, *span):
                        continue
                    # Re-check with case sensitivity if the name is a single
                    # English word. Multi-word brands like "Claude Code" or
                    # "Replit Agent" are safe without case enforcement.
                    if not multi_word and tool.name.lower() in _LOWERCASE_WORD_BRANDS:
                        if _find_name(text, tool.name, case_sensitive=True) is None:
                            continue
                    rule, conf = "name+context", 0.9
                else:
                    rule, conf = "name", 0.9

                m = Match(
                    paper_id=paper_id, tool_id=tool.id, field=field,
                    matched_text=tool.name,
                    snippet=_snippet_of(text, *span),
                    confidence=conf, rule=rule,
                )
                if best is None or m.confidence > best.confidence:
                    best = m
    return best


def match_all(papers: dict[str, dict], tools: list[ToolMeta]) -> list[Match]:
    matches: list[Match] = []
    for pid, paper in papers.items():
        for tool in tools:
            m = match_paper_to_tool(pid, paper, tool)
            if m is not None:
                matches.append(m)
    matches.sort(key=Match.sort_key)
    return matches


# --------------------------------------------------------------------------- #
# YAML write-back
# --------------------------------------------------------------------------- #

def apply_matches(
    matches: list[Match],
    *,
    threshold: float,
    yaml: YAML,
    dry: bool,
) -> dict[str, list[str]]:
    """Append accepted (paper_id) to each tool's ``cited_in`` list.

    Returns ``{tool_id: [added_paper_ids]}`` listing only NEW citations
    that were appended (or would be, in dry mode).
    """
    by_tool: dict[str, list[Match]] = {}
    for m in matches:
        if m.confidence < threshold:
            continue
        by_tool.setdefault(m.tool_id, []).append(m)

    added: dict[str, list[str]] = {}

    for tool_id, tool_matches in by_tool.items():
        path = TOOLS_DIR / f"{tool_id}.yml"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            doc = yaml.load(fh)
        if doc is None:
            continue

        existing = doc.get("cited_in")
        existing_list = list(existing) if existing else []
        existing_set = set(existing_list)

        # Deterministic order: sort proposed paper ids and append only the
        # new ones. Idempotent because we never reorder existing entries.
        new_pids = sorted({m.paper_id for m in tool_matches} - existing_set)
        if not new_pids:
            continue

        merged = existing_list + new_pids
        if "cited_in" in doc:
            doc["cited_in"] = merged
        else:
            # Field is absent — only create it when we have something to add
            # (per user instruction: never write empty cited_in).
            doc["cited_in"] = merged

        added[tool_id] = new_pids

        if dry:
            continue

        # Round-trip; only write if the file actually changed.
        buf = io.StringIO()
        yaml.dump(doc, buf)
        new_text = buf.getvalue()
        old_text = path.read_text(encoding="utf-8")
        if new_text != old_text:
            path.write_text(new_text, encoding="utf-8")

    return added


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def render_report(
    *,
    today: str,
    elapsed_s: float,
    papers: dict[str, dict],
    tools: list[ToolMeta],
    matches: list[Match],
    threshold: float,
    added: dict[str, list[str]],
    dry: bool,
) -> str:
    accepted = [m for m in matches if m.confidence >= threshold]
    candidates = [m for m in matches if m.confidence < threshold]

    n_papers = len(papers)
    n_tools = len(tools)
    n_added = sum(len(v) for v in added.values())
    n_tools_touched = len(added)

    lines: list[str] = []
    lines.append(f"# Citation backfill report — {today}")
    lines.append("")
    lines.append("Generated by `validator/backfill_citations.py`. "
                 "Conservative tool-mention matching over the paper corpus.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Mode: **{'dry-run (no writes)' if dry else 'apply (writes)'}**")
    lines.append(f"- Auto-apply threshold: **{threshold:.2f}**")
    lines.append(f"- Papers scanned: **{n_papers}**")
    lines.append(f"- Tools scanned: **{n_tools}**")
    lines.append(f"- Matches found (any confidence): **{len(matches)}**")
    lines.append(f"- Matches at/above threshold: **{len(accepted)}**")
    lines.append(f"- Candidates below threshold: **{len(candidates)}**")
    lines.append(f"- Tools that received new citations: **{n_tools_touched}**")
    lines.append(f"- New (paper, tool) edges added: **{n_added}**")
    lines.append(f"- Elapsed: **{elapsed_s:.2f}s**")
    lines.append("")

    lines.append("## Applied citations")
    lines.append("")
    if not added:
        lines.append("_No new citations applied. This is an honest finding: "
                     "the current paper YAMLs (`title` / `tldr` / `notes` / "
                     "`abstract`) rarely name specific tools or include "
                     "GitHub repository URLs, so the high-confidence match "
                     "set is sparse. The script will pick up new matches as "
                     "papers gain richer text or new papers/tools are added._")
        lines.append("")
    else:
        for tool_id in sorted(added):
            new_pids = added[tool_id]
            lines.append(f"### `{tool_id}`")
            lines.append("")
            for pid in new_pids:
                # Find the supporting match(es) for this (paper, tool).
                evidences = [m for m in accepted
                             if m.tool_id == tool_id and m.paper_id == pid]
                for m in evidences:
                    lines.append(
                        f"- **+{pid}** "
                        f"(rule={m.rule}, conf={m.confidence:.2f}, "
                        f"field=`{m.field}`)"
                    )
                    lines.append(f"  > {m.snippet}")
            lines.append("")

    # Show all accepted matches even if they were already present (for audit).
    pre_existing = [m for m in accepted
                    if m.paper_id not in added.get(m.tool_id, [])]
    if pre_existing:
        lines.append("## Already-present citations (no-op)")
        lines.append("")
        lines.append("Matches at/above threshold whose paper id was already "
                     "in the tool's `cited_in` list. Listed here so the "
                     "audit trail captures the full evidence set.")
        lines.append("")
        for m in pre_existing:
            lines.append(
                f"- `{m.tool_id}` ← `{m.paper_id}` "
                f"(rule={m.rule}, conf={m.confidence:.2f}, "
                f"field=`{m.field}`)"
            )
            lines.append(f"  > {m.snippet}")
        lines.append("")

    if candidates:
        lines.append("## Candidates needing review")
        lines.append("")
        lines.append(f"Matches BELOW the auto-apply threshold of "
                     f"{threshold:.2f}. Inspect manually; "
                     "promote to `cited_in` by hand if the evidence holds.")
        lines.append("")
        for m in candidates:
            lines.append(
                f"- `{m.tool_id}` ← `{m.paper_id}` "
                f"(rule={m.rule}, conf={m.confidence:.2f}, "
                f"field=`{m.field}`)"
            )
            lines.append(f"  > {m.snippet}")
        lines.append("")

    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "For each `(paper, tool)` pair the script searches the paper's "
        "`title`, `tldr`, `notes`, and `abstract` (plus `keywords` / "
        "`relevance_tags`) for one of:"
    )
    lines.append("")
    lines.append("1. **`url` (conf 1.0)** — literal `repository_url` substring.")
    lines.append("2. **`slug` (conf 1.0)** — `owner/repo` GitHub slug as a standalone token.")
    lines.append("3. **`name` (conf 0.9)** — tool `name` as a non-word-bounded phrase. "
                 "Borderline single-word names "
                 f"({sorted(BORDERLINE_TOOL_IDS)[:6]}…) require a "
                 "corroborating context word in the surrounding 60-char window.")
    lines.append("4. **`name+context` (conf 0.9)** — proprietary / academic products "
                 f"({sorted(NO_REPO_TOOL_IDS)[:6]}…) require both the name "
                 "and a code-related context word in the surrounding window. "
                 "Single-word brands that overlap with English nouns "
                 f"({sorted(_LOWERCASE_WORD_BRANDS)}) additionally require "
                 "exact-case matching.")
    lines.append("")
    lines.append(
        "`cited_in` is the only field this script ever writes; an absent "
        "`cited_in` is created only when at least one paper id is being added. "
        "Existing entries are preserved in their original order, and new entries "
        "are appended sorted to keep runs idempotent."
    )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry", action="store_true",
        help="Preview matches and write the report; do NOT modify YAMLs.",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.9,
        help="Minimum confidence to auto-apply a match (default: 0.9).",
    )
    parser.add_argument(
        "--report", type=Path, default=None,
        help="Path to the markdown report (default: validator/backfill_citations.report.md).",
    )
    args = parser.parse_args(argv)

    t0 = time.monotonic()
    papers = load_papers()
    tools = load_tools()
    matches = match_all(papers, tools)

    yaml = _make_yaml()
    added = apply_matches(matches, threshold=args.threshold, yaml=yaml, dry=args.dry)

    today = dt.date.today().isoformat()
    elapsed = time.monotonic() - t0
    report = render_report(
        today=today, elapsed_s=elapsed,
        papers=papers, tools=tools, matches=matches,
        threshold=args.threshold, added=added, dry=args.dry,
    )

    report_path = args.report or (REPORT_DIR / "backfill_citations.report.md")
    report_path.write_text(report, encoding="utf-8")

    try:
        report_display = report_path.relative_to(REPO)
    except ValueError:
        report_display = report_path
    print(
        f"backfill_citations: {len(papers)} papers × {len(tools)} tools → "
        f"{len(matches)} matches "
        f"({sum(1 for m in matches if m.confidence >= args.threshold)} ≥ "
        f"threshold {args.threshold:.2f}); "
        f"{sum(len(v) for v in added.values())} new citations across "
        f"{len(added)} tools "
        f"({'dry' if args.dry else 'applied'}). "
        f"Report → {report_display}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
