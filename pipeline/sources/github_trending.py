"""GitHub Trending scraper for the SAICA-KG ranking signal.

Scrapes ``https://github.com/trending`` (and the per-language slices) into a
flat list of candidate repositories, then exposes pure helpers used by the
orchestrator in :mod:`validator.screen_trending`:

* :func:`fetch_trending_page` — parse one trending list page (cached on disk
  so a re-run on the same day doesn't re-hit github.com).
* :func:`normalize_repository_url` — canonicalize a repo URL for matching
  against the KG (lowercase host, strip trailing ``/`` and ``.git``).
* :func:`fetch_readme` — defensive HTTP GET against
  ``raw.githubusercontent.com`` (HEAD branch), with a small fallback list of
  README casings; truncates the body to ``max_bytes``.
* :func:`score_relevance` — weighted-keyword score (raw_score / 10, clamped
  to [0, 1]); the threshold lives with the orchestrator.
* :func:`infer_failure_modes` — README → list of FM ids using the canonical
  :data:`pipeline.audit.kg.FM_KEYWORDS` map. We import + reuse rather than
  re-define so the rule stays identical to the heatmap.

Polite-scraper defaults: 2.0s minimum interval to ``github.com/trending``
pages and a custom User-Agent. The HTML parser prefers BeautifulSoup when
available and falls back to a regex-based reader otherwise.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

from pipeline.audit.kg import FM_KEYWORDS
from pipeline.sources._http import rate_limited_session

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / ".cache" / "trending"

USER_AGENT = (
    "SAICA-KG-Trending-Bot/0.2 (https://github.com/saica-kg/saica-kg)"
)
TRENDING_BASE = "https://github.com/trending"
RAW_README_BASE = "https://raw.githubusercontent.com"

# Polite intervals — github.com/trending is served from CDN but we still
# want to look like one well-mannered client. The same session is reused
# for raw.githubusercontent.com fetches.
_TRENDING_INTERVAL_S = 2.0
_SESSION = rate_limited_session(_TRENDING_INTERVAL_S, user_agent=USER_AGENT)


# ---------------------------------------------------------------------------
# Relevance scoring
# ---------------------------------------------------------------------------

# Weighted keyword map. Positive weights are signals that the repo addresses
# AI-coding-agent failure modes; negative weights are anti-signals (off-topic
# generative-media / blockchain projects that happen to use the words "agent"
# or "evaluator"). Tuned by hand; the orchestrator picks the cutoff.
RELEVANCE_KEYWORDS: dict[str, int] = {
    # Strong signals: directly about fixing AI-coding-agent issues
    "claude code": 3,
    "codex": 2,
    "cursor": 2,
    "windsurf": 2,
    "aider": 2,
    "coding agent": 4,
    "ai agent": 2,
    "ai-agent": 2,
    "ai coding": 3,
    "supervision": 4,
    "guardrail": 3,
    "guardrails": 3,
    "failure mode": 5,
    "failure modes": 5,
    "scope creep": 4,
    "hallucinat": 3,
    "fabricat": 3,
    "prompt injection": 3,
    "supply chain": 2,
    "slopsquat": 4,
    "agent fail": 4,
    "llm safety": 3,
    "llm security": 3,
    # Concept signals
    "evaluat": 2,
    "red team": 3,
    "red-team": 3,
    "static analysis": 1,
    "type check": 1,
    "lint": 1,
    "observability": 2,
    "tracing": 1,
    "monitor": 1,
    # Anti-signals
    "image generat": -3,
    "audio generat": -3,
    "video generat": -3,
    "music": -2,
    "fashion": -3,
    "game develop": -2,
    "blockchain": -3,
    "crypto trading": -4,
    "nft": -4,
    "tutorial": -1,
    "course": -1,
    "homework": -3,
}

# Score normalization ceiling. Raw scores in practice run from -10..+15;
# dividing by 10 and clamping gives a stable 0..1 number where >=0.4
# (raw>=4) is "looks relevant".
_RELEVANCE_CEIL = 10.0
RELEVANCE_THRESHOLD = 0.4


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

_TRACKING_RE = re.compile(r"\?.*$")


def normalize_repository_url(url: str) -> str:
    """Canonicalize a GitHub repo URL for KG matching.

    Lowercases the host, strips the URL fragment + querystring, drops a
    trailing ``/`` and a trailing ``.git``. The path case is preserved
    because GitHub repo names *are* case-sensitive in URLs (some users
    have ``MyRepo`` and ``myrepo`` as different things, even if redirects
    exist). The KG-side ``repository_url`` strings are likewise stored
    case-preserving.
    """
    if not url:
        return ""
    s = url.strip()
    # Drop fragments first (#readme), then query string.
    s = s.split("#", 1)[0]
    s = _TRACKING_RE.sub("", s)
    # Lowercase scheme + host but not the path.
    if "://" in s:
        scheme, rest = s.split("://", 1)
        if "/" in rest:
            host, path = rest.split("/", 1)
            s = f"{scheme.lower()}://{host.lower()}/{path}"
        else:
            s = f"{scheme.lower()}://{rest.lower()}"
    if s.endswith("/"):
        s = s[:-1]
    if s.endswith(".git"):
        s = s[:-4]
    return s


def _owner_repo(url: str) -> Optional[tuple[str, str]]:
    """Return ``(owner, repo)`` for a github.com URL, or ``None``."""
    s = normalize_repository_url(url)
    if "github.com/" not in s:
        return None
    tail = s.split("github.com/", 1)[1]
    parts = tail.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# HTML parsing — bs4 preferred, regex fallback
# ---------------------------------------------------------------------------

def _parse_with_bs4(html: str) -> list[dict[str, Any]]:
    from bs4 import BeautifulSoup  # local import: optional dep

    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []
    for art in soup.select("article.Box-row"):
        a = art.select_one("h2 a") or art.select_one("h1 a")
        if a is None:
            continue
        href = (a.get("href") or "").strip()
        if not href.startswith("/") or href.count("/") < 2:
            continue
        full_name = href.lstrip("/")
        # h2 text is "owner /\n  repo" — normalize.
        name_text = " ".join(a.get_text(" ", strip=True).split())
        owner_repo = name_text.replace(" / ", "/").replace(" ", "")
        if "/" not in owner_repo:
            owner_repo = full_name

        desc_el = art.select_one("p")
        description = desc_el.get_text(" ", strip=True) if desc_el else ""

        lang_el = art.select_one('[itemprop="programmingLanguage"]')
        language = lang_el.get_text(strip=True) if lang_el else ""

        # Stars: the first <a> with href ending in /stargazers; text like " 49,231 ".
        stars_total = 0
        for link in art.select("a.Link--muted"):
            lhref = (link.get("href") or "").strip()
            if lhref.endswith("/stargazers"):
                txt = link.get_text(" ", strip=True).replace(",", "")
                m = re.search(r"\d+", txt)
                if m:
                    stars_total = int(m.group(0))
                break

        out.append(
            {
                "full_name": owner_repo,
                "repository_url": f"https://github.com/{owner_repo}",
                "description": description,
                "stars_total": stars_total,
                "language": language,
            }
        )
    return out


_ARTICLE_RE = re.compile(
    r'<article[^>]*class="[^"]*Box-row[^"]*"[^>]*>(.*?)</article>',
    re.DOTALL | re.IGNORECASE,
)
_HREF_RE = re.compile(r'<h[12][^>]*>\s*<a[^>]*href="([^"]+)"', re.DOTALL | re.IGNORECASE)
_DESC_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
_LANG_RE = re.compile(
    r'itemprop="programmingLanguage"[^>]*>([^<]+)<', re.IGNORECASE
)
_STARS_RE = re.compile(
    r'href="[^"]+/stargazers"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(s: str) -> str:
    return " ".join(_TAG_RE.sub(" ", s).split()).strip()


def _parse_with_regex(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for art in _ARTICLE_RE.findall(html):
        m = _HREF_RE.search(art)
        if not m:
            continue
        href = m.group(1).strip()
        if not href.startswith("/") or href.count("/") < 2:
            continue
        full_name = href.lstrip("/")

        desc_match = _DESC_RE.search(art)
        description = _strip_tags(desc_match.group(1)) if desc_match else ""

        lang_match = _LANG_RE.search(art)
        language = lang_match.group(1).strip() if lang_match else ""

        stars_match = _STARS_RE.search(art)
        stars_total = 0
        if stars_match:
            num = re.sub(r"[^\d]", "", stars_match.group(1))
            if num:
                stars_total = int(num)

        out.append(
            {
                "full_name": full_name,
                "repository_url": f"https://github.com/{full_name}",
                "description": description,
                "stars_total": stars_total,
                "language": language,
            }
        )
    return out


def parse_trending_html(html: str) -> list[dict[str, Any]]:
    """Parse trending list HTML to a list of candidate dicts."""
    if not html:
        return []
    try:
        return _parse_with_bs4(html)
    except ImportError:
        return _parse_with_regex(html)
    except Exception as exc:  # noqa: BLE001
        log.warning("bs4 parse failed (%s); falling back to regex", exc)
        return _parse_with_regex(html)


# ---------------------------------------------------------------------------
# Trending page fetch (with disk cache)
# ---------------------------------------------------------------------------

def _cache_key(language: Optional[str], since: str, today_iso: str) -> str:
    lang = language or "all"
    return f"{today_iso}__{lang}__{since}.html"


def _cache_path(language: Optional[str], since: str, today_iso: str) -> Path:
    return CACHE_DIR / _cache_key(language, since, today_iso)


def _today_iso() -> str:
    return _dt.date.today().isoformat()


def fetch_trending_page(
    language: Optional[str] = None,
    since: str = "daily",
    *,
    today_iso: Optional[str] = None,
    use_network: bool = True,
    cache_dir: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Fetch one trending list and return parsed candidates.

    Cached by ``(language, since, today_iso)`` under ``.cache/trending/``;
    a re-run on the same day is fully offline.

    ``use_network=False`` reads only from the cache and returns ``[]`` if
    no cached file exists. The orchestrator wires this to the ``--no-network``
    CLI flag for tests / dry runs.
    """
    cdir = Path(cache_dir) if cache_dir is not None else CACHE_DIR
    cdir.mkdir(parents=True, exist_ok=True)
    key_day = today_iso or _today_iso()
    cpath = cdir / _cache_key(language, since, key_day)

    html: Optional[str] = None
    if cpath.exists():
        try:
            html = cpath.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("trending cache read failed for %s: %s", cpath, exc)

    if html is None:
        if not use_network:
            log.info("trending: no cache for %s and --no-network set", cpath.name)
            return []
        url = TRENDING_BASE
        if language:
            url = f"{TRENDING_BASE}/{language}"
        params = {"since": since}
        try:
            resp = _SESSION.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                log.warning("trending: rate-limited on %s ?since=%s", url, since)
                return []
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:  # noqa: BLE001
            log.warning("trending fetch failed for %s ?since=%s: %s", url, since, exc)
            return []
        try:
            cpath.write_text(html, encoding="utf-8")
        except OSError as exc:
            log.warning("trending cache write failed for %s: %s", cpath, exc)

    return parse_trending_html(html)


# ---------------------------------------------------------------------------
# README fetch
# ---------------------------------------------------------------------------

_README_NAMES = ("README.md", "README.MD", "readme.md", "Readme.md", "README.rst")


def fetch_readme(
    repository_url: str,
    *,
    max_bytes: int = 50_000,
    use_network: bool = True,
    description_fallback: str = "",
) -> str:
    """Best-effort README fetch from ``raw.githubusercontent.com``.

    Walks a small list of common casings on the ``HEAD`` branch and returns
    the first one that yields content (truncated to ``max_bytes``). On total
    failure we return ``description_fallback`` so the relevance scorer always
    has *something* to look at.
    """
    if not use_network:
        return description_fallback or ""
    pair = _owner_repo(repository_url)
    if pair is None:
        return description_fallback or ""
    owner, repo = pair
    for name in _README_NAMES:
        url = f"{RAW_README_BASE}/{owner}/{repo}/HEAD/{name}"
        try:
            resp = _SESSION.get(url, timeout=30, stream=True)
        except requests.RequestException as exc:
            log.debug("readme fetch error %s: %s", url, exc)
            continue
        if resp.status_code != 200:
            continue
        try:
            body = resp.content[: max_bytes + 1]
        finally:
            resp.close()
        text = body.decode("utf-8", errors="replace")
        if len(text) > max_bytes:
            text = text[:max_bytes]
        return text
    return description_fallback or ""


# ---------------------------------------------------------------------------
# Relevance + FM inference
# ---------------------------------------------------------------------------

def score_relevance(text: str) -> float:
    """Weighted-keyword relevance score in ``[0, 1]``.

    Sums ``RELEVANCE_KEYWORDS`` weights for keywords *present* in the
    lowercased text (each keyword counted once, not per-occurrence — this
    avoids a giant README full of the word "lint" pinning the score to 1.0).
    Negative totals clamp to 0.0.
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

    Reuses :data:`pipeline.audit.kg.FM_KEYWORDS` so the rule is identical to
    the heatmap's tier-2 detector. Result is sorted for stability.
    """
    if not text:
        return []
    t = text.lower()
    hits: set[str] = set()
    for fm_id, kws in FM_KEYWORDS.items():
        # FM id literal also counts (e.g. "scope_creep" in README)
        if fm_id in t or fm_id.replace("_", " ") in t or fm_id.replace("_", "-") in t:
            hits.add(fm_id)
            continue
        for kw in kws:
            if kw in t:
                hits.add(fm_id)
                break
    return sorted(hits)


def readme_excerpt(text: str, max_chars: int = 400) -> str:
    """Return a short excerpt from a README — pick the paragraph with the
    highest summed relevance-keyword weight (longer, prose paragraphs that
    mention multiple signals beat short link-list items that mention one).

    Falls back to the leading paragraph when no paragraph has any positive
    signal. Stripping code fences + HTML happens locally so the README
    cache stays untouched.
    """
    if not text:
        return ""
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # Drop heading markers / list bullets so the score isn't dominated by
    # markdown punctuation rather than substance.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    if not paragraphs:
        return ""

    pos_keys = {k: w for k, w in RELEVANCE_KEYWORDS.items() if w > 0}

    def _score(para: str) -> int:
        pl = para.lower()
        return sum(w for k, w in pos_keys.items() if k in pl)

    scored = [(_score(p), -i, p) for i, p in enumerate(paragraphs)]
    scored.sort(reverse=True)
    best_score, _, best_para = scored[0]
    if best_score <= 0:
        return _trim_excerpt(paragraphs[0], max_chars)
    return _trim_excerpt(best_para, max_chars)


def _trim_excerpt(s: str, max_chars: int) -> str:
    s = " ".join(s.split())
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars].rsplit(" ", 1)[0]
    return cut + "..."


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

DEFAULT_LANGUAGES: tuple[Optional[str], ...] = (None, "python", "typescript", "rust")
DEFAULT_SINCE: tuple[str, ...] = ("daily", "weekly")


def iter_default_pages() -> Iterable[tuple[Optional[str], str]]:
    """Iterate the ``(language, since)`` combos used for a real scrape."""
    for lang in DEFAULT_LANGUAGES:
        for since in DEFAULT_SINCE:
            yield lang, since


def page_source_label(language: Optional[str], since: str) -> str:
    """Human-readable label for the ``sources`` array in the snapshot."""
    base = "github.com/trending"
    if language:
        base = f"{base}/{language}"
    return f"{base}?since={since}"


def write_json(path: Path, doc: dict[str, Any]) -> None:
    """Write JSON with a stable indent — used by tests + the orchestrator."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


__all__ = [
    "CACHE_DIR",
    "DEFAULT_LANGUAGES",
    "DEFAULT_SINCE",
    "RELEVANCE_KEYWORDS",
    "RELEVANCE_THRESHOLD",
    "USER_AGENT",
    "fetch_readme",
    "fetch_trending_page",
    "infer_failure_modes",
    "iter_default_pages",
    "normalize_repository_url",
    "page_source_label",
    "parse_trending_html",
    "readme_excerpt",
    "score_relevance",
    "write_json",
]
