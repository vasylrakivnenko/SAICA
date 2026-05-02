"""Backfill the ``abstract`` field on every paper YAML that lacks one.

Why this matters: the citation backfill (`validator/backfill_citations.py`)
scans ``title``/``tldr``/``notes``/``abstract``/``keywords`` for tool
mentions. The original 25 hand-curated papers never populated ``abstract``,
so most of their richest text was invisible to the matcher. This script
closes the gap.

Resolution order, per paper missing ``abstract``:

1. **Local s2_raw cache** — scan ``research/s2_raw/*.json`` for a record
   matching the paper's ``semantic_scholar_id``, ``arxiv_id``, or
   normalized title; copy ``abstract`` if non-empty.
2. **arxiv API** — if the paper has ``arxiv_id`` and step 1 came up empty,
   fetch ``http://export.arxiv.org/api/query?id_list=<id>`` (Atom feed),
   parse the ``summary`` element. Polite: 3-second interval between calls,
   custom User-Agent.
3. **S2 graph API** — last-resort fallback via
   ``https://api.semanticscholar.org/graph/v1/paper/<paperId or arxivId>?fields=abstract``.
   Skipped silently on 429 / network failure.

Edits the YAML in place via ruamel (preserves order/comments/quotes).
Idempotent: re-running on the same data writes nothing because step 1
returns the same value, ruamel diffs to no-op. Runs in well under a
minute even with arxiv API fallbacks.

CLI::

    .venv/bin/python -m validator.enrich_abstracts            # write
    .venv/bin/python -m validator.enrich_abstracts --dry      # report only
    .venv/bin/python -m validator.enrich_abstracts --no-network  # no arxiv/S2 calls
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ruamel.yaml import YAML  # noqa: E402

PAPERS_DIR = REPO / "data" / "papers"
S2_RAW = REPO / "research" / "s2_raw"

USER_AGENT = "SAICA-KG-Abstract-Bot/0.1 (+https://github.com/vasylrakivnenko/SAICA)"
ARXIV_REQUEST_GAP_SECONDS = 3.0
S2_REQUEST_GAP_SECONDS = 1.0
TIMEOUT_SECONDS = 20.0

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


def _make_yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _normalize_title(s: str) -> str:
    """Lowercase, strip punctuation/whitespace — for fuzzy title match."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


# ---------------------------------------------------------------------------
# Source 1: local s2_raw bundles
# ---------------------------------------------------------------------------


def _build_s2_index() -> dict[str, dict]:
    """Return dict keyed by every retrievable id (paperId, arxiv_id, normalized
    title) → the S2 paper record."""
    idx: dict[str, dict] = {}
    for f in glob.glob(str(S2_RAW / "*.json")):
        try:
            doc = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        records = doc.get("data") or doc.get("papers") or []
        for r in records:
            if not isinstance(r, dict):
                continue
            pid = r.get("paperId")
            if pid:
                idx[str(pid)] = r
            ext = r.get("externalIds") or {}
            arxiv = ext.get("ArXiv") if isinstance(ext, dict) else None
            if arxiv:
                idx[f"arxiv:{arxiv}"] = r
            doi = ext.get("DOI") if isinstance(ext, dict) else None
            if doi:
                idx[f"doi:{str(doi).lower()}"] = r
            title = r.get("title")
            if title:
                idx[f"title:{_normalize_title(title)}"] = r
    return idx


def _abstract_from_s2_index(paper: dict, s2_index: dict[str, dict]) -> Optional[str]:
    """Return abstract string from local s2_raw if any id matches."""
    for key in (
        f"arxiv:{paper.get('arxiv_id') or ''}",
        f"doi:{(paper.get('doi') or '').lower()}",
        str(paper.get("semantic_scholar_id") or ""),
        f"title:{_normalize_title(paper.get('title') or '')}",
    ):
        if not key or key.endswith(":"):
            continue
        rec = s2_index.get(key)
        if rec and rec.get("abstract"):
            return str(rec["abstract"]).strip()
    return None


# ---------------------------------------------------------------------------
# Source 2: arxiv API
# ---------------------------------------------------------------------------

_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}
_last_arxiv_call: float = 0.0


def _abstract_from_arxiv(arxiv_id: str) -> Optional[str]:
    """Fetch the abstract for a specific arxiv id. Polite-paced."""
    global _last_arxiv_call
    if not arxiv_id:
        return None
    elapsed = time.time() - _last_arxiv_call
    if elapsed < ARXIV_REQUEST_GAP_SECONDS:
        time.sleep(ARXIV_REQUEST_GAP_SECONDS - elapsed)
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            xml_bytes = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("arxiv fetch failed for %s: %s", arxiv_id, exc)
        return None
    finally:
        _last_arxiv_call = time.time()
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    entry = root.find("atom:entry", _ARXIV_NS)
    if entry is None:
        return None
    summary = entry.find("atom:summary", _ARXIV_NS)
    if summary is None or not summary.text:
        return None
    # arxiv's summary text is multi-line + leading whitespace; collapse it.
    return re.sub(r"\s+", " ", summary.text).strip()


# ---------------------------------------------------------------------------
# Source 3: Semantic Scholar graph API (last-resort fallback)
# ---------------------------------------------------------------------------

_last_s2_call: float = 0.0


def _abstract_from_s2_api(paper: dict) -> Optional[str]:
    """Look up paper by semantic_scholar_id or arxiv_id via the S2 graph API."""
    global _last_s2_call
    sid = paper.get("semantic_scholar_id") or (
        f"arXiv:{paper['arxiv_id']}" if paper.get("arxiv_id") else None
    )
    if not sid:
        return None
    elapsed = time.time() - _last_s2_call
    if elapsed < S2_REQUEST_GAP_SECONDS:
        time.sleep(S2_REQUEST_GAP_SECONDS - elapsed)
    url = f"https://api.semanticscholar.org/graph/v1/paper/{sid}?fields=abstract"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        log.warning("S2 fetch failed for %s: %s", sid, exc)
        return None
    finally:
        _last_s2_call = time.time()
    abs_text = payload.get("abstract")
    return str(abs_text).strip() if abs_text else None


# ---------------------------------------------------------------------------
# Per-paper enrichment
# ---------------------------------------------------------------------------


def _insert_abstract(doc, abstract: str) -> None:
    """Insert the ``abstract`` key into ruamel doc, after ``tldr`` if present."""
    if "abstract" in doc:
        doc["abstract"] = abstract
        return
    keys = list(doc.keys())
    anchor = next((k for k in ("tldr", "notes", "title") if k in keys), None)
    if anchor is None:
        doc["abstract"] = abstract
        return
    pos = keys.index(anchor) + 1
    doc.insert(pos, "abstract", abstract)


def enrich_paper(
    path: Path,
    *,
    yaml: YAML,
    s2_index: dict[str, dict],
    use_network: bool,
) -> tuple[str, Optional[str]]:
    """Enrich one paper. Returns (status, source) where status is one of:
    skipped_has_abstract | wrote | skipped_no_abstract_found.
    """
    with path.open("r", encoding="utf-8") as fh:
        doc = yaml.load(fh)
    if not isinstance(doc, dict):
        return ("skipped_no_abstract_found", None)
    if doc.get("abstract"):
        return ("skipped_has_abstract", None)

    abstract = _abstract_from_s2_index(doc, s2_index)
    source = "s2_raw" if abstract else None
    if not abstract and use_network and doc.get("arxiv_id"):
        abstract = _abstract_from_arxiv(str(doc["arxiv_id"]))
        if abstract:
            source = "arxiv"
    if not abstract and use_network:
        abstract = _abstract_from_s2_api(doc)
        if abstract:
            source = "s2_api"
    if not abstract:
        return ("skipped_no_abstract_found", None)

    _insert_abstract(doc, abstract)
    buf = io.StringIO()
    yaml.dump(doc, buf)
    new_text = buf.getvalue()
    if new_text == path.read_text(encoding="utf-8"):
        return ("skipped_has_abstract", None)
    path.write_text(new_text, encoding="utf-8")
    return ("wrote", source)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry", action="store_true", help="print proposed enrichments without writing"
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="skip arxiv + S2 API; use only local s2_raw cache",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s"
    )

    yaml = _make_yaml()
    s2_index = _build_s2_index()
    print(f"s2_raw index size: {len(s2_index)} keys")
    paths = sorted(PAPERS_DIR.glob("*.yml"))

    counts = {"wrote": 0, "skipped_has_abstract": 0, "skipped_no_abstract_found": 0}
    sources = {"s2_raw": 0, "arxiv": 0, "s2_api": 0}

    for path in paths:
        if args.dry:
            with path.open("r", encoding="utf-8") as fh:
                doc = yaml.load(fh)
            if not isinstance(doc, dict) or doc.get("abstract"):
                counts["skipped_has_abstract"] += 1
                continue
            abstract = _abstract_from_s2_index(doc, s2_index)
            if abstract:
                counts["wrote"] += 1
                sources["s2_raw"] += 1
                print(f"  PREVIEW {path.name:60s} (s2_raw, {len(abstract)} chars)")
            elif args.no_network:
                counts["skipped_no_abstract_found"] += 1
            else:
                # Don't actually fetch in --dry; just note.
                print(f"  PREVIEW {path.name:60s} (would query arxiv/S2)")
                counts["wrote"] += 1
        else:
            status, source = enrich_paper(
                path,
                yaml=yaml,
                s2_index=s2_index,
                use_network=not args.no_network,
            )
            counts[status] = counts.get(status, 0) + 1
            if source:
                sources[source] = sources.get(source, 0) + 1
            if status == "wrote":
                print(f"  wrote   {path.name:60s} (source={source})")
            elif status == "skipped_no_abstract_found":
                print(f"  no-abs  {path.name:60s}")

    print()
    print("summary:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print("sources:")
    for k, v in sources.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
