"""Stage 3 — novelty filter.

GOAL
----
Stop curator-queue pollution. Every Stage 1 discovery run surfaces
the same well-known tools (semgrep, dependabot, langfuse) over and
over because they're indexed in every awesome-list and cited in many
papers. Without a novelty filter every cycle re-shows them; curators
re-evaluate; cycle wastes time.

WHAT IT DOES
------------
Given a candidate dict (a partial Postgres ``candidate_tools`` row),
extract its canonical ids (github owner/repo, arXiv id, DOI), match
against the live KG (``data/tools/*.yml``), and bin the candidate:

  * ``DROP`` — every canonical id resolved to an existing tool, AND no
    new evidence (no new failure-mode hit, no new paper citation, no
    newer release date) is attached.
  * ``UPDATE_QUEUE`` — at least one canonical id matched an existing
    tool, AND the candidate carries something we don't already have.
    The "what's new" details are attached to the decision so the
    update PR can be auto-drafted.
  * ``CONTINUE`` — no canonical id matched. Genuinely new; pass on to
    Stage 4 (composite quality gate).

DESIGN CHOICES
--------------
* No I/O. The classifier loads the KG once via the index helper in
  :mod:`pipeline.audit.kg`, then matches in-memory. Cheap to run on
  every batch.
* Match by *canonical id*, not by name. "Langfuse" the project,
  "langfuse-ai" the org, and "github.com/langfuse/langfuse" the URL
  must all collapse. Name-only matches are too noisy.
* Conservative: when in doubt (e.g. parse failure), CONTINUE. False
  positives in Stage 3 are worse than false negatives — a
  duplicate-but-passed candidate gets caught at merge time, but a
  dropped-genuinely-new candidate is silently lost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Iterable, Optional

import yaml

from pipeline.audit.analyzer import GITHUB_URL_RE


# ---------------------------------------------------------------------------
# Canonical-id extractors
# ---------------------------------------------------------------------------

# arXiv id patterns:
#   - new style: 2304.12345  or  2304.12345v3
#   - old style: cs.LG/0405001
_ARXIV_RE = re.compile(
    r"\b(?:arxiv:)?((?:\d{4}\.\d{4,5}(?:v\d+)?)|(?:[a-z\-]+(?:\.[A-Z]{2})?/\d{7}))",
    re.IGNORECASE,
)

# DOI: 10.NNNN/<rest> — \S excludes whitespace + common terminators.
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)


@dataclass(frozen=True)
class CanonicalIds:
    """Canonical identifiers extracted from one candidate.

    Any combination may be empty; the more populated, the better the
    novelty decision.
    """

    github: Optional[str] = None       # 'owner/repo' lowercased
    arxiv: Optional[str] = None        # bare id, no 'arXiv:' prefix
    doi: Optional[str] = None          # bare DOI, no 'https://doi.org/'
    slug: Optional[str] = None         # kebab-case proposed_id, if provided


def extract_canonical_ids(candidate: dict[str, Any]) -> CanonicalIds:
    """Extract canonical ids from a candidate row.

    Reads the fields a candidate_tools row carries: ``source_url``,
    ``proposed_id``, ``readme``/``readme_text``, ``summary``, ``doi``,
    ``arxiv_id``. Missing fields are skipped, no exceptions.
    """
    github = _extract_github(candidate.get("source_url"))
    if github is None:
        # Fall back to README scan — arXiv-paper candidates often link
        # to the implementation in README rather than carrying the URL
        # in `source_url`.
        for blob_key in ("readme", "readme_text", "summary"):
            blob = candidate.get(blob_key)
            if isinstance(blob, str):
                github = _scan_for_github(blob)
                if github:
                    break

    # Direct field; otherwise scan source_url + summary.
    arxiv = candidate.get("arxiv_id")
    if not arxiv:
        for blob in (candidate.get("source_url"), candidate.get("summary")):
            if isinstance(blob, str):
                m = _ARXIV_RE.search(blob)
                if m:
                    arxiv = m.group(1)
                    break

    doi = candidate.get("doi")
    if not doi:
        for blob in (candidate.get("source_url"), candidate.get("summary")):
            if isinstance(blob, str):
                m = _DOI_RE.search(blob)
                if m:
                    doi = m.group(1).rstrip(".,);")
                    break

    return CanonicalIds(
        github=github.lower() if github else None,
        arxiv=arxiv.lower() if isinstance(arxiv, str) else None,
        doi=doi.lower() if isinstance(doi, str) else None,
        slug=(
            candidate.get("proposed_id").lower()
            if isinstance(candidate.get("proposed_id"), str)
            else None
        ),
    )


def _extract_github(url: Any) -> Optional[str]:
    """Return ``owner/repo`` (lowercased, no trailing .git) or None."""
    if not isinstance(url, str):
        return None
    m = GITHUB_URL_RE.match(url.strip())
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    return f"{owner}/{repo}".rstrip("/").lower()


def _scan_for_github(text: str) -> Optional[str]:
    """Scan a free-text blob for the first github.com/owner/repo URL."""
    # Pre-compiled pattern; accepts trailing punctuation.
    pat = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
    m = pat.search(text)
    if not m:
        return None
    repo = m.group(2)
    # Drop common trailing punctuation that gets glued to URLs in prose.
    repo = repo.rstrip(".,);]>")
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"{m.group(1)}/{repo}".lower()


# ---------------------------------------------------------------------------
# KG index — keyed by canonical id
# ---------------------------------------------------------------------------


@dataclass
class _KgIndex:
    """In-memory canonical-id → tool-id lookup."""

    by_github: dict[str, str] = field(default_factory=dict)
    by_arxiv: dict[str, str] = field(default_factory=dict)
    by_doi: dict[str, str] = field(default_factory=dict)
    by_slug: dict[str, str] = field(default_factory=dict)
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup(self, ids: CanonicalIds) -> Optional[str]:
        """Return the matching tool_id or None. First hit wins."""
        if ids.github and ids.github in self.by_github:
            return self.by_github[ids.github]
        if ids.slug and ids.slug in self.by_slug:
            return self.by_slug[ids.slug]
        if ids.arxiv and ids.arxiv in self.by_arxiv:
            return self.by_arxiv[ids.arxiv]
        if ids.doi and ids.doi in self.by_doi:
            return self.by_doi[ids.doi]
        return None


def build_kg_index(tools_dir: Optional[str] = None) -> _KgIndex:
    """Build the canonical-id index from data/tools/*.yml.

    Cheap (~50ms for 87 tools); no caching — callers are expected to
    build once per batch and reuse.
    """
    from pathlib import Path

    if tools_dir is None:
        tools_dir = str(
            Path(__file__).resolve().parent.parent.parent / "data" / "tools"
        )

    idx = _KgIndex()
    for yml in sorted(Path(tools_dir).glob("*.yml")):
        try:
            doc = yaml.safe_load(yml.read_text()) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        tool_id = doc.get("id")
        if not isinstance(tool_id, str):
            continue
        idx.tools[tool_id] = doc
        idx.by_slug[tool_id.lower()] = tool_id

        repo = doc.get("repository_url")
        gh = _extract_github(repo)
        if gh:
            idx.by_github[gh] = tool_id

        # Existing tool YAMLs don't store arxiv ids or DOIs at the top
        # level today — but cited_in entries point at papers that may.
        # We don't expand the citation graph here on purpose: the
        # novelty match is per-tool, not per-paper.
    return idx


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class NoveltyOutcome(str, Enum):
    """The three buckets a novelty decision can land in."""

    DROP = "drop"
    UPDATE_QUEUE = "update_queue"
    CONTINUE = "continue"


@dataclass
class NoveltyDecision:
    """One classifier verdict per candidate."""

    outcome: NoveltyOutcome
    canonical_ids: CanonicalIds
    matched_tool_id: Optional[str] = None
    new_evidence: list[str] = field(default_factory=list)
    reason: str = ""


# ---------------------------------------------------------------------------
# What counts as "new evidence" on a known tool?
# ---------------------------------------------------------------------------


def _new_evidence(
    candidate: dict[str, Any], known_tool: dict[str, Any]
) -> list[str]:
    """Return short strings naming each kind of new evidence the
    candidate carries that the known tool doesn't.

    Cheap heuristic; intentionally narrow. False negatives here just
    mean the candidate gets DROPped instead of routed to the update
    queue — survivable.
    """
    new: list[str] = []

    # New paper citation — candidate proposes a paper id not in cited_in.
    proposed_papers = candidate.get("paper_citations") or []
    if isinstance(proposed_papers, (list, tuple)):
        existing = set(known_tool.get("cited_in") or [])
        for p in proposed_papers:
            if isinstance(p, str) and p not in existing:
                new.append(f"new_paper:{p}")

    # New failure-mode hit — Stage 1 discovery surfaces this.
    proposed_fms = candidate.get("failure_mode_hits") or []
    if isinstance(proposed_fms, (list, tuple)):
        existing_fms = set(known_tool.get("addresses_failure_modes") or [])
        for fm in proposed_fms:
            if isinstance(fm, str) and fm not in existing_fms:
                new.append(f"new_fm_hit:{fm}")

    # Newer release date.
    cand_date = candidate.get("last_updated") or candidate.get("last_commit_date")
    known_date = known_tool.get("last_updated")
    cand_d = _coerce_date(cand_date)
    known_d = _coerce_date(known_date)
    if cand_d and known_d and cand_d > known_d:
        new.append(f"newer_release:{cand_d.isoformat()}>{known_d.isoformat()}")

    return new


def _coerce_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def classify(
    candidate: dict[str, Any],
    *,
    kg_index: Optional[_KgIndex] = None,
) -> NoveltyDecision:
    """Apply the novelty filter to one candidate.

    ``kg_index`` is built fresh from disk if not provided; for batches
    of >5 candidates, prefer ``build_kg_index()`` once and pass in.
    """
    if kg_index is None:
        kg_index = build_kg_index()

    ids = extract_canonical_ids(candidate)

    matched_tool_id = kg_index.lookup(ids)
    if matched_tool_id is None:
        return NoveltyDecision(
            outcome=NoveltyOutcome.CONTINUE,
            canonical_ids=ids,
            reason="No canonical id matched any KG tool.",
        )

    known = kg_index.tools[matched_tool_id]
    new_evidence = _new_evidence(candidate, known)
    if new_evidence:
        return NoveltyDecision(
            outcome=NoveltyOutcome.UPDATE_QUEUE,
            canonical_ids=ids,
            matched_tool_id=matched_tool_id,
            new_evidence=new_evidence,
            reason=f"Known tool {matched_tool_id!r} carries new evidence.",
        )

    return NoveltyDecision(
        outcome=NoveltyOutcome.DROP,
        canonical_ids=ids,
        matched_tool_id=matched_tool_id,
        reason=f"Already in KG as {matched_tool_id!r}, no new evidence.",
    )


def classify_batch(
    candidates: Iterable[dict[str, Any]],
    *,
    kg_index: Optional[_KgIndex] = None,
) -> list[NoveltyDecision]:
    """Apply :func:`classify` to a batch of candidates with a single
    KG-index build."""
    if kg_index is None:
        kg_index = build_kg_index()
    return [classify(c, kg_index=kg_index) for c in candidates]


__all__ = [
    "CanonicalIds",
    "NoveltyDecision",
    "NoveltyOutcome",
    "build_kg_index",
    "classify",
    "classify_batch",
    "extract_canonical_ids",
]
