"""Opt-in validator checks that need the network, or a cache of it.

``validator/cli.py`` imports this module only when ``--arxiv`` or ``--links``
is given. The default gate stays offline and reads no cache.

``--arxiv``
    * every paper with an ``arxiv_id``: title and first-author surname must
      match the arXiv record (the version in ``arxiv_version`` when set,
      else the latest one). A record that names its ``arxiv_version`` says
      it reproduces that version's byline, so then the whole author list
      is compared, name by name;
    * every arXiv link in an incident's ``source_urls``: the paper it points
      to must share words with the incident, which catches a mistyped id
      that resolves to an unrelated paper.

    Records are kept in ``validator/cache/arxiv_records.json`` (tracked, so
    ``--arxiv --offline`` gives the same answer on every machine). Missing
    records are fetched from the arXiv API in batches, one request per three
    seconds.

``--links``
    Every source URL (incident sources, paper, taxonomy and tool URLs) is
    requested once. 404 / 410 is an error; a redirect from a deep link to a
    home page and anything that could not be verified (403, 429, time-out)
    is a warning. Answers are kept for seven days in ``.cache/validator/``
    (not tracked).

Only the standard library is used. Requests carry a generic User-Agent and
nothing about the person or machine running the check.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
ARXIV_CACHE = Path(__file__).resolve().parent / "cache" / "arxiv_records.json"
LINK_CACHE = REPO / ".cache" / "validator" / "links.json"

USER_AGENT = "kg-validator/1.0 (metadata and link check)"
ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_BATCH = 40
ARXIV_PAUSE_S = 3.0
LINK_TIMEOUT_S = 20
LINK_OK_TTL_DAYS = 7
TITLE_MATCH_RATIO = 0.92

Nodes = dict[str, list[tuple[Path, dict[str, Any]]]]

_ARXIV_ID_RE = re.compile(
    r"^(?:arxiv:)?([0-9]{4}\.[0-9]{4,5}|[a-z-]+(?:\.[A-Z]{2})?/[0-9]{7})(v[0-9]+)?$",
    re.I,
)
_ARXIV_URL_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5})(v[0-9]+)?", re.I
)
_ATOM = {"a": "http://www.w3.org/2005/Atom"}

_STOPWORDS = frozenset(
    """
    about above after again against also among and are based because been
    before being between both but can could did does doing down during each
    for from further had has have having here how into its itself just more
    most not now off once only other our out over own same should some such
    than that the their them then there these they this those through toward
    towards under until upon using via very was were what when where which
    while who whom why will with within without would you your study paper
    approach analysis case
    """.split()
)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def norm_title(text: str) -> str:
    """Lower-case letters and digits only; LaTeX markup and accents dropped."""
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    return re.sub(r"[^a-z0-9]+", "", _ascii(text).casefold())


def titles_match(ours: str, theirs: str) -> bool:
    a, b = norm_title(ours), norm_title(theirs)
    if not a or not b:
        return False
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= TITLE_MATCH_RATIO


def surname(name: str) -> str:
    """Family name of a byline entry: the part before a comma, else the
    last word. Accents and case are ignored."""
    name = name.strip()
    if "," in name:
        name = name.split(",", 1)[0]
    parts = re.findall(r"[A-Za-z][A-Za-z'’-]*", _ascii(name))
    return parts[-1].casefold() if parts else ""


def norm_name(name: str) -> str:
    """A byline name without accents, case, periods or extra spaces."""
    return " ".join(re.sub(r"[^a-z' -]+", " ", _ascii(name).casefold()).split())


def content_words(text: str) -> set[str]:
    words = set()
    for raw in re.findall(r"[a-z][a-z0-9]+", _ascii(text).casefold()):
        word = raw[:-1] if raw.endswith("s") and len(raw) > 4 else raw
        if len(word) >= 4 and word not in _STOPWORDS and raw not in _STOPWORDS:
            words.add(word)
    return words


def shares_words(title: str, node_text: str) -> bool:
    """True when the arXiv title and the node are plausibly about the same
    thing: two shared content words, or half of a very short title."""
    wanted = content_words(title)
    if not wanted:
        return True
    shared = wanted & content_words(node_text)
    return len(shared) >= 2 or len(shared) * 2 >= len(wanted)


# ---------------------------------------------------------------------------
# arXiv records
# ---------------------------------------------------------------------------


def split_arxiv_id(value: Any) -> tuple[str, str | None] | None:
    """``'2503.13657v2'`` → ``('2503.13657', 'v2')``; None when not an id."""
    if not isinstance(value, str):
        return None
    match = _ARXIV_ID_RE.match(value.strip())
    if not match:
        return None
    return match.group(1), (match.group(2) or None)


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return doc if isinstance(doc, dict) else default


def save_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_arxiv_feed(xml_text: str) -> list[dict[str, Any]]:
    """Parse an arXiv API Atom feed into ``{id, version, title, authors,
    published}`` records. Entries without an id (API errors) are skipped."""
    records: list[dict[str, Any]] = []
    root = ET.fromstring(xml_text)  # noqa: S314 - arXiv API answer, no entities used
    for entry in root.findall("a:entry", _ATOM):
        raw_id = (entry.findtext("a:id", default="", namespaces=_ATOM) or "").strip()
        match = re.search(r"arxiv\.org/abs/(.+?)(v[0-9]+)?$", raw_id)
        if not match:
            continue
        title = " ".join(
            (entry.findtext("a:title", default="", namespaces=_ATOM) or "").split()
        )
        authors = [
            " ".join((a.findtext("a:name", default="", namespaces=_ATOM) or "").split())
            for a in entry.findall("a:author", _ATOM)
        ]
        records.append(
            {
                "id": match.group(1),
                "version": match.group(2) or "v1",
                "title": title,
                "authors": [a for a in authors if a],
                "published": (
                    entry.findtext("a:published", default="", namespaces=_ATOM) or ""
                )[:10],
            }
        )
    return records


def _open(request: urllib.request.Request, timeout: float) -> Any:
    """``urlopen`` for http(s) only. ``urllib`` would also follow ``file://``;
    every URL requested here comes from the KG files or is the arXiv API,
    and this check makes sure none of them can name a local file."""
    if urllib.parse.urlsplit(request.full_url).scheme not in ("http", "https"):
        raise ValueError(f"not an http(s) URL: {request.full_url!r}")
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310


def fetch_arxiv(id_list: list[str]) -> list[dict[str, Any]]:
    """One API request for up to ``ARXIV_BATCH`` ids (with or without a
    version suffix)."""
    query = urllib.parse.urlencode(
        {"id_list": ",".join(id_list), "max_results": str(len(id_list))}
    )
    request = urllib.request.Request(  # noqa: S310 - fixed https host
        f"{ARXIV_API}?{query}", headers={"User-Agent": USER_AGENT}
    )
    with _open(request, timeout=60) as response:
        return parse_arxiv_feed(response.read().decode("utf-8", "replace"))


class ArxivRecords:
    """The tracked cache of arXiv records, filled from the API on demand."""

    def __init__(self, path: Path = ARXIV_CACHE, *, offline: bool = False) -> None:
        self.path = path
        self.offline = offline
        doc = load_json(path, {})
        self.records: dict[str, dict[str, Any]] = dict(doc.get("records") or {})
        self.latest: dict[str, dict[str, str]] = dict(doc.get("latest") or {})
        self.fetch_errors: list[str] = []
        self._dirty = False

    def _key(self, base: str, version: str | None) -> str | None:
        if version:
            return f"{base}{version}"
        latest = self.latest.get(base)
        return f"{base}{latest['version']}" if latest else None

    def get(self, base: str, version: str | None) -> dict[str, Any] | None:
        key = self._key(base, version)
        return self.records.get(key) if key else None

    def ensure(self, wanted: list[tuple[str, str | None]]) -> None:
        """Fetch what the cache lacks (nothing when offline)."""
        missing = sorted(
            {
                f"{base}{version or ''}"
                for base, version in wanted
                if self.get(base, version) is None
            }
        )
        if not missing or self.offline:
            return
        today = dt.date.today().isoformat()
        for start in range(0, len(missing), ARXIV_BATCH):
            batch = missing[start : start + ARXIV_BATCH]
            if start:
                time.sleep(ARXIV_PAUSE_S)
            try:
                fetched = fetch_arxiv(batch)
            except (OSError, ET.ParseError, ValueError) as exc:
                self.fetch_errors.append(f"arXiv API request failed: {exc}")
                continue
            asked_latest = {b for b in batch if not re.search(r"v[0-9]+$", b)}
            for record in fetched:
                key = f"{record['id']}{record['version']}"
                self.records[key] = {
                    "title": record["title"],
                    "authors": record["authors"],
                    "published": record["published"],
                    "fetched": today,
                }
                if record["id"] in asked_latest:
                    self.latest[record["id"]] = {
                        "version": record["version"],
                        "checked": today,
                    }
                self._dirty = True

    def save(self) -> None:
        if self._dirty:
            save_json(
                self.path,
                {
                    "about": (
                        "arXiv API records used by `validator/cli.py --arxiv`."
                        " Written by that command; do not edit by hand."
                    ),
                    "latest": self.latest,
                    "records": self.records,
                },
            )
            self._dirty = False


def check_arxiv(
    nodes: Nodes, records: ArxivRecords
) -> tuple[list[str], list[str], list[str]]:
    """Return ``(errors, warnings, notes)`` for the arXiv checks."""
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    papers = []
    for path, node in nodes.get("papers", []):
        parsed = split_arxiv_id(node.get("arxiv_id"))
        if node.get("arxiv_id") and parsed is None:
            errors.append(
                f"[papers] {path.name} :: arxiv_id — {node.get('arxiv_id')!r} is not"
                " an arXiv identifier"
            )
            continue
        if parsed:
            version = node.get("arxiv_version") or parsed[1]
            papers.append((path, node, parsed[0], version))

    incident_links = []
    for path, node in nodes.get("incidents", []):
        for url in node.get("source_urls") or []:
            match = _ARXIV_URL_RE.search(str(url))
            if match:
                incident_links.append(
                    (path, node, str(url), match.group(1), match.group(2))
                )

    records.ensure(
        [(base, version) for _, _, base, version in papers]
        + [(base, version) for _, _, _, base, version in incident_links]
    )
    records.save()
    warnings.extend(f"[arxiv] {e}" for e in records.fetch_errors)

    unchecked = 0
    for path, node, base, version in papers:
        record = records.get(base, version)
        if record is None:
            unchecked += 1
            continue
        label = f"arXiv {base}{version or ''}"
        if not titles_match(str(node.get("title") or ""), record["title"]):
            errors.append(
                f"[papers] {path.name} :: title — {node.get('title')!r} is not the"
                f" title of {label}: {record['title']!r}"
            )
        authors = [str(a) for a in node.get("authors") or []]
        ours = surname(authors[0]) if authors else ""
        theirs = surname(record["authors"][0]) if record["authors"] else ""
        if theirs and ours != theirs:
            errors.append(
                f"[papers] {path.name} :: authors/0 — first author"
                f" {authors[0] if authors else None!r} is not the first author of"
                f" {label}: {record['authors'][0]!r}"
            )
        elif node.get("arxiv_version") and record["authors"]:
            # The record says which version's byline it reproduces.
            if len(authors) != len(record["authors"]):
                errors.append(
                    f"[papers] {path.name} :: authors — {len(authors)} names, but"
                    f" {label} has {len(record['authors'])}:"
                    f" {', '.join(record['authors'])}"
                )
            else:
                for index, (mine, real) in enumerate(zip(authors, record["authors"])):
                    if norm_name(mine) != norm_name(real):
                        errors.append(
                            f"[papers] {path.name} :: authors/{index} — {mine!r} is"
                            f" not on the byline of {label}; it has {real!r}"
                        )
                        break
    if unchecked:
        notes.append(
            f"{unchecked} paper(s) with an arxiv_id have no cached arXiv record and"
            " were not checked; run `validator/cli.py --arxiv` with network access"
        )

    unchecked_links = 0
    for path, node, url, base, version in incident_links:
        record = records.get(base, version)
        if record is None:
            unchecked_links += 1
            continue
        text = " ".join(
            str(node.get(k) or "") for k in ("title", "tagline", "description", "notes")
        )
        if not shares_words(record["title"], text):
            errors.append(
                f"[incidents] {path.name} :: source_urls — {url} is the paper"
                f" {record['title']!r}, which shares no words with this record;"
                " wrong arXiv id?"
            )
    if unchecked_links:
        notes.append(
            f"{unchecked_links} arXiv link(s) in incident sources have no cached"
            " record and were not checked"
        )
    return errors, warnings, notes


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


def collect_urls(nodes: Nodes) -> dict[str, list[str]]:
    """Map each URL to the places that cite it (``kind/file :: field``)."""
    cited: dict[str, list[str]] = defaultdict(list)

    def add(kind: str, path: Path, field: str, value: Any) -> None:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            cited[value].append(f"[{kind}] {path.name} :: {field}")

    for kind, entries in nodes.items():
        for path, node in entries:
            for field in ("repository_url", "documentation_url", "url"):
                add(kind, path, field, node.get(field))
            for index, url in enumerate(node.get("source_urls") or []):
                add(kind, path, f"source_urls/{index}", url)
    return dict(cited)


def probe(url: str) -> dict[str, Any]:
    """Request one URL. Returns ``{status, final}``; status 0 means the
    request could not be completed (DNS, TLS, time-out)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(
            url, headers=headers, method=method
        )  # noqa: S310
        try:
            with _open(request, timeout=LINK_TIMEOUT_S) as response:
                if method == "GET":
                    response.read(1)
                return {"status": response.status, "final": response.geturl()}
        except urllib.error.HTTPError as exc:
            if method == "HEAD" and exc.code in (400, 403, 405, 406, 501):
                continue  # some servers refuse HEAD only
            return {"status": exc.code, "final": url}
        except (urllib.error.URLError, OSError, ValueError) as exc:
            if method == "HEAD":
                continue
            return {"status": 0, "final": url, "error": str(exc)[:120]}
    return {"status": 0, "final": url}


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower().removeprefix("www.")


def _sent_to_home(url: str, final: str) -> bool:
    """A deep link that now lands on the front page of the same site. A
    move to a docs sub-domain (``x.dev/docs`` → ``docs.x.dev/``) is fine."""
    deep = urllib.parse.urlsplit(url).path.strip("/") != ""
    at_root = urllib.parse.urlsplit(final).path.strip("/") == ""
    return deep and at_root and _host(url) == _host(final)


def check_links(
    nodes: Nodes,
    *,
    offline: bool = False,
    cache_path: Path = LINK_CACHE,
    today: dt.date | None = None,
    prober: Any = probe,
) -> tuple[list[str], list[str], list[str]]:
    """Return ``(errors, warnings, notes)`` for the link check."""
    today = today or dt.date.today()
    cache = load_json(cache_path, {})
    cited = collect_urls(nodes)

    def fresh(entry: dict[str, Any]) -> bool:
        try:
            age = (today - dt.date.fromisoformat(str(entry.get("checked")))).days
        except ValueError:
            return False
        ok = 200 <= int(entry.get("status") or 0) < 400
        return 0 <= age <= (LINK_OK_TTL_DAYS if ok else 1)

    todo = sorted(u for u in cited if not fresh(cache.get(u) or {}))
    if todo and not offline:
        by_host: dict[str, list[str]] = defaultdict(list)
        for url in todo:
            by_host[urllib.parse.urlsplit(url).netloc].append(url)

        def run_host(urls: list[str]) -> list[tuple[str, dict[str, Any]]]:
            out = []
            for index, url in enumerate(urls):
                if index:
                    time.sleep(1.0)  # be polite to a host we ask repeatedly
                out.append((url, prober(url)))
            return out

        with ThreadPoolExecutor(max_workers=8) as pool:
            for results in pool.map(run_host, by_host.values()):
                for url, result in results:
                    cache[url] = {**result, "checked": today.isoformat()}
        save_json(cache_path, cache)

    errors: list[str] = []
    warnings: list[str] = []
    unchecked = 0
    for url in sorted(cited):
        entry = cache.get(url)
        if not entry or (offline and not fresh(entry)):
            unchecked += 1
            continue
        status = int(entry.get("status") or 0)
        where = "; ".join(cited[url][:3])
        if status in (404, 410):
            errors.append(f"{where} — {url} answers {status} (dead link)")
        elif 200 <= status < 400:
            final = str(entry.get("final") or url)
            if _sent_to_home(url, final):
                warnings.append(
                    f"{where} — {url} now redirects to a home page ({final})"
                )
        else:
            reason = f"status {status}" if status else "no answer"
            warnings.append(f"{where} — {url} could not be verified ({reason})")
    notes = [f"link check: {len(cited)} distinct URLs, {unchecked} not checked"]
    return errors, warnings, notes


# ---------------------------------------------------------------------------
# Entry point used by validator/cli.py
# ---------------------------------------------------------------------------


def run(
    nodes: Nodes, *, arxiv: bool, links: bool, offline: bool
) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    if arxiv:
        e, w, n = check_arxiv(nodes, ArxivRecords(ARXIV_CACHE, offline=offline))
        errors += e
        warnings += w
        notes += n
    if links:
        e, w, n = check_links(nodes, offline=offline, cache_path=LINK_CACHE)
        errors += e
        warnings += w
        notes += n
    return errors, warnings, notes
