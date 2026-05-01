"""Deduplication across three populations for the SAICA-KG ingestion pipeline.

Populations checked (ordered, first hit wins):
    (a) canonical Tool YAMLs under ``data/tools/``
    (b) ``candidate_tools`` staging rows in Postgres
    (c) in-flight URLs registered within the current batch

The module builds indexes once at ``DupChecker.__init__`` and reuses them
across an ingest batch. Integration with ``validator/ingest_github.py`` and
the bulk-ingest CLI is out of scope — this file exposes a stable public API
that those callers can adopt in a follow-up PR.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlsplit

import yaml

try:  # Avoid a hard dep at import time; tests may stub rapidfuzz out.
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - rapidfuzz is in requirements.txt
    fuzz = None  # type: ignore[assignment]


__all__ = [
    "DupHit",
    "canonical_github_url",
    "canonical_repo_key",
    "DupChecker",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DupHit:
    """A single duplicate match.

    Attributes:
        kind:       'yaml' | 'candidate' | 'batch'
        match_id:   tool id (YAML ``id`` field) or candidate row id as str
        match_url:  the canonical URL of the matched record, if available
        match_name: the name of the matched record, if available
        similarity: 1.0 for exact URL, rapidfuzz_score/100 for fuzzy
        rule:       'canonical_url' | 'fuzzy_name' | 'org_repo_alias'
    """

    kind: str
    match_id: str
    match_url: Optional[str]
    match_name: Optional[str]
    similarity: float
    rule: str


# ---------------------------------------------------------------------------
# URL canonicalization
# ---------------------------------------------------------------------------


# Sub-paths that GitHub hangs off a repo URL. We strip them so
# "…/<owner>/<repo>/tree/main/docs" collapses to "…/<owner>/<repo>".
_STRIP_SUFFIXES = (
    "tree",
    "blob",
    "commits",
    "commit",
    "releases",
    "pulls",
    "pull",
    "issues",
    "wiki",
    "archive",
    "actions",
    "raw",
)

# Owner/repo are GitHub "login" style: alnum + hyphen + underscore + dot.
# Repo names in practice permit more but these cover the corpus of interest.
_SEG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def canonical_github_url(url: str) -> Optional[str]:
    """Normalize a GitHub URL to ``https://github.com/<owner>/<repo>``.

    Returns ``None`` if the input isn't a GitHub repo URL.

    Normalizations applied:
        * lowercased host and path
        * scheme coerced to ``https`` (``http`` accepted, anything else rejected)
        * trailing slashes, ``.git`` suffix stripped
        * query string and fragment dropped
        * sub-paths (``/tree/...``, ``/blob/...``, ``/issues/...``, etc.)
          dropped so only ``<scheme>://<host>/<owner>/<repo>`` remains
    """
    if not url or not isinstance(url, str):
        return None

    raw = url.strip()
    if not raw:
        return None

    # If the user passed a bare "github.com/foo/bar", urlsplit puts the host
    # into the path. Add a scheme so the split is unambiguous.
    if "://" not in raw:
        raw = "https://" + raw

    try:
        parts = urlsplit(raw)
    except ValueError:
        return None

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None

    host = parts.hostname
    if host is None:
        return None
    host = host.lower()
    # Accept github.com and the (rare) www.github.com; reject everything else
    # including enterprise GHE hosts — those need explicit opt-in, which is
    # out of scope for this pass.
    if host == "www.github.com":
        host = "github.com"
    if host != "github.com":
        return None

    path = parts.path.lower().strip("/")
    if not path:
        return None

    # Drop .git suffix on the whole path before splitting; GitHub repo clone
    # URLs frequently end in "<owner>/<repo>.git".
    if path.endswith(".git"):
        path = path[: -len(".git")]

    segments = [seg for seg in path.split("/") if seg]
    if len(segments) < 2:
        return None

    owner, repo = segments[0], segments[1]

    # If segment 3 is one of the known suffixes, we keep only owner/repo.
    # If it's something else (e.g. a monorepo sub-path GitHub doesn't know
    # about), we still collapse to owner/repo — that's the contract.
    if len(segments) > 2 and segments[2] in _STRIP_SUFFIXES:
        pass  # explicit branch for readability

    # Validate shape: owner and repo must look like real repo segments.
    if not _SEG_RE.match(owner) or not _SEG_RE.match(repo):
        return None
    # Reserved top-level GitHub paths that aren't repos.
    if owner in {
        "about",
        "contact",
        "features",
        "login",
        "logout",
        "marketplace",
        "orgs",
        "pricing",
        "settings",
        "signup",
        "sponsors",
        "topics",
        "trending",
        "search",
        "notifications",
    }:
        return None

    return f"https://github.com/{owner}/{repo}"


def canonical_repo_key(url: str) -> Optional[str]:
    """Return ``<owner>/<repo>`` (lowercased) from a GitHub URL, or ``None``."""
    canon = canonical_github_url(url)
    if canon is None:
        return None
    # canonical_github_url guarantees the "https://github.com/" prefix.
    return canon[len("https://github.com/") :]


# ---------------------------------------------------------------------------
# DupChecker
# ---------------------------------------------------------------------------


_COMPACT_RE = re.compile(r"[^a-z0-9]+")


def _compact_name(name: str) -> str:
    """Lowercase and strip non-alnum. 'pydantic-ai' == 'PydanticAI'."""
    return _COMPACT_RE.sub("", name.lower())


@dataclass
class _IndexEntry:
    """One indexed record for dedup lookups."""

    kind: str  # 'yaml' | 'candidate'
    match_id: str
    url: Optional[str]
    repo_key: Optional[str]
    name: Optional[str]
    compact_name: Optional[str] = None


class DupChecker:
    """Build indexes at construction; re-use across a batch.

    Args:
        yaml_dir: directory containing canonical Tool YAMLs.
        include_candidates: if True, also query ``candidate_tools`` in
            Postgres via :func:`pipeline.db.get_conn`. Set to False when
            Postgres is not reachable (e.g. offline unit tests).
        fuzzy_threshold: rapidfuzz ``token_set_ratio`` threshold in [0, 100]
            above which a name match counts. Defaults to 90.
    """

    def __init__(
        self,
        yaml_dir: str = "data/tools",
        include_candidates: bool = True,
        fuzzy_threshold: int = 90,
    ) -> None:
        self.yaml_dir = yaml_dir
        self.include_candidates = include_candidates
        self.fuzzy_threshold = fuzzy_threshold

        self._entries: list[_IndexEntry] = []
        self._by_url: dict[str, _IndexEntry] = {}
        self._by_repo_key: dict[str, _IndexEntry] = {}

        # Batch state.
        self._batch_by_url: dict[str, tuple[str, Optional[str]]] = {}
        self._batch_by_repo_key: dict[str, tuple[str, Optional[str]]] = {}

        self._load_yaml_index()
        if include_candidates:
            self._load_candidate_index()

    # -- index construction -------------------------------------------------

    def _load_yaml_index(self) -> None:
        root = Path(self.yaml_dir)
        if not root.is_dir():
            return
        for path in sorted(root.glob("*.yml")):
            try:
                data = yaml.safe_load(path.read_text()) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(data, dict):
                continue
            tool_id = str(data.get("id") or path.stem)
            name = data.get("name")
            repo_url_raw = data.get("repository_url")
            canon = canonical_github_url(repo_url_raw) if repo_url_raw else None
            repo_key = canonical_repo_key(repo_url_raw) if repo_url_raw else None
            name_str = name if isinstance(name, str) else None
            entry = _IndexEntry(
                kind="yaml",
                match_id=tool_id,
                url=canon,
                repo_key=repo_key,
                name=name_str,
                compact_name=_compact_name(name_str) if name_str else None,
            )
            self._entries.append(entry)
            if canon:
                self._by_url.setdefault(canon, entry)
            if repo_key:
                self._by_repo_key.setdefault(repo_key, entry)

    def _load_candidate_index(self) -> None:
        # Import lazily so tests that don't want Postgres can skip the import
        # failure entirely via include_candidates=False.
        try:
            from pipeline import db
        except ImportError:
            return
        try:
            with db.get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT id, source_url, name FROM candidate_tools")
                rows = list(cur.fetchall())
        except Exception:  # noqa: BLE001 - tolerate DB absence in tests
            return
        for row in rows:
            cand_id, source_url, name = row[0], row[1], row[2]
            canon = canonical_github_url(source_url) if source_url else None
            repo_key = canonical_repo_key(source_url) if source_url else None
            name_str = name if isinstance(name, str) else None
            entry = _IndexEntry(
                kind="candidate",
                match_id=str(cand_id),
                url=canon or source_url,
                repo_key=repo_key,
                name=name_str,
                compact_name=_compact_name(name_str) if name_str else None,
            )
            self._entries.append(entry)
            if canon:
                self._by_url.setdefault(canon, entry)
            if repo_key:
                self._by_repo_key.setdefault(repo_key, entry)

    # -- public API ---------------------------------------------------------

    def check_url(self, url: str, *, name: Optional[str] = None) -> Optional[DupHit]:
        """Check a URL (and optional name) against every population.

        Rule order: canonical_url (yaml) > canonical_url (candidate) >
        org_repo_alias > intra-batch > fuzzy_name.
        """
        canon = canonical_github_url(url)
        repo_key = canonical_repo_key(url)

        # 1 & 2: exact canonical URL against YAML then candidate.
        if canon is not None:
            entry = self._by_url.get(canon)
            if entry is not None:
                return DupHit(
                    kind=entry.kind,
                    match_id=entry.match_id,
                    match_url=entry.url,
                    match_name=entry.name,
                    similarity=1.0,
                    rule="canonical_url",
                )

        # 3: owner/repo key (tolerates suffix differences like /tree/main).
        if repo_key is not None:
            entry = self._by_repo_key.get(repo_key)
            if entry is not None:
                return DupHit(
                    kind=entry.kind,
                    match_id=entry.match_id,
                    match_url=entry.url,
                    match_name=entry.name,
                    similarity=1.0,
                    rule="org_repo_alias",
                )

        # 5 (before 4, so intra-batch URL hits beat fuzzy-name):
        if canon is not None and canon in self._batch_by_url:
            stored_url, stored_name = self._batch_by_url[canon]
            return DupHit(
                kind="batch",
                match_id=stored_url,
                match_url=stored_url,
                match_name=stored_name,
                similarity=1.0,
                rule="canonical_url",
            )
        if repo_key is not None and repo_key in self._batch_by_repo_key:
            stored_url, stored_name = self._batch_by_repo_key[repo_key]
            return DupHit(
                kind="batch",
                match_id=stored_url,
                match_url=stored_url,
                match_name=stored_name,
                similarity=1.0,
                rule="org_repo_alias",
            )

        # 4: fuzzy name last (weakest signal).
        if name:
            hit = self.check_name(name)
            if hit is not None:
                return hit

        return None

    def check_name(self, name: str) -> Optional[DupHit]:
        """Fuzzy name match against YAML + candidate names.

        We compare both the raw names (via ``token_set_ratio``) and a
        compacted form (lowercased, non-alnum stripped). Tool names in the
        wild vary on casing and separators — "PydanticAI" vs "pydantic-ai"
        — so comparing both forms and keeping the max lets us hold a high
        threshold (90) without under-matching.
        """
        if not name or fuzz is None:
            return None
        compact = _compact_name(name)
        best_score = 0.0
        best_entry: Optional[_IndexEntry] = None
        for entry in self._entries:
            if not entry.name:
                continue
            raw_score = float(fuzz.token_set_ratio(name, entry.name))
            compact_score = 0.0
            if compact and entry.compact_name:
                compact_score = float(fuzz.token_set_ratio(compact, entry.compact_name))
            score = max(raw_score, compact_score)
            if score > best_score:
                best_score = score
                best_entry = entry
        if best_entry is None or best_score < self.fuzzy_threshold:
            return None
        return DupHit(
            kind=best_entry.kind,
            match_id=best_entry.match_id,
            match_url=best_entry.url,
            match_name=best_entry.name,
            similarity=best_score / 100.0,
            rule="fuzzy_name",
        )

    def register_batch(self, url: str, name: Optional[str] = None) -> None:
        """Mark ``url`` as seen in the current batch.

        Subsequent :meth:`check_url` calls for the same canonical URL (or
        repo key) will return a ``kind='batch'`` hit.
        """
        canon = canonical_github_url(url)
        repo_key = canonical_repo_key(url)
        if canon is None and repo_key is None:
            # Still record non-GitHub URLs so exact-string repeats get caught.
            canon = url
        if canon is not None:
            self._batch_by_url.setdefault(canon, (canon, name))
        if repo_key is not None:
            self._batch_by_repo_key.setdefault(repo_key, (canon or url, name))

    # -- helpers (useful for tests / callers) -------------------------------

    def known_urls(self) -> Iterable[str]:
        """Iterate every canonical URL currently indexed (YAML + candidates)."""
        return list(self._by_url.keys())
