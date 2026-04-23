"""Core NLP pre-processing logic for SAICA-KG ingestion.

Pure Python + regex + rapidfuzz. No spaCy in v0.1.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from rapidfuzz import fuzz, utils as _rf_utils

from pipeline.nlp.keywords import (
    FAILURE_MODE_KEYWORDS,
    HIGH_SIGNAL_ORGS,
    TOOL_SIGNALS,
    PAPER_SIGNALS,
)


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

_GITHUB_URL_RE = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9][A-Za-z0-9._-]*)",
    re.IGNORECASE,
)
# arXiv new-style: 2403.12345 or 2403.12345v2 (word-boundary aware). Old-style:
# math.GT/0211159, cs.CL/0608032.
_ARXIV_NEW_RE = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")
_ARXIV_OLD_RE = re.compile(r"\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})\b")
# DOI: 10.<registrant>/<suffix>.
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)


def extract_github_urls(text: str) -> list[str]:
    """Return unique canonical ``github.com/owner/repo`` URLs found in ``text``.

    Trailing punctuation, .git suffix, and path tails beyond ``owner/repo``
    are stripped. Order preserved per first occurrence.
    """
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for owner, repo in _GITHUB_URL_RE.findall(text):
        # Strip trailing .git and punctuation already constrained by regex.
        if repo.endswith(".git"):
            repo = repo[:-4]
        url = f"https://github.com/{owner}/{repo}"
        if url.lower() not in seen:
            seen.add(url.lower())
            out.append(url)
    return out


def extract_arxiv_ids(text: str) -> list[str]:
    """Return unique arXiv ids from ``text`` (new + old style)."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _ARXIV_NEW_RE.findall(text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    for m in _ARXIV_OLD_RE.findall(text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def extract_dois(text: str) -> list[str]:
    """Return unique DOIs from ``text``."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _DOI_RE.findall(text):
        # Trim common trailing punctuation that can get swept in.
        m = m.rstrip(".,);]")
        key = m.lower()
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------

def _compile_keyword_patterns() -> dict[str, list[tuple[str, re.Pattern[str]]]]:
    compiled: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
    for fm_id, phrases in FAILURE_MODE_KEYWORDS.items():
        entries: list[tuple[str, re.Pattern[str]]] = []
        for phrase in phrases:
            # Word-boundary-aware match, case-insensitive. For multi-word
            # phrases with hyphens/spaces, we escape then relax the interior
            # whitespace to match one-or-more whitespace.
            escaped = re.escape(phrase)
            # Allow runs of whitespace between tokens (user text can have \n).
            escaped = re.sub(r"\\\s+", r"\\s+", escaped)
            pat = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
            entries.append((phrase, pat))
        compiled[fm_id] = entries
    return compiled


_KEYWORD_PATTERNS = _compile_keyword_patterns()


def keyword_hits(text: str) -> dict[str, list[str]]:
    """Return ``{failure_mode_id: [matched_phrases]}`` for hits in ``text``.

    Case-insensitive, word-boundary-aware. Empty dict if no hits.
    """
    if not text:
        return {}
    hits: dict[str, list[str]] = {}
    for fm_id, entries in _KEYWORD_PATTERNS.items():
        matched: list[str] = []
        for phrase, pat in entries:
            if pat.search(text):
                matched.append(phrase)
        if matched:
            hits[fm_id] = matched
    return hits


# ---------------------------------------------------------------------------
# URL canonicalisation
# ---------------------------------------------------------------------------

_TRACKING_PREFIXES = ("utm_", "ref_", "ref=", "mc_", "fbclid", "gclid")


def canonical_url(url: str) -> str:
    """Canonicalise: lowercase host, drop default ports, strip trailing slash,
    strip common tracking query params (utm_*, ref_*, fbclid, gclid)."""
    if not url:
        return url
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    # Strip default ports.
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    path = parsed.path or ""
    # Strip any trailing slash, including the lone root '/'. Reviewers using
    # canonical_url purely for dedupe benefit from 'example.com/' and
    # 'example.com' collapsing; retrieval tooling adds the slash back.
    if path.endswith("/"):
        path = path.rstrip("/")
    # Filter tracking params.
    kept = [
        (k, v) for (k, v) in parse_qsl(parsed.query, keep_blank_values=False)
        if not any(k.lower().startswith(pref) for pref in _TRACKING_PREFIXES)
    ]
    query = urlencode(kept)
    # Drop fragment (identifiers rarely matter for dedupe).
    fragment = ""
    return urlunparse((scheme, netloc, path, parsed.params, query, fragment))


# ---------------------------------------------------------------------------
# Relevance scoring + kind classification
# ---------------------------------------------------------------------------

_HIGH_SIGNAL_ORGS_LOWER = [o.lower() for o in HIGH_SIGNAL_ORGS]


def _row_text(raw_row: dict) -> str:
    parts = [
        str(raw_row.get("title") or ""),
        str(raw_row.get("snippet") or ""),
        str(raw_row.get("url") or ""),
    ]
    # raw_json can contain authors, venue, etc. — include a cheap string dump.
    rj = raw_row.get("raw_json")
    if rj:
        parts.append(str(rj))
    return "\n".join(parts)


def relevance_score(raw_row: dict) -> float:
    """0..1 relevance. See module docstring for weights."""
    text = _row_text(raw_row)
    score = 0.0

    # Keyword hits: +0.15 per distinct failure_mode, capped at 0.5.
    hits = keyword_hits(text)
    if hits:
        score += min(0.5, 0.15 * len(hits))

    # GitHub URL present: +0.2.
    if extract_github_urls(text):
        score += 0.2

    # arXiv or DOI present: +0.2.
    if extract_arxiv_ids(text) or extract_dois(text):
        score += 0.2

    # High-signal org mention: +0.1.
    low = text.lower()
    if any(org in low for org in _HIGH_SIGNAL_ORGS_LOWER):
        score += 0.1

    # Academic source baseline: +0.1.
    source = (raw_row.get("source") or "").lower()
    if source in {"elicit", "semantic_scholar", "s2"}:
        score += 0.1

    return max(0.0, min(1.0, score))


def classify_kind(raw_row: dict) -> Optional[str]:
    """Classify as 'tool' | 'paper' | 'incident' | None.

    Heuristics:
    - arXiv id or DOI present, or PAPER_SIGNALS hit in url/venue → 'paper'.
    - GitHub URL present, or TOOL_SIGNALS hit in title/snippet → 'tool'.
    - Title contains words like 'incident' / 'postmortem' / 'outage' → 'incident'.
    - Otherwise None.
    """
    text = _row_text(raw_row)
    low = text.lower()
    url = (raw_row.get("url") or "").lower()
    source = (raw_row.get("source") or "").lower()

    has_arxiv_or_doi = bool(extract_arxiv_ids(text)) or bool(extract_dois(text))
    paper_signal = any(sig in low for sig in PAPER_SIGNALS) or "arxiv.org" in url
    tool_signal = any(sig in low for sig in TOOL_SIGNALS)
    has_github = bool(extract_github_urls(text))
    incident_signal = any(
        w in low for w in (
            "incident report", "postmortem", "post-mortem", "outage report",
            "root cause analysis",
        )
    )

    # Incidents first: the wording is specific enough that it should win.
    if incident_signal:
        return "incident"

    # Papers: arxiv/doi wins over tool signals.
    if has_arxiv_or_doi or source in {"elicit", "semantic_scholar", "s2"}:
        return "paper"
    if paper_signal and not has_github:
        return "paper"

    # Tools.
    if has_github:
        return "tool"
    if tool_signal:
        return "tool"

    return None


# ---------------------------------------------------------------------------
# Dedupe / fuzzy title match
# ---------------------------------------------------------------------------

def fuzzy_title_matches(
    title: str,
    candidates: Iterable[str],
    *,
    threshold: int = 92,
) -> list[str]:
    """Return candidate titles whose token_set_ratio >= ``threshold`` against
    ``title``. Case-insensitive."""
    if not title:
        return []
    matches: list[str] = []
    t = title.strip()
    for c in candidates:
        if not c:
            continue
        score = fuzz.token_set_ratio(
            t, c, processor=_rf_utils.default_process
        )
        if score >= threshold:
            matches.append(c)
    return matches
