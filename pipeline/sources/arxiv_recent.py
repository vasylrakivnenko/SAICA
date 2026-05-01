"""arXiv recent-submissions scraper for the SAICA-KG discovery pipeline.

Polls the public arXiv Atom feed (``export.arxiv.org/api/query``) for the
last ``lookback_days`` of submissions in a configurable list of categories
(default ``cs.SE``, ``cs.AI``, ``cs.LG``) and surfaces papers that look
relevant to AI-coding-agent supervision / failure taxonomies.

This module mirrors the design of :mod:`pipeline.sources.github_trending`:

* Pure functions only — the orchestrator lives in
  :mod:`validator.screen_arxiv`.
* Polite scraping: 3.0s minimum interval to ``export.arxiv.org`` and a
  custom User-Agent (arXiv asks for "be reasonable"; we are well inside
  that envelope at one request per category per day).
* Per-day per-category disk cache under ``.cache/arxiv/`` so a re-run on
  the same day is fully offline.
* Reuses :data:`pipeline.audit.kg.FM_KEYWORDS` for failure-mode inference
  (do not redefine — the rule must stay identical to the heatmap).

Public surface (what the orchestrator imports):

* :func:`fetch_recent` — fetch (cached) Atom feed entries for one
  ``(category, lookback_days)`` pair, parse, return list of dicts.
* :func:`parse_atom` — pure XML parser for the Atom feed.
* :func:`score_relevance` — weighted-keyword score in [0, 1].
* :func:`infer_failure_modes` — text → list of canonical FM ids.
* :func:`suggested_id` — ``<surname>-<year>-<short-slug>`` paper id.
* :func:`match_against_kg` — split candidates into matched/new vs. KG.
* :func:`load_kg_arxiv_ids` — collect known arxiv ids from
  ``data/papers/*.yml``.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

from pipeline.audit.kg import FM_KEYWORDS
from pipeline.sources._http import rate_limited_session

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / ".cache" / "arxiv"
PAPERS_DIR = REPO_ROOT / "data" / "papers"

USER_AGENT = (
    "SAICA-KG-Arxiv-Bot/0.1 (https://github.com/saica-kg/saica-kg)"
)
ARXIV_API_BASE = "https://export.arxiv.org/api/query"

# arXiv asks for "be reasonable"; 3s between requests is the conventional
# polite interval and well under any documented limit.
_ARXIV_INTERVAL_S = 3.0
_SESSION = rate_limited_session(_ARXIV_INTERVAL_S, user_agent=USER_AGENT)

# Atom + arXiv namespaces. ElementTree needs them spelled out explicitly.
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

DEFAULT_CATEGORIES: tuple[str, ...] = ("cs.SE", "cs.AI", "cs.LG")
DEFAULT_LOOKBACK_DAYS = 30
# Per-page request size — arXiv tolerates up to a few hundred per page; we
# stick with 200 to keep responses small and parse-friendly.
DEFAULT_MAX_RESULTS = 200
# Hard cap on total entries fetched per category in one orchestrator run.
# The default protects against runaway pagination if the lookback window is
# very large; raise via the CLI if needed.
DEFAULT_MAX_TOTAL = 1000


# ---------------------------------------------------------------------------
# Relevance scoring (mirrors github_trending shape and threshold)
# ---------------------------------------------------------------------------

# Hand-tuned weighted keyword map. Positive weights are signals that the
# paper addresses AI-coding-agent supervision / failure modes; negative
# weights are anti-signals (off-topic generative-media / blockchain papers
# that happen to use words like "agent" or "evaluator"). The orchestrator
# picks the cutoff via :data:`RELEVANCE_THRESHOLD` (default 0.4).
RELEVANCE_KEYWORDS: dict[str, int] = {
    # Strong signals: directly about AI-coding-agent supervision / faults
    "claude code": 3,
    "codex": 2,
    "cursor": 2,
    "windsurf": 2,
    "aider": 2,
    "coding agent": 4,
    "code agent": 3,
    "ai agent": 2,
    "ai-agent": 2,
    "ai coding": 3,
    "llm agent": 3,
    "llm-based agent": 3,
    "agentic ai": 3,
    "agentic system": 3,
    "supervision": 4,
    "guardrail": 3,
    "guardrails": 3,
    "failure mode": 5,
    "failure modes": 5,
    "fault taxonomy": 4,
    "fault types": 3,
    "scope creep": 4,
    "hallucinat": 3,
    "fabricat": 3,
    "prompt injection": 3,
    "supply chain": 2,
    "slopsquat": 4,
    "agent fail": 4,
    "llm safety": 3,
    "llm security": 3,
    "code generation": 2,
    "software engineering": 1,
    # Concept signals (weaker, but additive)
    "evaluat": 2,
    "benchmark": 1,
    "red team": 3,
    "red-team": 3,
    "static analysis": 1,
    "type check": 1,
    "lint": 1,
    "observability": 2,
    "tracing": 1,
    "monitor": 1,
    "empirical study": 1,
    "taxonomy": 1,
    # Anti-signals
    "image generat": -3,
    "audio generat": -3,
    "video generat": -3,
    "music": -2,
    "fashion": -3,
    "protein folding": -4,
    "medical imaging": -4,
    "astronomy": -4,
    "blockchain": -3,
    "crypto trading": -4,
    "nft": -4,
}

_RELEVANCE_CEIL = 10.0
RELEVANCE_THRESHOLD = 0.4


def score_relevance(text: str) -> float:
    """Weighted-keyword relevance score in ``[0, 1]``.

    Same shape as :func:`pipeline.sources.github_trending.score_relevance`:
    each keyword is counted once (not per-occurrence) so a long abstract
    can't pin the score to 1.0 by repetition. Negative totals clamp to 0.
    """
    if not text:
        return 0.0
    t = text.lower()
    raw = 0
    for kw, w in RELEVANCE_KEYWORDS.items():
        if kw in t:
            raw += w
    if raw <= 0:
        return 0.0
    return min(1.0, raw / _RELEVANCE_CEIL)


def infer_failure_modes(text: str) -> list[str]:
    """Return canonical FM ids whose keywords appear in ``text``.

    Reuses :data:`pipeline.audit.kg.FM_KEYWORDS` so the rule is identical
    to the heatmap's tier-2 detector. Result is sorted for stability.
    """
    if not text:
        return []
    t = text.lower()
    hits: set[str] = set()
    for fm_id, kws in FM_KEYWORDS.items():
        if (
            fm_id in t
            or fm_id.replace("_", " ") in t
            or fm_id.replace("_", "-") in t
        ):
            hits.add(fm_id)
            continue
        for kw in kws:
            if kw in t:
                hits.add(fm_id)
                break
    return sorted(hits)


# ---------------------------------------------------------------------------
# Atom XML parsing
# ---------------------------------------------------------------------------

_ARXIV_ID_FROM_URL = re.compile(
    r"arxiv\.org/abs/(?P<id>[0-9]{4}\.[0-9]{4,6})(?:v\d+)?",
    re.IGNORECASE,
)


def _strip_arxiv_id(raw: str) -> str:
    """Extract the bare arxiv id (no version suffix) from a URL or id."""
    if not raw:
        return ""
    m = _ARXIV_ID_FROM_URL.search(raw)
    if m:
        return m.group("id")
    # Fallback: if the string itself is already a bare id (with optional v).
    s = raw.strip()
    s = re.sub(r"v\d+$", "", s)
    if re.fullmatch(r"[0-9]{4}\.[0-9]{4,6}", s):
        return s
    return ""


def _txt(el: Optional[ET.Element]) -> str:
    if el is None or el.text is None:
        return ""
    return " ".join(el.text.split())


def parse_atom(xml_str: str) -> list[dict[str, Any]]:
    """Parse an arXiv Atom feed into a list of entry dicts.

    Each entry dict has::

        {
            "arxiv_id": "2604.99001",
            "title": "...",
            "authors": ["First Last", ...],
            "first_published": "2026-04-29",   # ISO date (UTC)
            "updated": "2026-04-29",
            "abstract": "...",                 # whitespace-collapsed
            "primary_category": "cs.SE",
            "categories": ["cs.SE", "cs.AI"],
        }

    Entries with no parseable arxiv id are silently skipped. Raises
    :class:`xml.etree.ElementTree.ParseError` on malformed XML.
    """
    if not xml_str:
        return []
    root = ET.fromstring(xml_str)
    out: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", _NS):
        raw_id = _txt(entry.find("atom:id", _NS))
        arxiv_id = _strip_arxiv_id(raw_id)
        if not arxiv_id:
            continue
        title = _txt(entry.find("atom:title", _NS))
        summary_el = entry.find("atom:summary", _NS)
        abstract = (
            " ".join((summary_el.text or "").split())
            if summary_el is not None
            else ""
        )
        published = _txt(entry.find("atom:published", _NS))
        updated = _txt(entry.find("atom:updated", _NS))
        first_published = published[:10] if published else ""
        updated_date = updated[:10] if updated else ""

        authors: list[str] = []
        for a in entry.findall("atom:author", _NS):
            name = _txt(a.find("atom:name", _NS))
            if name:
                authors.append(name)

        prim = entry.find("arxiv:primary_category", _NS)
        primary_category = prim.get("term", "") if prim is not None else ""

        categories: list[str] = []
        for c in entry.findall("atom:category", _NS):
            term = c.get("term")
            if term:
                categories.append(term)

        out.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors,
                "first_published": first_published,
                "updated": updated_date,
                "abstract": abstract,
                "primary_category": primary_category,
                "categories": categories,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Suggested KG id (mirrors data/papers/<id>.yml convention)
# ---------------------------------------------------------------------------

# Stop words for slug generation — common abstract-noun words that don't
# carry the paper's identity. Kept small and deliberate.
_SLUG_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "for", "on", "in", "to", "with", "and",
        "or", "by", "from", "via", "is", "are", "be", "as", "at", "into",
        "towards", "toward", "using", "based", "study", "studies",
        "approach", "method", "methods", "framework", "system", "systems",
        "case", "cases", "model", "models", "new", "novel", "paper",
        "analysis", "evaluation",
    }
)

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _strip_diacritics(s: str) -> str:
    norm = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in norm if not unicodedata.combining(ch))


def _surname(full_name: str) -> str:
    """Lowercased, diacritic-stripped surname (last whitespace token).

    Handles trailing initials (``"Doe, J."`` → ``"doe"``) and dropped
    suffixes (``"Smith Jr."`` → ``"smith"``). Falls back to a slug of the
    full name if no alpha tokens remain.
    """
    if not full_name:
        return "unknown"
    name = _strip_diacritics(full_name).strip()
    # "Doe, John" → "Doe"
    if "," in name:
        name = name.split(",", 1)[0].strip()
    tokens = [t for t in re.split(r"\s+", name) if t]
    # Drop common suffixes that aren't really surnames.
    suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
    while tokens and tokens[-1].lower().rstrip(".") in suffixes:
        tokens.pop()
    if not tokens:
        return "unknown"
    surname = tokens[-1].lower()
    surname = _NON_SLUG.sub("", surname)
    return surname or "unknown"


def _slugify_title(title: str, *, max_tokens: int = 4) -> str:
    """2..max_tokens lowercase tokens from the title, stop-words stripped."""
    if not title:
        return "untitled"
    cleaned = _strip_diacritics(title).lower()
    raw = _NON_SLUG.sub(" ", cleaned).split()
    keep = [t for t in raw if t and t not in _SLUG_STOPWORDS and len(t) > 2]
    if len(keep) < 2:
        # Not enough content words — fall back to the first non-empty tokens.
        keep = [t for t in raw if t][:max_tokens]
    return "-".join(keep[:max_tokens]) or "untitled"


def suggested_id(authors: list[str], year: int, title: str) -> str:
    """Suggested ``<surname>-<year>-<short-slug>`` paper id.

    Mirrors the convention in ``data/papers/<id>.yml`` (e.g.
    ``shah-2026-characterizing-faults``). Uses the *first* author's
    surname; the slug is 2-4 stop-word-stripped lowercase tokens from the
    title.
    """
    first = authors[0] if authors else ""
    surname = _surname(first)
    slug = _slugify_title(title)
    return f"{surname}-{int(year)}-{slug}"


# ---------------------------------------------------------------------------
# KG-side helpers
# ---------------------------------------------------------------------------

def load_kg_arxiv_ids(papers_dir: Optional[Path] = None) -> dict[str, str]:
    """Return ``{bare_arxiv_id: paper_id}`` for every KG paper that has one.

    Looks at the ``arxiv_id`` field first; if absent, tries to derive an id
    from ``url`` (and ``doi`` for symmetry). Bare ids are stripped of any
    ``vN`` suffix so they line up with what :func:`parse_atom` produces.
    """
    pdir = Path(papers_dir) if papers_dir is not None else PAPERS_DIR
    out: dict[str, str] = {}
    if not pdir.exists():
        return out
    for path in sorted(pdir.glob("*.yml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            log.warning("arxiv: failed to read %s: %s", path, exc)
            continue
        if not isinstance(doc, dict):
            continue
        paper_id = str(doc.get("id") or path.stem)
        candidates: list[str] = []
        if doc.get("arxiv_id"):
            candidates.append(str(doc["arxiv_id"]))
        if doc.get("url"):
            candidates.append(str(doc["url"]))
        if doc.get("doi"):
            candidates.append(str(doc["doi"]))
        for c in candidates:
            bare = _strip_arxiv_id(c)
            if bare:
                out.setdefault(bare, paper_id)
                break
    return out


def match_against_kg(
    candidates: list[dict[str, Any]],
    kg_arxiv_ids: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split candidates into ``(matched_in_kg, new_candidates)``.

    ``kg_arxiv_ids`` is a mapping from bare arxiv id (e.g. ``2603.06847``)
    to the KG ``paper_id`` (e.g. ``shah-2026-characterizing-faults``).
    """
    matched: list[dict[str, Any]] = []
    new: list[dict[str, Any]] = []
    for c in candidates:
        aid = c.get("arxiv_id") or ""
        paper_id = kg_arxiv_ids.get(aid)
        if paper_id:
            matched.append(
                {
                    "paper_id": paper_id,
                    "arxiv_id": aid,
                    "title": c.get("title", ""),
                    "first_published": c.get("first_published", ""),
                }
            )
        else:
            new.append(c)
    matched.sort(key=lambda r: (r.get("first_published") or "", r["arxiv_id"]), reverse=True)
    return matched, new


# ---------------------------------------------------------------------------
# Excerpt
# ---------------------------------------------------------------------------

def abstract_excerpt(text: str, max_chars: int = 400) -> str:
    """Return a leading-sentence excerpt of the abstract, ``max_chars`` cap."""
    if not text:
        return ""
    s = " ".join(text.split())
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars].rsplit(" ", 1)[0]
    return cut + "..."


# ---------------------------------------------------------------------------
# Fetch (with disk cache)
# ---------------------------------------------------------------------------

def _cache_key(category: str, lookback_days: int, today_iso: str) -> str:
    safe_cat = category.replace("/", "_")
    return f"{today_iso}__{safe_cat}__lb{int(lookback_days)}.xml"


def _cache_key_page(
    category: str, lookback_days: int, today_iso: str, page_start: int
) -> str:
    """Cache key for a single paginated page (offset = ``page_start``).

    Page 0 is also written under the legacy single-page key
    (:func:`_cache_key`) so older callers / fixtures keep working — see
    :func:`fetch_recent` for the read path.
    """
    safe_cat = category.replace("/", "_")
    return (
        f"{today_iso}__{safe_cat}__lb{int(lookback_days)}__p{int(page_start)}.xml"
    )


def _today_iso() -> str:
    return _dt.date.today().isoformat()


def _arxiv_date_window(today: _dt.date, lookback_days: int) -> tuple[str, str]:
    """Return ``(start, end)`` strings in arxiv's ``YYYYMMDDHHMM`` format."""
    start = today - _dt.timedelta(days=int(lookback_days))
    return (
        f"{start.strftime('%Y%m%d')}0000",
        f"{today.strftime('%Y%m%d')}2359",
    )


def _fetch_one_page(
    *,
    category: str,
    lookback_days: int,
    page_start: int,
    page_size: int,
    today_iso: str,
    cdir: Path,
    use_network: bool,
) -> Optional[str]:
    """Fetch one page of results (returns raw XML, or ``None`` on failure).

    Page 0 is *also* read from / written to the legacy single-page cache
    key (:func:`_cache_key`) so existing fixtures and the offline test
    path don't need to know about pagination.
    """
    page_path = cdir / _cache_key_page(category, lookback_days, today_iso, page_start)
    legacy_path = cdir / _cache_key(category, lookback_days, today_iso)

    xml_str: Optional[str] = None
    if page_path.exists():
        try:
            xml_str = page_path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("arxiv cache read failed for %s: %s", page_path, exc)
    if xml_str is None and page_start == 0 and legacy_path.exists():
        try:
            xml_str = legacy_path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("arxiv cache read failed for %s: %s", legacy_path, exc)

    if xml_str is not None:
        return xml_str
    if not use_network:
        log.info(
            "arxiv: no cache for %s page %d and --no-network set",
            category, page_start,
        )
        return None

    try:
        today_d = _dt.date.fromisoformat(today_iso)
    except ValueError:
        today_d = _dt.date.today()
    start, end = _arxiv_date_window(today_d, lookback_days)
    params = {
        "search_query": (
            f"cat:{category} AND lastUpdatedDate:[{start} TO {end}]"
        ),
        "start": str(int(page_start)),
        "max_results": str(int(page_size)),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    try:
        resp = _SESSION.get(ARXIV_API_BASE, params=params, timeout=60)
        if resp.status_code == 429:
            log.warning(
                "arxiv: rate-limited on %s page %d", category, page_start,
            )
            return None
        resp.raise_for_status()
        xml_str = resp.text
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "arxiv fetch failed for %s page %d: %s",
            category, page_start, exc,
        )
        return None

    try:
        page_path.write_text(xml_str, encoding="utf-8")
    except OSError as exc:
        log.warning("arxiv cache write failed for %s: %s", page_path, exc)
    return xml_str


def fetch_recent(
    category: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    *,
    today_iso: Optional[str] = None,
    use_network: bool = True,
    cache_dir: Optional[Path] = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    max_total: int = DEFAULT_MAX_TOTAL,
) -> list[dict[str, Any]]:
    """Fetch + parse the recent feed for one category.

    Pages through arXiv until either the per-page response is short
    (signalling end of feed) or we hit ``max_total`` accumulated entries.
    Each page is cached individually under ``.cache/arxiv/`` so a re-run
    on the same day is fully offline.

    With ``use_network=False`` we read only the cache and stop at the
    first missing page — the orchestrator wires this to ``--no-network``.

    For backward compatibility, page 0 also resolves the legacy
    ``<today>__<cat>__lb<N>.xml`` cache key so existing fixtures keep
    working.
    """
    cdir = Path(cache_dir) if cache_dir is not None else CACHE_DIR
    cdir.mkdir(parents=True, exist_ok=True)
    key_day = today_iso or _today_iso()

    out: list[dict[str, Any]] = []
    page_size = int(max_results)
    page_start = 0
    while page_start < int(max_total):
        xml_str = _fetch_one_page(
            category=category,
            lookback_days=lookback_days,
            page_start=page_start,
            page_size=page_size,
            today_iso=key_day,
            cdir=cdir,
            use_network=use_network,
        )
        if xml_str is None:
            break
        try:
            page_items = parse_atom(xml_str)
        except ET.ParseError as exc:
            log.warning("arxiv: malformed XML for %s page %d: %s",
                        category, page_start, exc)
            break
        if not page_items:
            break
        out.extend(page_items)
        # End-of-feed signal: a short page (fewer than ``page_size``).
        if len(page_items) < page_size:
            break
        page_start += page_size
    if len(out) > int(max_total):
        out = out[: int(max_total)]
    return out


# ---------------------------------------------------------------------------
# Public IO
# ---------------------------------------------------------------------------

def write_json(path: Path, doc: dict[str, Any]) -> None:
    """Write JSON with a stable indent — used by tests + the orchestrator."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def iter_default_categories() -> Iterable[str]:
    """Iterate the default category list."""
    return iter(DEFAULT_CATEGORIES)


__all__ = [
    "ARXIV_API_BASE",
    "CACHE_DIR",
    "DEFAULT_CATEGORIES",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_MAX_RESULTS",
    "DEFAULT_MAX_TOTAL",
    "PAPERS_DIR",
    "RELEVANCE_KEYWORDS",
    "RELEVANCE_THRESHOLD",
    "USER_AGENT",
    "abstract_excerpt",
    "fetch_recent",
    "infer_failure_modes",
    "iter_default_categories",
    "load_kg_arxiv_ids",
    "match_against_kg",
    "parse_atom",
    "score_relevance",
    "suggested_id",
    "write_json",
]
