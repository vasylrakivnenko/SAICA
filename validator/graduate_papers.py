"""Graduate paper *candidates* (S2 / Elicit / candidate-list bundles) into
``data/papers/<id>.yml`` files that conform to ``schema/paper.schema.json``.

Pipeline
--------

1. **Load existing graduated papers** under ``data/papers/`` and build a dedup
   index keyed by (id, normalized title, arxiv id, doi).
2. **Walk each source bundle** under ``research/`` and normalize every paper
   into a common ``Candidate`` shape (s2 / elicit / candidates_*).
3. **Score** each candidate using a relevance + recency + citation heuristic
   (reuse of ``research/analyze.py`` plus a per-candidate quality floor).
4. **Filter** to candidates that look like genuine SAICA-KG material:
   coding-agent failure modes, supervision, evaluation, taxonomies,
   MCP/security, etc. Drop pure-ML / pure-NLP / domain-specific (medical,
   geospatial-only, hardware-only) papers.
5. **Sort by score, dedup, accept up to N** (default 30).
6. **Editorialize** each accepted candidate: derive a kebab-case id, write a
   1-2 sentence ``tldr``, write a longer ``notes`` block that explicitly
   names the SAICA-KG failure modes the paper relates to (so a future
   indexer can pick them up).
7. **Validate** each YAML against ``pipeline.models.Paper`` before writing.
   Skip and report any that won't validate.
8. **Write** ``data/papers/<id>.yml`` (only new files; never modifies
   existing).
9. **Emit a per-paper report** to ``validator/graduate_papers.report.md``.

This script is intentionally self-contained: it does not touch tool YAMLs,
the schema, or other pipeline modules.

Usage
-----

.. code-block:: shell

    python -m validator.graduate_papers --dry              # plan only, no writes
    python -m validator.graduate_papers --limit 25         # cap accepted papers
    python -m validator.graduate_papers --from-source s2   # one source only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
PAPERS_DIR = DATA_DIR / "papers"
RESEARCH_DIR = REPO / "research"
S2_RAW_DIR = RESEARCH_DIR / "s2_raw"
ELICIT_RAW_DIR = RESEARCH_DIR / "elicit_raw"
REPORT_PATH = REPO / "validator" / "graduate_papers.report.md"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline.models import Paper  # noqa: E402

# --- Failure-mode keyword index -------------------------------------------
#
# Each accepted paper gets a notes block that cites the SAICA-KG failure
# modes it relates to *as written* in snake_case, so a future indexer can
# pick them up. We surface modes from a keyword scan over (title + tldr +
# abstract); humans can later refine.

FAILURE_MODES = (
    "fabrication",
    "obsolescence",
    "dependency_blindness",
    "logic_error",
    "security_vulnerability",
    "scope_creep",
    "context_pollution",
    "supply_chain_attack",
    "cascading_failure",
    "incomplete_execution",
    "test_manipulation",
)

# Keywords -> failure mode id. Multi-token entries are matched as substrings
# (case-insensitive) on the combined title + tldr + abstract text. Tuned to
# avoid wild over-matching: e.g. "package" alone is too generic, so we
# require "package hallucinat" / "slopsquat".
_MODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fabrication": (
        "hallucinat",  # hallucination, hallucinated, hallucinations
        "fabricat",
        "ungrounded",
        "made up",
    ),
    "obsolescence": (
        "deprecat",
        "version drift",
        "library evolution",
        "api evolution",
        "library version",
        "obsolete",
        "outdated",
    ),
    "dependency_blindness": (
        "dependency",
        "api hallucinat",
        "import error",
        "missing import",
    ),
    "logic_error": (
        "logic error",
        "logical error",
        "reasoning failure",
        "wrong answer",
        "incorrect output",
        "buggy code",
        "fault localization",
        "bug",
    ),
    "security_vulnerability": (
        "vulnerab",
        "insecure code",
        "cwe",
        "security flaw",
        "exploit",
        "attack vector",
        "prompt injection",
        "jailbreak",
    ),
    "scope_creep": (
        "scope creep",
        "over-generation",
        "unwanted feature",
        "spec deviation",
        "intent misalignment",
        "off-task",
    ),
    "context_pollution": (
        "context window",
        "context-boundary",
        "context boundary",
        "context pruning",
        "context pollut",
        "long context",
        "context drift",
    ),
    "supply_chain_attack": (
        "supply chain",
        "slopsquat",
        "package hallucinat",
        "malicious package",
        "malicious mcp",
        "typosquat",
    ),
    "cascading_failure": (
        "cascading",
        "propagat",
        "cascade",
        "fault propagation",
        "error propagation",
    ),
    "incomplete_execution": (
        "incomplete",
        "task completion",
        "did not finish",
        "partial solution",
        "abandoned",
        "stuck",
        "timeout",
    ),
    "test_manipulation": (
        "test manipulation",
        "test gaming",
        "reward hacking",
        "specification gaming",
        "overfit to test",
        "cheating on benchmark",
        "test smell",
    ),
}


def detect_failure_modes(text: str) -> list[str]:
    """Return the SAICA-KG failure modes a paper plausibly relates to.

    Picks at least one mode (the highest-scoring keyword family) so every
    notes block has at least one ``snake_case`` failure-mode tag for the
    indexer.
    """
    if not text:
        return []
    t = text.lower()
    scored: list[tuple[str, int]] = []
    for mode, keywords in _MODE_KEYWORDS.items():
        hits = sum(1 for k in keywords if k in t)
        if hits:
            scored.append((mode, hits))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [m for m, _ in scored]


# --- Topic relevance gating -----------------------------------------------
#
# Hard "include" signals — a candidate must have at least one of these or it
# gets dropped. Hard "exclude" signals — a candidate with any of these is
# dropped regardless of include hits. Tuned conservatively per the prompt:
# quality > quantity.

# Topic gating works in two halves: a candidate must hit at least one
# "domain" keyword (this is a coding-agent / supervision / KG paper) AND at
# least one "concern" keyword (failure modes, eval, taxonomy, security,
# etc.). Anything that hits "domain" but not "concern" is usually a generic
# capability paper; anything that hits "concern" but not "domain" is
# usually about something other than coding agents.
_DOMAIN_KEYWORDS = (
    "coding agent",
    "code agent",
    "code generation",
    "code-generation",
    "code llm",
    "code llms",
    "code-llm",
    "llm code",
    "llm-generated code",
    "llm-based code",
    "llm-powered code",
    "software engineering agent",
    "swe agent",
    "swe-bench",
    "swe bench",
    "agentic ai",
    "agentic system",
    "llm agent",
    "ai agent",
    "ai coding",
    "code review",
    "code repair",
    "code synthesis",
    "model context protocol",
    " mcp ",
    "mcp server",
    "mcp tool",
    "mcp-",
    "tool use",
    "tool-use",
    "software supply chain",
    "package hallucinat",
    "slopsquat",
    "deprecated api",
    "library evolution",
    "api evolution",
    "package",
    "library",
)

_CONCERN_KEYWORDS = (
    "supervis",
    "monitoring",
    "monitor",
    "guardrail",
    "sandbox",
    "verification",
    "evaluation",
    "benchmark",
    "taxonomy",
    "failure mode",
    "fault",
    "hallucinat",
    "supply chain",
    "knowledge graph",
    "ontolog",
    "faceted",
    "mece",
    "deprecat",
    "autonomy",
    "human-in-the-loop",
    "hitl",
    "incident",
    "trajectory",
    "oversight",
    "governance",
    "red team",
    "red-team",
    "vulnerab",
    "security",
    "static analysis",
    "patch",
    "automated repair",
    "self-debug",
    "self debug",
    "reflexion",
    "retrieval-augmented",
    "retrieval augmented",
    " rag ",
    "reliability",
    "robust",
    "trust",
    "explainab",
    "empirical study",
    "empirical investigation",
    "case study",
    "survey",
    "review",
    "risk",
    "control",
    "safety",
    "alignment",
)

_EXCLUDE_KEYWORDS = (
    "geospatial",
    "verilog",
    "hdl",
    "hardware verification",
    "hardware design",
    "embedded machine learning",
    "embedded ml",
    "pde",
    "partial differential equation",
    "robot arm",
    "molecular",
    "genome",
    "clinical trial",
    "medical imaging",
    "agriculture",
    "crop",
    "sentiment analysis",
    "social media sentiment",
    "classroom",
    "students",
    "teaching",
    "iot ",
    "sensor",
    "air quality",
    "power flow",
    "smart grid",
    "manufacturing",
    "ehr",
    "clinical decision",
    "anomaly detection service",
    "site reliability engineer",
    "graph convolutional",
    "self-play",
    "speech recognition",
    "image generation",
    "text-to-image",
    "3d generation",
    "video generation",
    "drug discovery",
    "materials discovery",
    "chemistry",
    "physics simulation",
    "wireless",
    "5g",
    "satellite",
    "ad hoc network",
)


# --- Title slug / id helpers ----------------------------------------------

_SLUG_STOPWORDS = {
    "a", "an", "the", "of", "for", "to", "and", "or", "in", "on", "with",
    "from", "by", "via", "across", "between", "into", "is", "are", "be",
    "as", "at", "this", "that", "these", "those", "we", "our", "their",
    "its", "it", "can", "will", "do", "how", "why", "what", "when",
    "toward", "towards", "based",
}

_NON_ALPHANUM = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_words: int = 5) -> str:
    """kebab-case slug of ``text`` truncated to ``max_words`` content words."""
    words = _NON_ALPHANUM.sub(" ", (text or "").lower()).split()
    keep = [w for w in words if w and w not in _SLUG_STOPWORDS]
    if not keep:
        keep = [w for w in words if w]
    return "-".join(keep[:max_words])


def _last_name(author: str) -> str:
    """Best-effort last-name extraction from a Semantic-Scholar / Elicit
    author string. Drops trailing punctuation and the leading initials in
    "F. Last" or "First M. Last" forms.
    """
    a = (author or "").strip().rstrip(".,;").strip()
    if not a or a.lower() in {"et al.", "et al"}:
        return ""
    parts = a.split()
    # "F. Khomh" -> "Khomh"; "Fang Liu" -> "Liu".
    return parts[-1] if parts else ""


def make_paper_id(authors: list[str], year: int, title: str) -> str:
    """Generate kebab-case id of the form
    ``<firstauthor-lastname>-<year>-<short-slug>``.

    Non-alphanumeric chars are stripped; the slug is capped to 5 content
    words so the id stays short and human-scannable.
    """
    last = ""
    for a in authors:
        candidate = _last_name(a)
        if candidate:
            last = candidate
            break
    last_slug = _slugify(last, max_words=2) or "anon"
    title_slug = _slugify(title, max_words=4) or "untitled"
    raw = f"{last_slug}-{year}-{title_slug}"
    raw = _NON_ALPHANUM.sub("-", raw).strip("-")
    return raw or f"paper-{year}"


def _normalize_title(title: str) -> str:
    """Title slug used purely for dedup. Strips stopwords *and* punctuation
    so casing / minor wording diffs collapse together.
    """
    return _slugify(title or "", max_words=12)


def _strip_arxiv(value: str | None) -> str | None:
    """Drop a leading ``arxiv:`` / ``arXiv:`` prefix from an arXiv id."""
    if not value:
        return None
    v = str(value).strip()
    if not v:
        return None
    if v.lower().startswith("arxiv:"):
        v = v.split(":", 1)[1].strip()
    return v or None


def _strip_doi(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip().lower()
    return v or None


# --- Candidate datamodel --------------------------------------------------


@dataclass
class Candidate:
    """A normalized paper candidate from any source bundle."""

    source: str          # e.g. "s2:llm-code-failure-taxonomy", "elicit:Q1"
    title: str
    authors: list[str]
    year: int
    abstract: str
    tldr: str
    venue: str
    url: str
    doi: str | None
    arxiv_id: str | None
    semantic_scholar_id: str | None
    citation_count: int

    score: int = 0
    failure_modes: list[str] = field(default_factory=list)

    def text_blob(self) -> str:
        return " ".join(
            [self.title, self.tldr, self.abstract, self.venue]
        ).lower()

    def dedup_keys(self) -> tuple[str | None, str | None, str | None]:
        return (
            _strip_arxiv(self.arxiv_id),
            _strip_doi(self.doi),
            _normalize_title(self.title),
        )


# --- Source loaders -------------------------------------------------------


def _norm_authors(raw: Any) -> list[str]:
    """Flatten S2 / Elicit author shapes into a plain list of names."""
    if not raw:
        return []
    out: list[str] = []
    for a in raw:
        if isinstance(a, dict):
            name = a.get("name") or ""
        else:
            name = str(a)
        name = name.strip()
        if name:
            out.append(name)
    return out


def _s2_to_candidate(p: dict[str, Any], slug: str) -> Candidate | None:
    title = (p.get("title") or "").strip()
    if not title:
        return None
    ext = p.get("externalIds") or {}
    arxiv_id = _strip_arxiv(ext.get("ArXiv"))
    doi = ext.get("DOI")
    tldr_blob = (p.get("tldr") or {}).get("text") or ""
    return Candidate(
        source=f"s2:{slug}",
        title=title,
        authors=_norm_authors(p.get("authors")),
        year=int(p.get("year") or 0),
        abstract=(p.get("abstract") or "").strip(),
        tldr=tldr_blob.strip(),
        venue=(p.get("venue") or "").strip(),
        url=(p.get("url") or "").strip(),
        doi=doi,
        arxiv_id=arxiv_id,
        semantic_scholar_id=p.get("paperId"),
        citation_count=int(p.get("citationCount") or 0),
    )


def _elicit_to_candidate(p: dict[str, Any], slug: str) -> Candidate | None:
    title = (p.get("title") or "").strip()
    if not title:
        return None
    urls = p.get("urls") or []
    arxiv_id = None
    url = ""
    if urls:
        url = urls[0]
        m = re.search(r"arxiv\.org/(?:abs|pdf)/([\d.]+)", url)
        if m:
            arxiv_id = m.group(1)
    if not arxiv_id and p.get("doi") and "arxiv" in str(p["doi"]).lower():
        m = re.search(r"arxiv\.([\d.]+)", str(p["doi"]).lower())
        if m:
            arxiv_id = m.group(1)
    return Candidate(
        source=f"elicit:{slug}",
        title=title,
        authors=_norm_authors(p.get("authors")),
        year=int(p.get("year") or 0),
        abstract=(p.get("abstract") or "").strip(),
        tldr="",
        venue=(p.get("venue") or "").strip(),
        url=url,
        doi=p.get("doi"),
        arxiv_id=arxiv_id,
        semantic_scholar_id=(p.get("elicitId") or "").replace("ss-", "")
        or None,
        citation_count=int(p.get("citedByCount") or 0),
    )


def load_s2() -> list[Candidate]:
    out: list[Candidate] = []
    if not S2_RAW_DIR.exists():
        return out
    for fn in sorted(S2_RAW_DIR.glob("*.json")):
        slug = fn.stem
        try:
            data = json.loads(fn.read_text())
        except json.JSONDecodeError:
            continue
        for p in data.get("data") or []:
            c = _s2_to_candidate(p, slug)
            if c:
                out.append(c)
    return out


def load_elicit() -> list[Candidate]:
    out: list[Candidate] = []
    if not ELICIT_RAW_DIR.exists():
        return out
    for fn in sorted(ELICIT_RAW_DIR.glob("*.json")):
        slug = fn.stem
        try:
            data = json.loads(fn.read_text())
        except json.JSONDecodeError:
            continue
        for p in data.get("papers") or []:
            c = _elicit_to_candidate(p, slug)
            if c:
                out.append(c)
    return out


def load_candidates() -> list[Candidate]:
    """The ``research/candidates_*.json`` bundles are GitHub-tool oriented;
    they contain no paper-shaped entries. We keep this loader for the
    --from-source CLI option but it returns an empty list.
    """
    return []


# --- Scoring & filtering --------------------------------------------------


_POSITIVE_KEYWORDS = (
    ("taxonomy", 3),
    ("failure mode", 3),
    ("hallucinat", 3),
    ("coding agent", 3),
    ("code agent", 3),
    ("agentic", 2),
    ("supervis", 2),
    ("monitoring", 2),
    ("oversight", 2),
    ("benchmark", 2),
    ("empirical study", 2),
    ("knowledge graph", 2),
    ("supply chain", 2),
    ("slopsquat", 3),
    ("package hallucinat", 3),
    ("mcp", 2),
    ("model context protocol", 3),
    ("guardrail", 2),
    ("sandbox", 2),
    ("autonomy", 2),
    ("control monitoring", 3),
    ("crosswalk", 2),
    ("ontolog", 2),
    ("faceted", 2),
    ("mece", 2),
    ("deprecat", 2),
    ("library evolution", 3),
    ("api evolution", 3),
    ("self-debug", 1),
    ("reflexion", 1),
    ("retrieval-augmented code", 2),
    ("incident", 2),
    ("red team", 2),
    ("survey", 1),
)


def score_candidate(c: Candidate) -> int:
    """Heuristic relevance score (higher = more SAICA-KG-relevant).

    Mirrors ``research/analyze.py`` but with stricter coding-agent / agent
    weighting and a recency floor so 2025-26 papers win ties.
    """
    text = c.text_blob()
    if not text:
        return -1000
    s = 0
    for kw, w in _POSITIVE_KEYWORDS:
        if kw in text:
            s += w
    if c.year >= 2026:
        s += 5
    elif c.year == 2025:
        s += 4
    elif c.year == 2024:
        s += 2
    elif c.year >= 2022:
        s += 1
    elif c.year > 0 and c.year < 2018:
        s -= 3
    cc = c.citation_count
    if cc >= 500:
        s += 5
    elif cc >= 100:
        s += 4
    elif cc >= 30:
        s += 3
    elif cc >= 10:
        s += 2
    elif cc >= 3:
        s += 1
    if not c.tldr and not c.abstract:
        s -= 5
    elif len((c.tldr + " " + c.abstract).strip()) < 200:
        s -= 2
    return s


def passes_topic_filter(c: Candidate) -> bool:
    """Hard include/exclude gate.

    A candidate must:
      - hit at least one *domain* keyword (this is a coding-agent / MCP /
        supervision paper)
      - hit at least one *concern* keyword (failure modes, evaluation,
        taxonomy, security, ...)
      - miss every exclude keyword
      - have at least one author and a sane year (>= 2017)
    """
    text = c.text_blob()
    if not text:
        return False
    if not any(k in text for k in _DOMAIN_KEYWORDS):
        return False
    if not any(k in text for k in _CONCERN_KEYWORDS):
        return False
    if any(k in text for k in _EXCLUDE_KEYWORDS):
        return False
    if not c.authors:
        return False
    if c.year < 2017:
        return False
    return True


# --- Editorial templates --------------------------------------------------


def _pick_tldr(c: Candidate) -> str:
    """Prefer S2's tldr; fall back to a 1-2 sentence trim of the abstract."""
    if c.tldr:
        return c.tldr.strip()
    if not c.abstract:
        return c.title
    sentences = re.split(r"(?<=[.!?])\s+", c.abstract.strip())
    out: list[str] = []
    for s in sentences:
        out.append(s)
        if sum(len(x) for x in out) > 220:
            break
        if len(out) >= 2:
            break
    return " ".join(out).strip()


def _build_notes(c: Candidate, modes: list[str]) -> str:
    """Editorial notes block — mentions the SAICA-KG failure modes the
    paper plausibly informs. The mode names are written as snake_case so a
    future indexer can extract them.
    """
    if modes:
        modes_phrase = ", ".join(modes)
        first_sentence = (
            f"Relates to SAICA-KG failure modes: {modes_phrase}."
        )
    else:
        first_sentence = (
            "Relates to SAICA-KG's broader supervision / coding-agent"
            " evaluation theme; specific failure-mode tags pending"
            " editorial review."
        )
    second_sentence = (
        "Auto-graduated from candidate pool; review the editorial framing"
        f" before promoting to a primary cite. Source: {c.source}."
    )
    return f"{first_sentence} {second_sentence}"


def _venue(c: Candidate) -> str | None:
    """Normalize empty / arxiv-org venues to the canonical ``arXiv``."""
    v = (c.venue or "").strip()
    if not v:
        if c.arxiv_id:
            return "arXiv"
        return None
    if v.lower() in {"arxiv.org", "arxiv"}:
        return "arXiv"
    return v


def _url(c: Candidate) -> str | None:
    if c.url:
        return c.url
    if c.arxiv_id:
        return f"https://arxiv.org/abs/{c.arxiv_id}"
    if c.doi:
        return f"https://doi.org/{c.doi}"
    return None


def _relevance_tags(c: Candidate, modes: list[str]) -> list[str]:
    """Pick 3-6 free-form tags. We keep these stable so editors can later
    grep + replace.
    """
    tags: list[str] = []
    text = c.text_blob()
    if "taxonomy" in text or "failure mode" in text:
        tags.append("failure-mode-taxonomy")
    if "coding agent" in text or "code agent" in text or "swe-bench" in text:
        tags.append("coding-agent")
    if "agentic" in text or "llm agent" in text:
        tags.append("agentic-ai")
    if "supervis" in text or "monitoring" in text or "oversight" in text:
        tags.append("supervision")
    if "mcp" in text or "model context protocol" in text:
        tags.append("MCP")
    if "benchmark" in text or "evaluation" in text:
        tags.append("benchmark")
    if "supply chain" in text or "slopsquat" in text or "package hallucinat" in text:
        tags.append("supply-chain")
    if "knowledge graph" in text or "ontolog" in text:
        tags.append("knowledge-graph")
    if "empirical study" in text or "grounded theory" in text:
        tags.append("empirical")
    if "survey" in text:
        tags.append("survey")
    if "deprecat" in text or "library evolution" in text or "api evolution" in text:
        tags.append("api-evolution")
    if "red team" in text or "red-team" in text:
        tags.append("red-teaming")
    if "autonomy" in text:
        tags.append("autonomy")
    if "guardrail" in text or "sandbox" in text:
        tags.append("guardrails")
    # Keep the list short; cap at 6.
    seen: set[str] = set()
    deduped = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    if not deduped:
        deduped = ["coding-agent"]
    return deduped[:6]


# --- YAML build / write ---------------------------------------------------


def _block_scalar(text: str) -> str:
    """Indent a string for use under a YAML ``>`` block scalar.

    We hand-format YAML to match the existing paper file style (folded
    block scalars, double-quoted ids, bare keys). ``ruamel.yaml`` would
    work too, but the existing files mix conventions; hand-writing keeps
    the diff small.
    """
    if not text:
        return ""
    text = " ".join(text.split())  # collapse whitespace
    # crude wrap at ~76 cols
    words = text.split()
    lines: list[str] = []
    cur = "  "
    for w in words:
        if len(cur) + len(w) + 1 > 76 and cur.strip():
            lines.append(cur.rstrip())
            cur = "  " + w
        else:
            cur = cur + (" " if cur != "  " else "") + w
    if cur.strip():
        lines.append(cur.rstrip())
    return "\n".join(lines)


def candidate_to_yaml(c: Candidate, paper_id: str, modes: list[str]) -> tuple[str, dict]:
    """Render the YAML body and the equivalent dict (for validation)."""
    venue = _venue(c)
    url = _url(c)
    tldr = _pick_tldr(c)
    notes = _build_notes(c, modes)
    tags = _relevance_tags(c, modes)
    abstract = c.abstract.strip() if c.abstract else None

    payload: dict[str, Any] = {
        "id": paper_id,
        "authors": c.authors,
        "year": c.year,
        "title": c.title,
    }
    if venue:
        payload["venue"] = venue
    if url:
        payload["url"] = url
    if c.doi:
        payload["doi"] = c.doi
    if c.arxiv_id:
        payload["arxiv_id"] = c.arxiv_id
    if c.semantic_scholar_id:
        payload["semantic_scholar_id"] = c.semantic_scholar_id
    if c.citation_count:
        payload["citation_count"] = c.citation_count
    if abstract:
        payload["abstract"] = abstract
    if tldr:
        payload["tldr"] = tldr
    if tags:
        payload["relevance_tags"] = tags
    if notes:
        payload["notes"] = notes

    # Hand-formatted YAML so the file matches the existing style.
    lines: list[str] = []
    lines.append(f"id: {paper_id}")
    lines.append("authors:")
    for a in c.authors:
        # Quote if it contains a colon, comma, or starts with a punctuation.
        if any(ch in a for ch in ":#") or a.startswith(("-", "?", "!", "&", "*", "'", '"')):
            quoted = a.replace('"', '\\"')
            lines.append(f'  - "{quoted}"')
        else:
            lines.append(f"  - {a}")
    lines.append(f"year: {c.year}")
    title = c.title.replace('"', '\\"')
    lines.append(f'title: "{title}"')
    if venue:
        if any(ch in venue for ch in ":#"):
            v = venue.replace('"', '\\"')
            lines.append(f'venue: "{v}"')
        else:
            lines.append(f"venue: {venue}")
    if c.arxiv_id:
        lines.append(f'arxiv_id: "{c.arxiv_id}"')
    if c.doi:
        lines.append(f'doi: "{c.doi}"')
    if url:
        lines.append(f"url: {url}")
    if c.semantic_scholar_id:
        lines.append(f'semantic_scholar_id: "{c.semantic_scholar_id}"')
    if c.citation_count:
        lines.append(f"citation_count: {c.citation_count}")
    if abstract:
        lines.append("abstract: >")
        lines.append(_block_scalar(abstract))
    if tldr:
        lines.append("tldr: >")
        lines.append(_block_scalar(tldr))
    if tags:
        lines.append("relevance_tags:")
        for t in tags:
            lines.append(f"  - {t}")
    if notes:
        lines.append("notes: >")
        lines.append(_block_scalar(notes))
    return "\n".join(lines) + "\n", payload


def validate_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    """Validate a paper dict against ``pipeline.models.Paper``."""
    try:
        Paper.model_validate(payload)
    except Exception as exc:  # pragma: no cover — surface in report
        return False, str(exc).replace("\n", " ")[:400]
    return True, ""


# --- Dedup index ----------------------------------------------------------


@dataclass
class DedupIndex:
    """Tracks (id, arxiv_id, doi, normalized_title) of every paper already
    in the KG plus any we accept this run.
    """

    ids: set[str] = field(default_factory=set)
    arxiv_ids: set[str] = field(default_factory=set)
    dois: set[str] = field(default_factory=set)
    titles: set[str] = field(default_factory=set)

    @classmethod
    def from_existing(cls, papers_dir: Path) -> "DedupIndex":
        idx = cls()
        for fp in sorted(papers_dir.glob("*.yml")):
            try:
                data = yaml.safe_load(fp.read_text())
            except yaml.YAMLError:
                continue
            if not isinstance(data, dict):
                continue
            pid = data.get("id")
            if pid:
                idx.ids.add(pid)
            ax = _strip_arxiv(data.get("arxiv_id"))
            if ax:
                idx.arxiv_ids.add(ax)
            doi = _strip_doi(data.get("doi"))
            if doi:
                idx.dois.add(doi)
            ts = _normalize_title(data.get("title") or "")
            if ts:
                idx.titles.add(ts)
        # Also seed with non-paper ids so we never collide with a Tool id.
        return idx

    def seed_from_manifest(self, manifest_path: Path) -> None:
        """Add every id declared in MANIFEST.json so the new paper id is
        unique across the whole KG (papers + tools + everything else).
        """
        if not manifest_path.exists():
            return
        try:
            mf = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            return
        for kind, entry in (mf.get("ids") or {}).items():
            if isinstance(entry, dict):
                self.ids.update(entry.keys())
            elif isinstance(entry, list):
                self.ids.update(entry)

    def is_duplicate(self, c: Candidate) -> str | None:
        """Return a human-readable reason if ``c`` duplicates an existing
        paper; None otherwise.
        """
        ax, doi, title = c.dedup_keys()
        if ax and ax in self.arxiv_ids:
            return f"arxiv_id={ax}"
        if doi and doi in self.dois:
            return f"doi={doi}"
        if title and title in self.titles:
            return f"title={title}"
        return None

    def add(self, paper_id: str, c: Candidate) -> None:
        self.ids.add(paper_id)
        ax, doi, title = c.dedup_keys()
        if ax:
            self.arxiv_ids.add(ax)
        if doi:
            self.dois.add(doi)
        if title:
            self.titles.add(title)

    def unique_id(self, base: str) -> str:
        """Disambiguate ``base`` against ``self.ids`` by appending ``-2``,
        ``-3`` … until we find something free.
        """
        if base not in self.ids:
            return base
        i = 2
        while f"{base}-{i}" in self.ids:
            i += 1
        return f"{base}-{i}"


# --- Orchestration --------------------------------------------------------


def gather_candidates(sources: Iterable[str]) -> list[Candidate]:
    out: list[Candidate] = []
    if "s2" in sources:
        out.extend(load_s2())
    if "elicit" in sources:
        out.extend(load_elicit())
    if "candidates" in sources:
        out.extend(load_candidates())
    return out


def dedup_candidates(cands: list[Candidate]) -> list[Candidate]:
    """Collapse identical (arxiv / doi / title) candidates that came from
    multiple S2 / Elicit queries — keep the highest-scoring instance.
    """
    by_key: dict[tuple[str, str, str], Candidate] = {}
    for c in cands:
        ax, doi, title = c.dedup_keys()
        key = (ax or "", doi or "", title or "")
        prev = by_key.get(key)
        if prev is None or (c.score, c.citation_count) > (prev.score, prev.citation_count):
            by_key[key] = c
    return list(by_key.values())


def run(
    *,
    dry: bool,
    limit: int,
    sources: tuple[str, ...],
    papers_dir: Path = PAPERS_DIR,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    """End-to-end orchestration. Returns a summary dict for tests / CLI."""
    cands = gather_candidates(sources)
    total_loaded = len(cands)

    # Score & topic-filter
    for c in cands:
        c.score = score_candidate(c)
        c.failure_modes = detect_failure_modes(c.text_blob())
    eligible = [c for c in cands if passes_topic_filter(c)]
    eligible = dedup_candidates(eligible)
    eligible.sort(
        key=lambda c: (c.score, c.citation_count, c.year),
        reverse=True,
    )

    dedup_idx = DedupIndex.from_existing(papers_dir)
    dedup_idx.seed_from_manifest(DATA_DIR / "MANIFEST.json")

    accepted: list[tuple[str, Candidate, list[str]]] = []
    skipped_dup: list[tuple[Candidate, str]] = []
    skipped_invalid: list[tuple[Candidate, str]] = []

    for c in eligible:
        if len(accepted) >= limit:
            break
        reason = dedup_idx.is_duplicate(c)
        if reason:
            skipped_dup.append((c, reason))
            continue
        base_id = make_paper_id(c.authors, c.year, c.title)
        paper_id = dedup_idx.unique_id(base_id)
        modes = c.failure_modes or detect_failure_modes(c.text_blob())
        body, payload = candidate_to_yaml(c, paper_id, modes)
        ok, err = validate_payload(payload)
        if not ok:
            skipped_invalid.append((c, err))
            continue
        accepted.append((paper_id, c, modes))
        # Reserve the id and dedup keys so a near-duplicate later in the
        # ranking doesn't sneak in.
        dedup_idx.add(paper_id, c)
        if not dry:
            (papers_dir / f"{paper_id}.yml").write_text(body)

    # Write report
    write_report(
        report_path,
        total_loaded=total_loaded,
        eligible_count=len(eligible),
        accepted=accepted,
        skipped_dup=skipped_dup,
        skipped_invalid=skipped_invalid,
        dry=dry,
        limit=limit,
        sources=sources,
    )

    return {
        "loaded": total_loaded,
        "eligible": len(eligible),
        "accepted": len(accepted),
        "skipped_duplicates": len(skipped_dup),
        "skipped_invalid": len(skipped_invalid),
        "accepted_ids": [p for p, _, _ in accepted],
    }


def write_report(
    path: Path,
    *,
    total_loaded: int,
    eligible_count: int,
    accepted: list[tuple[str, Candidate, list[str]]],
    skipped_dup: list[tuple[Candidate, str]],
    skipped_invalid: list[tuple[Candidate, str]],
    dry: bool,
    limit: int,
    sources: tuple[str, ...],
) -> None:
    lines: list[str] = []
    lines.append("# graduate_papers report")
    lines.append("")
    lines.append(f"- Mode: {'dry-run' if dry else 'write'}")
    lines.append(f"- Limit: {limit}")
    lines.append(f"- Sources: {', '.join(sources)}")
    lines.append(f"- Candidates loaded: {total_loaded}")
    lines.append(f"- Eligible after topic filter & dedup: {eligible_count}")
    lines.append(f"- Accepted: {len(accepted)}")
    lines.append(f"- Skipped (duplicate): {len(skipped_dup)}")
    lines.append(f"- Skipped (schema-invalid): {len(skipped_invalid)}")
    lines.append("")
    lines.append("## Accepted papers")
    lines.append("")
    if accepted:
        lines.append("| id | year | citations | score | source | failure_modes |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for pid, c, modes in accepted:
            modes_str = ", ".join(modes) if modes else "—"
            lines.append(
                f"| `{pid}` | {c.year} | {c.citation_count} | {c.score} |"
                f" `{c.source}` | {modes_str} |"
            )
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Top 20 skipped duplicates")
    lines.append("")
    if skipped_dup:
        for c, reason in skipped_dup[:20]:
            lines.append(f"- **{c.title}** ({c.year}) — {reason} — score={c.score}")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Schema-invalid candidates")
    lines.append("")
    if skipped_invalid:
        for c, err in skipped_invalid:
            lines.append(f"- **{c.title}** ({c.year}) — {err}")
    else:
        lines.append("_None._")
    lines.append("")
    path.write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry", action="store_true", help="Plan only; don't write YAMLs.")
    ap.add_argument("--limit", type=int, default=30, help="Cap on accepted papers (default 30).")
    ap.add_argument(
        "--from-source",
        choices=["s2", "elicit", "candidates", "all"],
        default="all",
        help="Source filter (default 'all').",
    )
    args = ap.parse_args(argv)

    if args.from_source == "all":
        sources = ("s2", "elicit", "candidates")
    else:
        sources = (args.from_source,)

    summary = run(dry=args.dry, limit=args.limit, sources=sources)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
