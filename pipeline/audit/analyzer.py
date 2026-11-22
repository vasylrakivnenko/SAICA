"""Top-level orchestrator: ``audit_repo(url) -> AuditReport``.

Pipeline:
  1. Validate the URL (``https://github.com/<owner>/<repo>`` and nothing else).
  2. Fetch through the GitHub API: one listing of the repository's files,
     then only the files the detectors read (see
     :func:`pipeline.audit.detectors.fetch_plan`). Files and folders whose
     presence alone matters are created empty; nothing is downloaded for
     them. There is no ``git clone``.
  3. Detect stack: languages, runtime hints, CI, package managers, agents,
     supervision tools.
  4. Build coverage grid (FM × paradigm × tier).
  5. Compute gaps and catalog suggestions, and the limits of the audit.
  6. Render Markdown.
  7. Return :class:`AuditReport`.

The fetch is bounded (:class:`FetchLimits`): a cap on the listing size, on
the number of files, on the bytes per file and in total, and one wall-clock
deadline for the whole fetch. Requests go to two fixed hosts over https;
a redirect to any other host is refused. No token is sent unless the
caller passes one (the public ``/assess`` endpoint never does).

``audit_repo_local(path)`` audits a directory that is already on disk.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin, urlsplit

import requests
import urllib3

from pipeline.audit.coverage import build_coverage_grid, find_gaps
from pipeline.audit.detectors import (
    MAX_READ_BYTES,
    detect_agents,
    detect_ci_providers,
    detect_languages,
    detect_package_managers,
    detect_runtime_hints,
    detect_supervision_tools,
    detectable_tool_ids,
    fetch_plan,
)
from pipeline.audit.kg import load_tool_index
from pipeline.audit.render import to_markdown
from pipeline.audit.schemas import (
    AuditLimits,
    AuditReport,
    CoverageGrid,
    DetectedStack,
    DetectedTool,
    GapItem,
)

log = logging.getLogger(__name__)

# Owner: letters, digits, "-", "_" (never a leading "-" or "."). Repo: the
# same plus "." (".github" is a real repository name), but not "." or "..".
GITHUB_URL_RE = re.compile(
    r"^https://github\.com/"
    r"([A-Za-z0-9_][A-Za-z0-9_-]{0,99})/"
    r"((?!\.{1,2}(?:\.git)?/?$)[A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$"
)

API_HOST = "api.github.com"
RAW_HOST = "raw.githubusercontent.com"
USER_AGENT = "saica-audit (+https://saica.ai/assess/)"
# Longest wait for one connect or one socket read.
READ_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Errors a caller can show to a user
# ---------------------------------------------------------------------------


class AuditError(RuntimeError):
    """An audit that could not be completed. ``str()`` is safe to show."""


class RepoNotFound(AuditError):
    """GitHub answered 404: no such repository, or it is private."""


class RepoTooLarge(AuditError):
    """The repository listing is larger than the audit accepts."""


class FetchUnavailable(AuditError):
    """GitHub could not be reached in time, or its rate limit is used up."""


# ---------------------------------------------------------------------------
# URL parsing + validation
# ---------------------------------------------------------------------------


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    """Validate ``repo_url`` and return ``(owner, repo)``.

    Raises ``ValueError`` for anything that is not
    ``https://github.com/<owner>/<repo>`` (no other host, no ``/tree/``,
    no ``/blob/``, no query, no fragment, no ``.`` or ``..`` segment).
    """
    if not isinstance(repo_url, str):
        raise ValueError("repo_url must be a string")
    url = repo_url.strip()
    if "/tree/" in url or "/blob/" in url or "#" in url or "?" in url:
        raise ValueError(
            "repo_url must point to a repo root, not a branch or file "
            "(no /tree/, /blob/, # or ? allowed)."
        )
    m = GITHUB_URL_RE.match(url)
    if not m:
        raise ValueError("repo_url must look like https://github.com/<owner>/<repo>")
    return m.group(1), m.group(2)


# ---------------------------------------------------------------------------
# Bounded fetch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchLimits:
    """Hard caps for one remote audit."""

    max_listing_bytes: int = 8_000_000  # the JSON listing of the repository
    max_files: int = 60  # files downloaded
    max_file_bytes: int = MAX_READ_BYTES  # the detectors read no more
    max_total_bytes: int = 4_000_000  # all downloaded files together
    deadline_seconds: float = 20.0  # wall clock for the whole fetch
    max_placeholders: int = 400  # empty files / folders created


@dataclass
class FetchStats:
    """What one fetch did; copied into the report's limits."""

    files_listed: int = 0
    files_read: int = 0
    bytes_read: int = 0
    truncated: list[str] = field(default_factory=list)


class GitHubClient:
    """GET against a fixed set of https hosts, with a byte cap and a deadline.

    One instance serves one audit: the deadline starts when it is created.
    """

    def __init__(
        self,
        *,
        deadline_seconds: float,
        token: str | None = None,
        allowed_hosts: frozenset[str] = frozenset({API_HOST, RAW_HOST}),
        schemes: tuple[str, ...] = ("https",),
        session: requests.Session | None = None,
    ) -> None:
        self._deadline = time.monotonic() + deadline_seconds
        self._token = token
        self._hosts = allowed_hosts
        self._schemes = schemes
        self._session = session or requests.Session()

    def remaining(self) -> float:
        return self._deadline - time.monotonic()

    def _check(self, url: str) -> str:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme not in self._schemes or host not in self._hosts:
            raise FetchUnavailable("The fetch was redirected off GitHub and stopped.")
        return host

    def get(self, url: str, *, max_bytes: int) -> tuple[int, bytes, bool, dict]:
        """Return ``(status, body, cut, headers)``.

        ``body`` holds at most ``max_bytes``; ``cut`` says the response was
        longer. Raises :class:`FetchUnavailable` on a network error, a
        redirect off the allowed hosts or when the deadline passes.
        """
        for _ in range(4):  # the request plus at most three redirects
            host = self._check(url)
            left = self.remaining()
            if left <= 0:
                raise FetchUnavailable("The audit ran out of time while fetching.")
            headers = {"User-Agent": USER_AGENT}
            if host == API_HOST:
                headers["Accept"] = "application/vnd.github+json"
                if self._token:
                    headers["Authorization"] = f"Bearer {self._token}"
            try:
                resp = self._session.get(
                    url,
                    headers=headers,
                    stream=True,
                    allow_redirects=False,
                    timeout=(min(READ_TIMEOUT, left), min(READ_TIMEOUT, left)),
                )
            except requests.RequestException as exc:
                log.warning("audit fetch failed: %s: %s", url, type(exc).__name__)
                raise FetchUnavailable("GitHub could not be reached.") from exc
            try:
                if resp.status_code in (301, 302, 307, 308):
                    location = resp.headers.get("Location") or ""
                    url = urljoin(url, location)
                    continue
                body = bytearray()
                cut = False
                # read1 returns after one socket read, so the deadline is
                # checked at least every READ_TIMEOUT seconds even when a
                # server sends one byte at a time.
                read1 = getattr(resp.raw, "read1", None)
                try:
                    while True:
                        if self.remaining() <= 0:
                            raise FetchUnavailable(
                                "The audit ran out of time while fetching."
                            )
                        if read1 is not None:
                            chunk = read1(65536, decode_content=True)
                        else:  # urllib3 < 2
                            chunk = resp.raw.read(8192, decode_content=True)
                        if not chunk:
                            break
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            cut = True
                            del body[max_bytes:]
                            break
                except (
                    requests.RequestException,
                    urllib3.exceptions.HTTPError,
                    OSError,
                ) as exc:
                    log.warning("audit read failed: %s: %s", url, type(exc).__name__)
                    raise FetchUnavailable("GitHub could not be reached.") from exc
                return resp.status_code, bytes(body), cut, dict(resp.headers)
            finally:
                resp.close()
        raise FetchUnavailable("Too many redirects while fetching.")

    def close(self) -> None:
        self._session.close()


def _listing(
    client: GitHubClient,
    owner: str,
    repo: str,
    ref: str,
    *,
    recursive: bool,
    limits: FetchLimits,
) -> dict:
    """One call to the git-trees API; returns the parsed JSON object."""
    url = (
        f"https://{API_HOST}/repos/{quote(owner)}/{quote(repo)}/git/trees/{quote(ref)}"
    )
    if recursive:
        url += "?recursive=1"
    status, body, cut, headers = client.get(url, max_bytes=limits.max_listing_bytes)
    if status == 404:
        raise RepoNotFound(
            "GitHub has no public repository at that address (it may be private, "
            "empty or misspelled)."
        )
    if status in (403, 429):
        if headers.get("X-RateLimit-Remaining") == "0" or status == 429:
            raise FetchUnavailable(
                "GitHub's request limit for this service is used up for now."
            )
        raise FetchUnavailable("GitHub refused the request.")
    if status == 409:  # "Git Repository is empty."
        raise RepoNotFound("That repository is empty.")
    if status != 200:
        raise FetchUnavailable(f"GitHub answered with status {status}.")
    if cut:
        raise RepoTooLarge("The repository's file listing is too large to audit.")
    try:
        doc = json.loads(body)
    except ValueError as exc:
        raise FetchUnavailable("GitHub sent a listing that could not be read.") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("tree"), list):
        raise FetchUnavailable("GitHub sent a listing that could not be read.")
    return doc


def _entries(
    doc: dict, prefix: str = ""
) -> tuple[list[str], list[str], dict[str, str]]:
    """``(files, folders, folder shas)`` of one listing, paths under ``prefix``."""
    blobs: list[str] = []
    trees: list[str] = []
    shas: dict[str, str] = {}
    for item in doc["tree"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        path = prefix + item["path"]
        if item.get("type") == "blob":
            blobs.append(path)
        elif item.get("type") == "tree":
            trees.append(path)
            if isinstance(item.get("sha"), str):
                shas[path] = item["sha"]
    return blobs, trees, shas


# Folders the detectors look into, for the walk used when GitHub cuts the
# recursive listing short (more than 100,000 entries).
_WALK_DIRS: tuple[str, ...] = (".github", ".github/workflows", ".circleci", ".zed")


def _list_repo(
    client: GitHubClient, owner: str, repo: str, limits: FetchLimits
) -> tuple[list[str], list[str]]:
    """``(files, folders)`` of the default branch, relative to the root."""
    doc = _listing(client, owner, repo, "HEAD", recursive=True, limits=limits)
    if not doc.get("truncated"):
        blobs, trees, _ = _entries(doc)
        return blobs, trees
    # Very large repository: read the root and the few folders we need.
    blobs, trees, shas = _entries(
        _listing(client, owner, repo, "HEAD", recursive=False, limits=limits)
    )
    for folder in _WALK_DIRS:
        sha = shas.get(folder)
        if not sha:
            continue
        sub_blobs, sub_trees, sub_shas = _entries(
            _listing(client, owner, repo, sha, recursive=False, limits=limits),
            prefix=folder + "/",
        )
        blobs.extend(sub_blobs)
        trees.extend(sub_trees)
        shas.update(sub_shas)
    return blobs, trees


def _safe_target(dest: Path, rel: str) -> Path | None:
    """``dest / rel`` if it stays inside ``dest``; else ``None``."""
    if not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        return None
    if any(part in ("", ".", "..") for part in rel.split("/")):
        return None
    return dest / rel


def fetch_repo(
    owner: str,
    repo: str,
    dest: Path,
    *,
    limits: FetchLimits | None = None,
    token: str | None = None,
    client: GitHubClient | None = None,
) -> FetchStats:
    """Fill ``dest`` with what the detectors need from ``owner/repo``.

    Raises :class:`AuditError` when the repository cannot be listed. A cap
    reached while downloading files does not raise: the fetch stops and the
    returned stats say what was cut.
    """
    limits = limits or FetchLimits()
    own_client = client is None
    client = client or GitHubClient(
        deadline_seconds=limits.deadline_seconds, token=token
    )
    stats = FetchStats()
    try:
        blobs, trees = _list_repo(client, owner, repo, limits)
        stats.files_listed = len(blobs)
        content, files, folders = fetch_plan(blobs, trees)
        dest.mkdir(parents=True, exist_ok=True)

        placeholders = [(p, False) for p in files] + [(p, True) for p in folders]
        if len(placeholders) > limits.max_placeholders:
            placeholders = placeholders[: limits.max_placeholders]
            stats.truncated.append("Some marker files were not checked (too many).")
        for rel, is_dir in placeholders:
            target = _safe_target(dest, rel)
            if target is None:
                continue
            if is_dir:
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()

        if len(content) > limits.max_files:
            stats.truncated.append(
                f"Only the first {limits.max_files} of {len(content)} manifest and "
                "workflow files were read."
            )
            content = content[: limits.max_files]
        raw_base = f"https://{RAW_HOST}/{quote(owner)}/{quote(repo)}/HEAD/"
        for rel in content:
            target = _safe_target(dest, rel)
            if target is None:
                continue
            room = limits.max_total_bytes - stats.bytes_read
            if room <= 0:
                stats.truncated.append(
                    "The download limit was reached; some files were not read."
                )
                break
            if client.remaining() <= 0:
                stats.truncated.append(
                    "The time limit was reached; some files were not read."
                )
                break
            try:
                status, body, cut, _ = client.get(
                    raw_base + quote(rel), max_bytes=min(limits.max_file_bytes, room)
                )
            except FetchUnavailable:
                stats.truncated.append(
                    "The time limit was reached; some files were not read."
                )
                break
            if status != 200:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            stats.files_read += 1
            stats.bytes_read += len(body)
            if cut:
                stats.truncated.append(f"{rel} was read in part (it is very large).")
    finally:
        if own_client:
            client.close()
    return stats


# ---------------------------------------------------------------------------
# Stack assembly + summary
# ---------------------------------------------------------------------------


def _split_resolved(
    detected: list[DetectedTool],
) -> tuple[list[DetectedTool], list[DetectedTool]]:
    resolved = [d for d in detected if d.in_kg]
    unresolved = [d for d in detected if not d.in_kg]
    return resolved, unresolved


def _build_stack(repo_root: Path) -> DetectedStack:
    detected_tools = detect_supervision_tools(repo_root)
    resolved, unresolved = _split_resolved(detected_tools)
    return DetectedStack(
        languages=detect_languages(repo_root),
        runtime_hints=detect_runtime_hints(repo_root),
        ci_providers=detect_ci_providers(repo_root),
        package_managers=detect_package_managers(repo_root),
        agents=detect_agents(repo_root),
        supervision_tools=resolved,
        unresolved_tools=unresolved,
    )


def distinct_tool_count(stack: DetectedStack) -> int:
    """Catalog tools found, each counted once however often it was seen."""
    return len({t.id for t in stack.supervision_tools if t.in_kg and t.id})


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _build_summary(
    repo_url: str,
    stack: DetectedStack,
    coverage: CoverageGrid,
    gaps: list[GapItem],
) -> str:
    n_tools = distinct_tool_count(stack)
    n_covered = len(coverage.failure_modes_covered)
    n_total = n_covered + len(coverage.failure_modes_missing)
    n_blind = len(coverage.failure_modes_not_assessable)
    high = sum(1 for g in gaps if g.severity == "high")
    medium = sum(1 for g in gaps if g.severity == "medium")
    repo_name = repo_url.rstrip("/").rsplit("/", 1)[-1]

    if n_tools == 0:
        head = f"The audit found no catalog tool in {repo_name}."
    else:
        head = (
            f"The audit found {_plural(n_tools, 'catalog tool')} in {repo_name}. "
            f"Their tags name {n_covered} of {n_total} failure modes "
            "(a tag is what the tool says it addresses, not a measurement)."
        )
    parts = [
        head,
        f"Gaps: {high} high, {medium} medium.",
    ]
    if n_blind:
        parts.append(
            f"{_plural(n_blind, 'failure mode')} cannot be assessed: the audit "
            "cannot detect any catalog tool for "
            f"{'it' if n_blind == 1 else 'them'}."
        )
    if stack.agents:
        parts.append(
            "Coding agent(s) detected: " + ", ".join(a.name for a in stack.agents) + "."
        )
    return " ".join(parts)


def build_limits(
    kg_index: dict[str, dict],
    coverage: CoverageGrid,
    stats: FetchStats | None = None,
) -> AuditLimits:
    """What this audit can and cannot see, for the report."""
    detectable = detectable_tool_ids(kg_index)
    notes = [
        "Only the repository root and its .github, .circleci and .zed folders "
        "are read. A manifest in a sub-folder (a monorepo package) is not seen.",
        "A tool is found through a GitHub Actions `uses:` step, a dependency "
        "name, a `[tool.<name>]` table in pyproject.toml, a pre-commit hook or "
        "a named config file. A tool started any other way (a `run:` step, "
        "tox, a Makefile) is not seen.",
        "Coverage tiers and suggestions come from the catalog's tags. They say "
        "what a tool claims to address, not how well it does it.",
    ]
    return AuditLimits(
        catalog_tools=len(kg_index),
        detectable_tools=sorted(detectable),
        undetectable_tools=sorted(set(kg_index) - detectable),
        not_assessable_failure_modes=list(coverage.failure_modes_not_assessable),
        files_listed=stats.files_listed if stats else None,
        files_read=stats.files_read if stats else None,
        bytes_read=stats.bytes_read if stats else None,
        truncated=list(dict.fromkeys(stats.truncated)) if stats else [],
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------


def audit_repo_local(
    repo_path: str | Path,
    repo_url: Optional[str] = None,
    *,
    fetch_stats: FetchStats | None = None,
) -> AuditReport:
    """Audit a directory that is already on disk.

    ``repo_url`` is the URL shown in the report; when omitted it is a
    ``file://`` URL of the path. Raises ``FileNotFoundError`` when the
    path is not a directory.
    """
    root = Path(repo_path).resolve()
    if not root.is_dir():
        raise FileNotFoundError(
            f"repo path does not exist or is not a directory: {root}"
        )

    url = repo_url or root.as_uri()
    kg = load_tool_index()

    stack = _build_stack(root)
    coverage = build_coverage_grid(stack.supervision_tools, kg_index=kg)
    gaps = find_gaps(coverage, stack, kg_index=kg)
    summary = _build_summary(url, stack, coverage, gaps)

    report = AuditReport(
        repo_url=url,
        audited_at=date.today(),
        stack=stack,
        coverage=coverage,
        gaps=gaps,
        summary=summary,
        markdown="",  # filled below; rendering needs the rest of the object
        limits=build_limits(kg, coverage, fetch_stats),
    )
    report.markdown = to_markdown(report)
    return report


def audit_repo(
    repo_url: str,
    *,
    limits: FetchLimits | None = None,
    github_token: str | None = None,
    client: GitHubClient | None = None,
) -> AuditReport:
    """Audit a public GitHub repository by URL.

    Raises ``ValueError`` for a URL that is not a GitHub repository root
    and :class:`AuditError` (a ``RuntimeError``) when the repository cannot
    be fetched; the message of either is safe to show to a user.
    """
    owner, repo = parse_repo_url(repo_url)
    with tempfile.TemporaryDirectory(prefix="saica-audit-") as tmp:
        dest = Path(tmp) / "repo"
        stats = fetch_repo(
            owner, repo, dest, limits=limits, token=github_token, client=client
        )
        return audit_repo_local(
            dest, repo_url=f"https://github.com/{owner}/{repo}", fetch_stats=stats
        )


__all__ = [
    "AuditError",
    "FetchLimits",
    "FetchStats",
    "FetchUnavailable",
    "GITHUB_URL_RE",
    "GitHubClient",
    "RepoNotFound",
    "RepoTooLarge",
    "audit_repo",
    "audit_repo_local",
    "build_limits",
    "distinct_tool_count",
    "fetch_repo",
    "parse_repo_url",
]
