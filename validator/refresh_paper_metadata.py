#!/usr/bin/env python3
"""Refresh ``title``, ``authors`` and ``year`` of the paper records from the
paper's own registry: the arXiv API, or Crossref for records without an
arXiv id.

Why: the paper records were typed by hand or written by a script from
Semantic Scholar search dumps. Semantic Scholar lists *author entities*,
not the byline, so names came out shortened or merged with another
person's ("Y. Piao", "Xing Peng" for Xin Peng). This script replaces the
title and the author list with what the registry holds and writes down
which arXiv version was used.

Rules
-----
* A record with ``arxiv_id``: title and authors are taken from the arXiv
  API. The version is the one named in ``arxiv_version`` when the record
  already has that field, else the latest one; the version used is written
  to ``arxiv_version``. ``--latest`` moves every record to the latest
  version.
* A record with a ``doi`` and no ``arxiv_id``: title and authors are taken
  from Crossref (``api.crossref.org/works/<doi>``). A name deposited in
  capitals ("SUNIL KOTA") is written in title case.
* One exception to "arXiv wins": a record that also names the DOI of the
  published article and already carries that article's byline (same names,
  same order as Crossref) keeps it when the arXiv byline is different,
  because authors were added or reordered for publication. Such a record
  gets no ``arxiv_version``, and the report says how the two bylines
  differ.
* A record with neither is reported and left alone.
* ``year`` convention (one rule for every record): **the year the work
  first became public**. For a record with an ``arxiv_id`` that is the
  year of arXiv v1 (the API's ``published`` date); for a DOI-only record
  it is the year of Crossref's ``issued`` date (the earlier of online and
  print publication). A later venue year belongs in ``venue`` (for example
  "USENIX Security 2025"), not in ``year``.
* Nothing else is rewritten. ``abstract``, ``tldr``, ``venue``, ``doi``,
  ``url`` and ``notes`` stay as they are; when the stored abstract is not
  the abstract of the version used, the report says so.

The file is edited as text (only the ``authors:`` block and the ``title``,
``year`` and ``arxiv_version`` lines), so key order, wrapping and every
other line stay byte-identical. After each edit the file is parsed again
and compared with the plan; a mismatch aborts before anything is saved.

Network: arXiv is asked in batches, one request per three seconds;
Crossref once per DOI, one request per second. Requests carry a generic
User-Agent and nothing about the person or machine. Answers are kept in
``.cache/validator/paper_metadata.json`` (not tracked); ``--offline`` uses
only that file and ``--refetch`` ignores it.

Usage::

    .venv/bin/python validator/refresh_paper_metadata.py            # dry run; exit 1 when a record differs
    .venv/bin/python validator/refresh_paper_metadata.py --write    # rewrite the files
    .venv/bin/python validator/refresh_paper_metadata.py --latest --write
    .venv/bin/python validator/refresh_paper_metadata.py --only cemri-2025-mast
    .venv/bin/python validator/refresh_paper_metadata.py --report /tmp/papers.json

Run ``.venv/bin/python validator/cli.py --arxiv`` afterwards: the gate
compares every record that names an ``arxiv_version`` with that version's
byline, name by name.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
PAPERS_DIR = REPO / "data" / "papers"
CACHE_PATH = REPO / ".cache" / "validator" / "paper_metadata.json"

USER_AGENT = "kg-metadata-refresh/1.0 (paper title and author check)"
ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_BATCH = 25
ARXIV_PAUSE_S = 3.0
ARXIV_RETRY_WAITS_S = (15.0, 45.0, 90.0)  # after HTTP 429 / 503
CROSSREF_API = "https://api.crossref.org/works/"
CROSSREF_PAUSE_S = 1.0
ALLOWED_HOSTS = frozenset({"export.arxiv.org", "api.crossref.org"})
TIMEOUT_S = 60

_ATOM = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
_ARXIV_ID_RE = re.compile(r"^([0-9]{4}\.[0-9]{4,5}|[a-z-]+(?:\.[A-Z]{2})?/[0-9]{7})$")
_VERSION_RE = re.compile(r"^v[1-9][0-9]*$")
# A plain YAML scalar is safe for a name made of letters, marks, digits,
# spaces and the few punctuation marks that occur in names.
_PLAIN_NAME_RE = re.compile(r"^[^\W\d_][\w .’'()\-]*$")
_YAML_WORDS = {"null", "true", "false", "yes", "no", "on", "off", "y", "n", "~"}


# ---------------------------------------------------------------------------
# Registry answers
# ---------------------------------------------------------------------------


@dataclass
class Registry:
    """What a registry says about one paper."""

    source: str  # "arxiv" | "crossref"
    title: str
    authors: list[str]
    first_public: str  # ISO date (may be a bare year for Crossref)
    arxiv_id: str | None = None  # arXiv only, without the version
    version: str | None = None  # arXiv only
    updated: str | None = None  # arXiv only: date of this version
    abstract: str | None = None
    doi: str | None = None  # arXiv: DOI of the published version, if declared
    journal_ref: str | None = None
    comment: str | None = None
    container: str | None = None  # Crossref: journal or proceedings title
    fetched: str = ""

    @property
    def year(self) -> int | None:
        match = re.match(r"^([0-9]{4})", self.first_public or "")
        return int(match.group(1)) if match else None


def _squash(text: str | None) -> str:
    return " ".join((text or "").split())


def _http_get(url: str, accept: str) -> bytes:
    """GET from one of the two registries. ``urllib`` would also open
    ``file://`` and other schemes, so anything but https to a known host
    is refused before the request is made."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"refusing to fetch {url!r}: not a registry URL")
    request = urllib.request.Request(  # noqa: S310 - https and host checked above
        url, headers={"User-Agent": USER_AGENT, "Accept": accept}
    )
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        return response.read()


def parse_arxiv_feed(xml_text: str, fetched: str) -> list[Registry]:
    """Turn an arXiv API Atom feed into records; entries without an id are
    API error entries and are skipped."""
    records: list[Registry] = []
    root = ET.fromstring(xml_text)  # noqa: S314 - arXiv API answer, no entities used
    for entry in root.findall("a:entry", _ATOM):
        raw_id = _squash(entry.findtext("a:id", default="", namespaces=_ATOM))
        match = re.search(r"arxiv\.org/abs/(.+?)(v[0-9]+)?$", raw_id)
        if not match:
            continue
        authors = [
            _squash(a.findtext("a:name", default="", namespaces=_ATOM))
            for a in entry.findall("a:author", _ATOM)
        ]
        record = Registry(
            source="arxiv",
            arxiv_id=match.group(1),
            title=_squash(entry.findtext("a:title", default="", namespaces=_ATOM)),
            authors=[a for a in authors if a],
            first_public=_squash(
                entry.findtext("a:published", default="", namespaces=_ATOM)
            )[:10],
            version=match.group(2) or "v1",
            updated=_squash(entry.findtext("a:updated", default="", namespaces=_ATOM))[
                :10
            ],
            abstract=_squash(entry.findtext("a:summary", default="", namespaces=_ATOM)),
            doi=_squash(entry.findtext("x:doi", default="", namespaces=_ATOM)) or None,
            journal_ref=_squash(
                entry.findtext("x:journal_ref", default="", namespaces=_ATOM)
            )
            or None,
            comment=_squash(entry.findtext("x:comment", default="", namespaces=_ATOM))
            or None,
            fetched=fetched,
        )
        records.append(record)
    return records


def fetch_arxiv(ids: list[str], fetched: str) -> list[Registry]:
    """One API request for up to ``ARXIV_BATCH`` ids; an id may end in a
    version (``2503.13657v2``), a bare id returns the latest version.
    When arXiv answers "too many requests" the call waits and asks again,
    three times at most."""
    query = urllib.parse.urlencode(
        {"id_list": ",".join(ids), "max_results": str(len(ids))}
    )
    for wait in (*ARXIV_RETRY_WAITS_S, None):
        try:
            body = _http_get(f"{ARXIV_API}?{query}", "application/atom+xml")
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or wait is None:
                raise
            print(f"arXiv answered {exc.code}; waiting {wait:.0f} s", file=sys.stderr)
            time.sleep(wait)
            continue
        return parse_arxiv_feed(body.decode("utf-8", "replace"), fetched)
    return []


def _crossref_date(message: dict[str, Any]) -> str:
    for key in ("issued", "published-online", "published-print", "created"):
        parts = ((message.get(key) or {}).get("date-parts") or [[]])[0]
        if parts and parts[0]:
            return "-".join(
                f"{int(p):02d}" if i else str(p) for i, p in enumerate(parts)
            )
    return ""


def _fix_capitals(name: str) -> str:
    """Title-case a name that was deposited in capitals only."""
    letters = [c for c in name if c.isalpha()]
    if len(letters) > 3 and all(c.isupper() for c in letters):
        return name.title()
    return name


def fetch_crossref(doi: str, fetched: str) -> Registry | None:
    url = CROSSREF_API + urllib.parse.quote(doi, safe="/")
    try:
        body = _http_get(url, "application/json")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    message = json.loads(body.decode("utf-8")).get("message") or {}
    authors = []
    for person in message.get("author") or []:
        name = _squash(
            " ".join(p for p in (person.get("given"), person.get("family")) if p)
        ) or _squash(person.get("name"))
        if name:
            authors.append(name)
    title = _squash((message.get("title") or [""])[0])
    title = re.sub(r"<[^>]+>", "", title)  # Crossref titles may carry <i>, <sub>
    return Registry(
        source="crossref",
        title=title,
        authors=authors,
        first_public=_crossref_date(message),
        doi=_squash(message.get("DOI")) or doi,
        container=_squash((message.get("container-title") or [""])[0]) or None,
        fetched=fetched,
    )


class Cache:
    """Registry answers on disk, so a second run needs no network."""

    def __init__(self, path: Path, *, offline: bool, refetch: bool) -> None:
        self.path = path
        self.offline = offline
        self.refetch = refetch
        self.doc: dict[str, Any] = {}
        if path.exists() and not refetch:
            try:
                self.doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.doc = {}
        self.errors: list[str] = []
        self._last_arxiv = 0.0
        self._last_crossref = 0.0

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.doc, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _pack(record: Registry) -> dict[str, Any]:
        return dict(record.__dict__)

    @staticmethod
    def _unpack(raw: dict[str, Any]) -> Registry:
        return Registry(**raw)

    def arxiv(self, wanted: list[tuple[str, str | None]]) -> dict[str, Registry]:
        """Return ``{"<id><version or ''>": record}`` for every wanted pair."""
        out: dict[str, Registry] = {}
        missing: list[str] = []
        for base, version in wanted:
            key = f"arxiv:{base}{version or ''}"
            if key in self.doc:
                out[f"{base}{version or ''}"] = self._unpack(self.doc[key])
            else:
                missing.append(f"{base}{version or ''}")
        missing = sorted(set(missing))
        if missing and self.offline:
            self.errors.append(
                f"offline: no cached arXiv answer for {', '.join(missing)}"
            )
            return out
        today = dt.date.today().isoformat()
        # Bare ids (latest version) and versioned ids go in separate
        # requests, so an answer can never be filed under the wrong key.
        bare = [m for m in missing if not re.search(r"v[0-9]+$", m)]
        versioned = [m for m in missing if re.search(r"v[0-9]+$", m)]
        batches = [
            group[start : start + ARXIV_BATCH]
            for group in (bare, versioned)
            for start in range(0, len(group), ARXIV_BATCH)
        ]
        for batch in batches:
            wait = ARXIV_PAUSE_S - (time.monotonic() - self._last_arxiv)
            if wait > 0:
                time.sleep(wait)
            try:
                fetched = fetch_arxiv(batch, today)
            except (OSError, ET.ParseError, ValueError) as exc:
                self.errors.append(f"arXiv API request failed ({exc}): {batch}")
                continue
            finally:
                self._last_arxiv = time.monotonic()
            by_id: dict[str, Registry] = {}
            for record in fetched:
                by_id[f"{record.arxiv_id}{record.version}"] = record
                by_id[str(record.arxiv_id)] = record
            for asked in batch:
                record = by_id.get(asked)
                if record is None:
                    self.errors.append(f"arXiv returned no record for {asked}")
                    continue
                self.doc[f"arxiv:{asked}"] = self._pack(record)
                # A bare id answers with the latest version; keep it under
                # its versioned key too.
                self.doc[f"arxiv:{record.arxiv_id}{record.version}"] = self._pack(
                    record
                )
                out[asked] = record
            self.save()
        return out

    def crossref(self, doi: str) -> Registry | None:
        """The Crossref record of a DOI (None when Crossref has none). The
        cache keeps the answer as deposited; capitals are fixed on the way
        out."""
        key = f"crossref:{doi.lower()}"
        if key not in self.doc:
            if self.offline:
                self.errors.append(f"offline: no cached Crossref answer for {doi}")
                return None
            wait = CROSSREF_PAUSE_S - (time.monotonic() - self._last_crossref)
            if wait > 0:
                time.sleep(wait)
            try:
                fetched = fetch_crossref(doi, dt.date.today().isoformat())
            except (OSError, ValueError) as exc:
                self.errors.append(f"Crossref request failed for {doi}: {exc}")
                return None
            finally:
                self._last_crossref = time.monotonic()
            self.doc[key] = self._pack(fetched) if fetched else None
            self.save()
        raw = self.doc[key]
        if not raw:
            return None
        record = self._unpack(raw)
        record.authors = [_fix_capitals(a) for a in record.authors]
        return record


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def norm_text(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii(text or "").casefold())


def norm_name(name: str) -> str:
    """A byline name without accents, case, periods or extra spaces."""
    return " ".join(re.sub(r"[^a-z' -]+", " ", _ascii(name).casefold()).split())


def same_byline(ours: list[str], theirs: list[str]) -> bool:
    return [norm_name(a) for a in ours] == [norm_name(a) for a in theirs]


@dataclass
class Plan:
    """What the registry says about one file and what would change."""

    path: Path
    node: dict[str, Any]
    registry: Registry | None = None
    latest_version: str | None = None
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def paper_id(self) -> str:
        return str(self.node.get("id") or self.path.stem)


def author_diff(old: list[str], new: list[str]) -> list[str]:
    """Readable list of what differs between two bylines."""
    out: list[str] = []
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before, after = old[i1:i2], new[j1:j2]
        if tag == "replace" and len(before) == len(after):
            out.extend(f"{b} → {a}" for b, a in zip(before, after))
        else:
            out.extend(f"− {b}" for b in before)
            out.extend(f"+ {a}" for a in after)
    return out


def build_plans(
    paths: list[Path], cache: Cache, *, latest: bool
) -> tuple[list[Plan], list[str]]:
    plans: list[Plan] = []
    problems: list[str] = []
    for path in paths:
        node = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(node, dict):
            problems.append(f"{path.name}: top level is not a mapping")
            continue
        plans.append(Plan(path=path, node=node))

    wanted: list[tuple[str, str | None]] = []
    for plan in plans:
        arxiv_id = plan.node.get("arxiv_id")
        if not arxiv_id:
            continue
        if not _ARXIV_ID_RE.match(str(arxiv_id)):
            problems.append(f"{plan.path.name}: arxiv_id {arxiv_id!r} is not an id")
            continue
        wanted.append((str(arxiv_id), None))
        pinned = plan.node.get("arxiv_version")
        if pinned and not latest:
            if not _VERSION_RE.match(str(pinned)):
                problems.append(
                    f"{plan.path.name}: arxiv_version {pinned!r} is not 'vN'"
                )
                continue
            wanted.append((str(arxiv_id), str(pinned)))
    answers = cache.arxiv(wanted)

    for plan in plans:
        node = plan.node
        arxiv_id, doi = node.get("arxiv_id"), node.get("doi")
        if arxiv_id:
            newest = answers.get(str(arxiv_id))
            pinned = None if latest else node.get("arxiv_version")
            record = answers.get(f"{arxiv_id}{pinned}") if pinned else newest
            if record is None:
                plan.notes.append("no arXiv answer; left as it is")
                continue
            plan.registry = record
            plan.latest_version = newest.version if newest else None
            if newest and newest.version != record.version:
                plan.notes.append(
                    f"pinned to {record.version}; arXiv has {newest.version}"
                    f" ({newest.updated}): {newest.title!r}, first author"
                    f" {newest.authors[0] if newest.authors else '?'}"
                )
        elif doi:
            record = cache.crossref(str(doi))
            if record is None:
                plan.notes.append("no Crossref answer; left as it is")
                continue
            if not record.authors or not record.title:
                plan.notes.append("Crossref record has no title or no authors; left")
                continue
            plan.registry = record
        else:
            plan.notes.append("no arxiv_id and no doi; cannot be checked")
            continue

        record = plan.registry
        stored_authors = [str(a) for a in node.get("authors") or []]
        published_byline = False
        if (
            record.source == "arxiv"
            and stored_authors != record.authors
            and doi
            and not str(doi).lower().startswith("10.48550/")
        ):
            # The record names a published article. Is its byline already
            # that article's byline?
            published = cache.crossref(str(doi))
            if (
                published is not None
                and published.authors
                and same_byline(stored_authors, published.authors)
                and not same_byline(stored_authors, record.authors)
            ):
                published_byline = True
                plan.notes.append(
                    f"byline kept: it is the byline of the published article"
                    f" (Crossref {doi}, {len(published.authors)} authors);"
                    f" arXiv {record.version} lists {len(record.authors)}:"
                    f" {', '.join(record.authors)}"
                )
                if node.get("arxiv_version"):
                    plan.notes.append(
                        "arxiv_version is set although the byline is not the"
                        " arXiv one; remove arxiv_version by hand"
                    )
        if node.get("title") != record.title:
            plan.changes["title"] = (node.get("title"), record.title)
        if stored_authors != record.authors and not published_byline:
            plan.changes["authors"] = (stored_authors, record.authors)
        if record.year and node.get("year") != record.year:
            plan.changes["year"] = (node.get("year"), record.year)
        if (
            record.source == "arxiv"
            and not published_byline
            and node.get("arxiv_version") != record.version
        ):
            plan.changes["arxiv_version"] = (node.get("arxiv_version"), record.version)
        if (
            record.abstract
            and node.get("abstract")
            and norm_text(node.get("abstract")) != norm_text(record.abstract)
        ):
            ratio = difflib.SequenceMatcher(
                None, norm_text(node.get("abstract")), norm_text(record.abstract)
            ).ratio()
            plan.notes.append(
                f"stored abstract is not the {record.version} abstract"
                f" (similarity {ratio:.2f})"
            )
    return plans, problems


# ---------------------------------------------------------------------------
# Rewriting (text level)
# ---------------------------------------------------------------------------


def yaml_string(text: str) -> str:
    """A double-quoted YAML scalar (JSON string syntax is valid YAML)."""
    return json.dumps(text, ensure_ascii=False)


def yaml_name(name: str) -> str:
    if _PLAIN_NAME_RE.match(name) and name.casefold() not in _YAML_WORDS:
        return name
    return yaml_string(name)


def rewrite(text: str, plan: Plan) -> str:
    """Apply ``plan.changes`` to the file text; only the touched lines move."""
    lines = text.split("\n")

    def find(key: str) -> int | None:
        for index, line in enumerate(lines):
            if line.startswith(f"{key}:"):
                return index
        return None

    if "authors" in plan.changes:
        start = find("authors")
        if start is None or lines[start].strip() != "authors:":
            raise ValueError("authors is not a block list")
        end = start + 1
        while end < len(lines) and re.match(r"^\s+- ", lines[end]):
            end += 1
        new_items = [f"  - {yaml_name(a)}" for a in plan.changes["authors"][1]]
        lines[start + 1 : end] = new_items

    for key in ("title", "year"):
        if key in plan.changes:
            index = find(key)
            if index is None:
                raise ValueError(f"{key} line not found")
            value = plan.changes[key][1]
            rendered = yaml_string(value) if isinstance(value, str) else str(value)
            lines[index] = f"{key}: {rendered}"

    if "arxiv_version" in plan.changes:
        rendered = f"arxiv_version: {yaml_string(plan.changes['arxiv_version'][1])}"
        index = find("arxiv_version")
        if index is not None:
            lines[index] = rendered
        else:
            anchor = find("arxiv_id")
            if anchor is None:
                raise ValueError("arxiv_id line not found")
            lines.insert(anchor + 1, rendered)
    return "\n".join(lines)


def apply(plan: Plan) -> None:
    """Rewrite one file and check that nothing but the plan changed."""
    old_text = plan.path.read_text(encoding="utf-8")
    new_text = rewrite(old_text, plan)
    before = yaml.safe_load(old_text)
    after = yaml.safe_load(new_text)
    expected = dict(before)
    for key, (_, new_value) in plan.changes.items():
        expected[key] = new_value
    if after != expected:
        changed = sorted(
            k for k in set(after) | set(expected) if after.get(k) != expected.get(k)
        )
        raise ValueError(f"rewrite would also change {changed}")
    plan.path.write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def describe(plan: Plan) -> list[str]:
    out: list[str] = []
    record = plan.registry
    if record is not None:
        label = (
            f"arXiv {plan.node.get('arxiv_id')}{record.version}"
            if record.source == "arxiv"
            else f"Crossref {record.doi}"
        )
        out.append(f"source: {label}")
    for key, (old, new) in plan.changes.items():
        if key == "authors":
            out.append(f"authors: {len(old)} → {len(new)} names")
            out.extend(f"    {line}" for line in author_diff(old, new))
        else:
            out.append(f"{key}: {old!r} → {new!r}")
    out.extend(f"note: {note}" for note in plan.notes)
    return out


def report_doc(plans: list[Plan]) -> dict[str, Any]:
    rows = []
    for plan in plans:
        record = plan.registry
        rows.append(
            {
                "id": plan.paper_id,
                "source": record.source if record else None,
                "arxiv_id": plan.node.get("arxiv_id"),
                "version_used": record.version if record else None,
                "latest_version": plan.latest_version,
                "first_public": record.first_public if record else None,
                "registry_doi": record.doi if record else None,
                "journal_ref": record.journal_ref if record else None,
                "comment": record.comment if record else None,
                "container": record.container if record else None,
                "before": {
                    "title": plan.node.get("title"),
                    "authors": list(plan.node.get("authors") or []),
                    "year": plan.node.get("year"),
                    "arxiv_version": plan.node.get("arxiv_version"),
                },
                "after": {
                    "title": record.title if record else plan.node.get("title"),
                    "authors": (
                        record.authors
                        if record
                        else list(plan.node.get("authors") or [])
                    ),
                    "year": (
                        record.year if record and record.year else plan.node.get("year")
                    ),
                    "arxiv_version": (
                        record.version
                        if record and record.source == "arxiv"
                        else plan.node.get("arxiv_version")
                    ),
                },
                "changed": sorted(plan.changes),
                "notes": plan.notes,
            }
        )
    return {
        "generated": dt.date.today().isoformat(),
        "year_convention": "year the work first became public (arXiv v1, else Crossref issued)",
        "papers": rows,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare paper titles, author lists and years with arXiv / Crossref."
            " Dry run unless --write is given."
        )
    )
    parser.add_argument("--write", action="store_true", help="rewrite the files")
    parser.add_argument(
        "--latest",
        action="store_true",
        help="use the latest arXiv version even when a record names arxiv_version",
    )
    parser.add_argument(
        "--only", nargs="+", metavar="ID", help="check these paper ids only"
    )
    parser.add_argument(
        "--papers-dir", type=Path, default=PAPERS_DIR, help="default: data/papers"
    )
    parser.add_argument(
        "--cache", type=Path, default=CACHE_PATH, help="where registry answers are kept"
    )
    parser.add_argument(
        "--offline", action="store_true", help="use cached answers only"
    )
    parser.add_argument(
        "--refetch", action="store_true", help="ignore the cache and ask again"
    )
    parser.add_argument(
        "--report", type=Path, help="write the before / after list here as JSON"
    )
    args = parser.parse_args(argv)

    paths = sorted(args.papers_dir.glob("*.yml"))
    if args.only:
        wanted = set(args.only)
        paths = [p for p in paths if p.stem in wanted]
        unknown = wanted - {p.stem for p in paths}
        if unknown:
            print(f"unknown paper id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
    if not paths:
        print("no paper files", file=sys.stderr)
        return 2

    cache = Cache(args.cache, offline=args.offline, refetch=args.refetch)
    plans, problems = build_plans(paths, cache, latest=args.latest)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report_doc(plans), indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    differing = [p for p in plans if p.changes]
    unchecked = [p for p in plans if p.registry is None]
    for plan in plans:
        lines = describe(plan)
        if plan.changes or plan.notes:
            print(f"{plan.paper_id}")
            for line in lines:
                print(f"  {line}")
    for problem in problems + cache.errors:
        print(f"PROBLEM {problem}", file=sys.stderr)

    written = 0
    if args.write:
        for plan in differing:
            try:
                apply(plan)
            except (OSError, ValueError) as exc:
                print(f"PROBLEM {plan.path.name}: not written — {exc}", file=sys.stderr)
                problems.append(str(exc))
                continue
            written += 1

    print(
        f"\n{len(plans)} records: {len(plans) - len(differing) - len(unchecked)} match"
        f" the registry, {len(differing)} differ"
        + (f" ({written} rewritten)" if args.write else "")
        + f", {len(unchecked)} could not be checked"
    )
    if problems or cache.errors:
        return 2
    if differing and not args.write:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
