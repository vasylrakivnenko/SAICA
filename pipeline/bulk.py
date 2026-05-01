"""Bulk ingestion core for SAICA-KG.

Reads the awesome-list candidate file (``research/candidates_YYYYMMDD.json``),
ranks candidates by cross-list source-count, and walks each through the
GitHub API + README fetch + raw_search_results insert path. Stops before
Kimi extraction (the user triggers that separately to control cost).

Public API:
    load_candidates(path)
    rank_candidates(cands, min_stars=None, since=None)   # (no star fetch here)
    ingest_one(cand, *, dup, github_session, dry_run=False, min_stars=None, since=None)
    run_bulk(...)  -> BulkRunReport  (drives the whole loop)
    write_report(report, out_dir) -> Path

This module is importable from tests; the CLI wrapper lives in
``pipeline.cli.bulk_ingest``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

log = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CANDIDATE_FILE = REPO_ROOT / "research" / "candidates_20260422.json"
DEFAULT_REPORT_DIR = REPO_ROOT / "research"

GITHUB_API = "https://api.github.com"
BULK_SOURCE = "bulk_ingest"
BULK_QUERY = "awesome_lists_20260422"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    owner: str
    repo: str
    full_name: str
    url: str
    sources: list[str]
    source_count: int
    suggested_id: Optional[str] = None
    already_in_kg: bool = False
    matched_tool_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Candidate":
        owner = d.get("owner") or ""
        # Some candidate exports use ``repo`` as the bare repo name; others as
        # ``owner/repo``. Normalise both.
        repo_field = d.get("repo") or ""
        full_name = d.get("full_name") or ""
        if "/" in repo_field and not full_name:
            full_name = repo_field
            owner, _, repo_field = repo_field.partition("/")
        if not full_name:
            full_name = f"{owner}/{repo_field}" if owner else repo_field
        url = d.get("url") or f"https://github.com/{full_name}"
        sources = list(d.get("sources") or [])
        source_count = int(d.get("source_count") or len(sources))
        return cls(
            owner=owner,
            repo=repo_field,
            full_name=full_name,
            url=url,
            sources=sources,
            source_count=source_count,
            suggested_id=d.get("suggested_id"),
            already_in_kg=bool(d.get("already_in_kg")),
            matched_tool_id=d.get("matched_tool_id"),
        )


@dataclass
class IngestResult:
    candidate: Candidate
    status: str  # one of: ingested, dry_run, skip_yaml, skip_candidate, skip_batch,
    # skip_min_stars, skip_since, github_404, github_rate_limited, error
    detail: str = ""
    stars: Optional[int] = None
    pushed_at: Optional[str] = None
    raw_row_id: Optional[int] = None


@dataclass
class BulkRunReport:
    started_at: datetime
    finished_at: datetime
    input_file: Path
    total_candidates: int
    top: Optional[int]
    min_stars: Optional[int]
    since: Optional[str]
    dry_run: bool
    preprocess_after: bool
    ranked: int
    results: list[IngestResult] = field(default_factory=list)

    # Aggregates (computed on demand).
    @property
    def elapsed(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for r in self.results:
            c[r.status] = c.get(r.status, 0) + 1
        return c

    @property
    def dedup_hits(self) -> int:
        return sum(
            self.counts.get(k, 0) for k in ("skip_yaml", "skip_candidate", "skip_batch")
        )


# ---------------------------------------------------------------------------
# Candidate loading + ranking
# ---------------------------------------------------------------------------


def load_candidates(path: Path) -> tuple[list[Candidate], dict[str, Any]]:
    """Load a candidates file and return (candidates, raw_file_meta)."""
    data = json.loads(Path(path).read_text())
    raw = data.get("candidates") or []
    cands = [Candidate.from_dict(d) for d in raw if isinstance(d, dict)]
    meta = {k: v for k, v in data.items() if k != "candidates"}
    return cands, meta


def rank_candidates(cands: Iterable[Candidate]) -> list[Candidate]:
    """Sort by descending source_count, then alphabetical full_name."""
    return sorted(
        cands,
        key=lambda c: (-int(c.source_count or 0), (c.full_name or "").lower()),
    )


# ---------------------------------------------------------------------------
# GitHub API client (single-threaded, rate-limit aware)
# ---------------------------------------------------------------------------


class GitHubClient:
    """Thin wrapper around /repos/<owner>/<repo> with polite rate-limit handling."""

    def __init__(
        self,
        *,
        token: Optional[str] = None,
        baseline_sleep_s: float = 1.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.baseline_sleep_s = baseline_sleep_s
        self.session = session or requests.Session()
        self.rate_limit_hits = 0

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "saica-kg-bulk-ingest/0.1",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _sleep_for_reset(self, resp: requests.Response) -> None:
        reset = resp.headers.get("X-RateLimit-Reset")
        if not reset:
            time.sleep(60.0)
            return
        try:
            reset_ts = int(reset)
        except ValueError:
            time.sleep(60.0)
            return
        delta = max(1.0, reset_ts - time.time() + 1.0)
        log.warning("github rate-limited, sleeping %.1fs until reset", delta)
        time.sleep(min(delta, 900.0))  # cap so a runaway clock can't wedge us for hours

    def get_repo(self, owner: str, repo: str) -> tuple[str, Optional[dict[str, Any]]]:
        """Return (status, payload).

        status is one of: ok, not_found, rate_limited, error.
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}"
        try:
            resp = self.session.get(url, headers=self._headers(), timeout=30)
        except requests.RequestException as exc:
            log.warning(
                "github repo fetch network error for %s/%s: %s", owner, repo, exc
            )
            return ("error", None)

        if resp.status_code == 404:
            return ("not_found", None)
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            self.rate_limit_hits += 1
            self._sleep_for_reset(resp)
            # Retry once after waiting.
            try:
                resp = self.session.get(url, headers=self._headers(), timeout=30)
            except requests.RequestException as exc:
                log.warning(
                    "github retry network error for %s/%s: %s", owner, repo, exc
                )
                return ("error", None)
            if resp.status_code == 404:
                return ("not_found", None)
            if resp.status_code == 403:
                return ("rate_limited", None)
        if not resp.ok:
            log.warning(
                "github repo fetch %s/%s returned %s", owner, repo, resp.status_code
            )
            return ("error", None)
        try:
            payload = resp.json()
        except ValueError:
            return ("error", None)
        time.sleep(self.baseline_sleep_s)
        return ("ok", payload)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def _parse_since(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    v = value.strip()
    try:
        if len(v) == 10 and v[4] == "-" and v[7] == "-":
            return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid --since value {value!r}: {exc}") from exc


def _pushed_after(payload: dict[str, Any], since_dt: datetime) -> bool:
    pushed = payload.get("pushed_at")
    if not pushed:
        return False
    try:
        dt = datetime.fromisoformat(str(pushed).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= since_dt


# ---------------------------------------------------------------------------
# Per-candidate ingest
# ---------------------------------------------------------------------------


def _canonical_url(cand: Candidate) -> str:
    """Best-effort canonical GitHub URL for a candidate.

    Uses ``pipeline.dedup.canonical_github_url`` if importable; otherwise falls
    back to ``https://github.com/<owner>/<repo>`` lower-cased.
    """
    fallback = f"https://github.com/{cand.full_name}".lower()
    try:
        from pipeline.dedup import canonical_github_url  # type: ignore

        canon = canonical_github_url(cand.url or f"https://github.com/{cand.full_name}")
        return canon or fallback
    except Exception:  # noqa: BLE001
        return fallback


def ingest_one(
    cand: Candidate,
    *,
    dup: Any,
    github: Optional[GitHubClient],
    dry_run: bool = False,
    min_stars: Optional[int] = None,
    since_dt: Optional[datetime] = None,
) -> IngestResult:
    """Run the per-candidate pipeline: dedup -> GitHub -> README -> DB insert."""
    canon = _canonical_url(cand)

    # 1. Dedup check.
    try:
        hit = dup.check_url(canon)
    except Exception as exc:  # noqa: BLE001
        log.warning("dup.check_url failed for %s: %s", canon, exc)
        hit = None

    hit_kind = _classify_hit(hit)
    if hit_kind == "yaml":
        return IngestResult(cand, "skip_yaml", detail="already in KG")
    if hit_kind == "candidate":
        return IngestResult(cand, "skip_candidate", detail="already staged")
    if hit_kind == "batch":
        return IngestResult(cand, "skip_batch", detail="already in this batch")

    if dry_run:
        # Register in batch so repeated rows in dry-run dedup against themselves.
        _try_register_batch(dup, canon)
        return IngestResult(cand, "dry_run", detail="ranked (no writes)")

    assert github is not None, "github client required for non-dry-run"

    # 2. GitHub repo metadata.
    status, payload = github.get_repo(cand.owner, cand.repo)
    if status == "not_found":
        _try_register_batch(dup, canon)
        return IngestResult(cand, "github_404", detail="repo removed or renamed")
    if status == "rate_limited":
        return IngestResult(cand, "github_rate_limited", detail="rate limit persisted")
    if status != "ok" or not isinstance(payload, dict):
        return IngestResult(cand, "error", detail=f"github status={status}")

    stars = int(payload.get("stargazers_count") or 0)
    pushed_at = payload.get("pushed_at")
    if min_stars is not None and stars < min_stars:
        _try_register_batch(dup, canon)
        return IngestResult(
            cand,
            "skip_min_stars",
            detail=f"{stars} < {min_stars}",
            stars=stars,
            pushed_at=pushed_at,
        )
    if since_dt is not None and not _pushed_after(payload, since_dt):
        _try_register_batch(dup, canon)
        return IngestResult(
            cand,
            "skip_since",
            detail=f"pushed_at={pushed_at} < {since_dt.date().isoformat()}",
            stars=stars,
            pushed_at=pushed_at,
        )

    # 3. README.
    readme_text: Optional[str] = None
    try:
        from pipeline.sources.github import fetch_readme

        readme_text = fetch_readme(cand.owner, cand.repo)
    except Exception as exc:  # noqa: BLE001
        log.warning("readme fetch failed for %s: %s", cand.full_name, exc)

    snippet = (readme_text or payload.get("description") or "")[:400]
    title = payload.get("description") or payload.get("full_name") or cand.full_name

    # 4. Insert into raw_search_results.
    try:
        from pipeline.db import insert_raw_result

        row_id = insert_raw_result(
            BULK_SOURCE,
            BULK_QUERY,
            url=canon,
            title=title,
            snippet=snippet,
            raw_json={
                "query": BULK_QUERY,
                "awesome_sources": cand.sources,
                "source_count": cand.source_count,
                "result": payload,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("raw_search_results insert failed for %s: %s", canon, exc)
        return IngestResult(
            cand, "error", detail=f"db insert: {exc}", stars=stars, pushed_at=pushed_at
        )

    # 5. Register in batch dedup set.
    _try_register_batch(dup, canon)

    detail = "inserted" if row_id is not None else "duplicate row (content_hash)"
    return IngestResult(
        cand,
        "ingested",
        detail=detail,
        stars=stars,
        pushed_at=pushed_at,
        raw_row_id=row_id,
    )


def _classify_hit(hit: Any) -> Optional[str]:
    """Normalise DupChecker.check_url return into {yaml, candidate, batch, None}."""
    if hit is None or hit is False:
        return None
    # Dataclass / object with .source or .kind attribute.
    for attr in ("source", "kind", "bucket"):
        val = getattr(hit, attr, None)
        if isinstance(val, str):
            low = val.lower()
            if "yaml" in low or low == "kg":
                return "yaml"
            if "candidate" in low:
                return "candidate"
            if "batch" in low:
                return "batch"
    if isinstance(hit, dict):
        for key in ("source", "kind", "bucket"):
            v = hit.get(key)
            if isinstance(v, str):
                low = v.lower()
                if "yaml" in low or low == "kg":
                    return "yaml"
                if "candidate" in low:
                    return "candidate"
                if "batch" in low:
                    return "batch"
    if isinstance(hit, str):
        low = hit.lower()
        if "yaml" in low or low == "kg":
            return "yaml"
        if "candidate" in low:
            return "candidate"
        if "batch" in low:
            return "batch"
    # Truthy but unclassifiable — treat conservatively as a candidate hit.
    return "candidate"


def _try_register_batch(dup: Any, url: str) -> None:
    fn = getattr(dup, "register_batch", None)
    if fn is None:
        return
    try:
        fn(url)
    except Exception as exc:  # noqa: BLE001
        log.debug("register_batch(%s) failed: %s", url, exc)


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------


def run_bulk(
    *,
    input_file: Path = DEFAULT_CANDIDATE_FILE,
    top: Optional[int] = None,
    min_stars: Optional[int] = None,
    since: Optional[str] = None,
    dry_run: bool = False,
    preprocess_after: bool = False,
    progress_fn: Optional[Any] = None,
) -> BulkRunReport:
    """Load candidates, rank, and ingest up to ``top`` of them."""
    started_at = datetime.now(timezone.utc)
    input_path = Path(input_file)
    cands, _meta = load_candidates(input_path)
    total = len(cands)
    ranked = rank_candidates(cands)
    selected = ranked[:top] if top else ranked

    since_dt = _parse_since(since)

    # Import DupChecker lazily so the import error (if any) is deferred.
    if dry_run:
        dup = _DryRunDup()
        github: Optional[GitHubClient] = None
    else:
        from pipeline.dedup import DupChecker  # type: ignore

        dup = DupChecker()
        github = GitHubClient()

    results: list[IngestResult] = []
    for idx, cand in enumerate(selected, 1):
        res = ingest_one(
            cand,
            dup=dup,
            github=github,
            dry_run=dry_run,
            min_stars=min_stars,
            since_dt=since_dt,
        )
        results.append(res)
        if progress_fn is not None:
            try:
                progress_fn(idx, len(selected), res)
            except Exception:  # noqa: BLE001
                pass

    finished_at = datetime.now(timezone.utc)
    report = BulkRunReport(
        started_at=started_at,
        finished_at=finished_at,
        input_file=input_path,
        total_candidates=total,
        top=top,
        min_stars=min_stars,
        since=since,
        dry_run=dry_run,
        preprocess_after=preprocess_after,
        ranked=len(selected),
        results=results,
    )

    if preprocess_after and not dry_run:
        try:
            from pipeline.nlp.pipeline import run as _nlp_run

            _nlp_run()
        except Exception as exc:  # noqa: BLE001
            log.warning("preprocess.run() failed: %s", exc)

    return report


class _DryRunDup:
    """Minimal dedup stub used when --dry-run is passed.

    Tries to use the real ``DupChecker`` if importable so we still see yaml/
    candidate hits; falls back to an in-memory batch-only set.
    """

    def __init__(self) -> None:
        self._inner: Any = None
        self._batch: set[str] = set()
        try:
            from pipeline.dedup import DupChecker  # type: ignore

            self._inner = DupChecker()
        except Exception as exc:  # noqa: BLE001
            log.debug("DupChecker unavailable in dry-run: %s", exc)

    def check_url(self, url: str) -> Any:
        if url.lower() in self._batch:
            return {"source": "batch"}
        if self._inner is not None:
            try:
                return self._inner.check_url(url)
            except Exception as exc:  # noqa: BLE001
                log.debug("inner check_url failed: %s", exc)
        return None

    def register_batch(self, url: str) -> None:
        self._batch.add(url.lower())
        fn = getattr(self._inner, "register_batch", None)
        if fn is not None:
            try:
                fn(url)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


_STATUS_LABELS: dict[str, str] = {
    "ingested": "ingested",
    "dry_run": "dry-run",
    "skip_yaml": "skip (in KG)",
    "skip_candidate": "skip (staged)",
    "skip_batch": "skip (batch dup)",
    "skip_min_stars": "skip (min-stars)",
    "skip_since": "skip (since)",
    "github_404": "github 404",
    "github_rate_limited": "rate-limited",
    "error": "error",
}


def render_report(report: BulkRunReport) -> str:
    ts = report.finished_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    counts = report.counts
    input_rel = report.input_file
    try:
        input_rel = report.input_file.relative_to(REPO_ROOT)
    except ValueError:
        pass

    # Dedup breakdown.
    in_kg = counts.get("skip_yaml", 0)
    in_cand = counts.get("skip_candidate", 0)
    in_batch = counts.get("skip_batch", 0)
    dedup_total = in_kg + in_cand + in_batch
    dedup_detail_parts = []
    if in_kg:
        dedup_detail_parts.append(f"{in_kg} in KG")
    if in_cand:
        dedup_detail_parts.append(f"{in_cand} in candidates")
    if in_batch:
        dedup_detail_parts.append(f"{in_batch} in batch")
    dedup_detail = ", ".join(dedup_detail_parts) if dedup_detail_parts else "none"

    ingested = counts.get("ingested", 0)
    dry_runs = counts.get("dry_run", 0)
    gh_404 = counts.get("github_404", 0)
    rl = counts.get("github_rate_limited", 0)
    min_stars_skipped = counts.get("skip_min_stars", 0)
    since_skipped = counts.get("skip_since", 0)
    errors = counts.get("error", 0)

    filter_bits = [f"--top {report.top}" if report.top else "--top (all)"]
    if report.min_stars is not None:
        filter_bits.append(f"--min-stars {report.min_stars}")
    if report.since:
        filter_bits.append(f"--since {report.since}")
    if report.dry_run:
        filter_bits.append("--dry-run")
    if report.preprocess_after:
        filter_bits.append("--preprocess-after")

    lines: list[str] = []
    lines.append(f"# Bulk ingest run — {ts}")
    lines.append("")
    lines.append(f"- Input file: {input_rel} ({report.total_candidates} candidates)")
    lines.append(f"- Filters: {', '.join(filter_bits)}")
    lines.append(f"- Ranked: {report.ranked}")
    lines.append(f"- Dedup hits: {dedup_total} ({dedup_detail})")
    if min_stars_skipped:
        lines.append(f"- Skipped (min-stars): {min_stars_skipped}")
    if since_skipped:
        lines.append(f"- Skipped (since): {since_skipped}")
    lines.append(f"- GitHub 404: {gh_404}")
    lines.append(f"- GitHub rate-limited: {rl}")
    if report.dry_run:
        lines.append(f"- Would ingest: {dry_runs} (dry-run, no DB writes)")
    else:
        lines.append(f"- Ingested to raw_search_results: {ingested}")
    if errors:
        lines.append(f"- Errors: {errors}")
    lines.append(f"- Elapsed: {_fmt_elapsed(report.elapsed)}")
    lines.append("- Estimated cost: $0.00 (GitHub API free; Kimi extraction deferred)")
    lines.append("")
    lines.append("## Next steps")
    if report.preprocess_after:
        lines.append("- preprocess.run() already executed at end of this run")
    else:
        lines.append(
            "- Run `python -m pipeline.cli.preprocess run` "
            "(or re-run with --preprocess-after)"
        )
    lines.append(
        "- Then `python -m pipeline.cli.extract tools --limit 10` to run Kimi on top 10"
    )
    lines.append("  (~$3 at Kimi pricing)")
    lines.append("")
    lines.append("## Candidates attempted")
    lines.append("")
    lines.append("| # | repo | sources | stars | status | detail |")
    lines.append("|---|------|---------|-------|--------|--------|")
    for i, r in enumerate(report.results, 1):
        stars = "" if r.stars is None else str(r.stars)
        label = _STATUS_LABELS.get(r.status, r.status)
        detail = (r.detail or "").replace("|", "\\|")
        repo = r.candidate.full_name.replace("|", "\\|")
        lines.append(
            f"| {i} | {repo} | {r.candidate.source_count} | {stars} | {label} | {detail} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report: BulkRunReport, out_dir: Path = DEFAULT_REPORT_DIR) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.finished_at.strftime("%Y%m%d%H%M%S")
    path = out_dir / f"bulk_ingest_{stamp}.md"
    path.write_text(render_report(report))
    return path


__all__ = [
    "Candidate",
    "IngestResult",
    "BulkRunReport",
    "GitHubClient",
    "load_candidates",
    "rank_candidates",
    "ingest_one",
    "run_bulk",
    "render_report",
    "write_report",
    "DEFAULT_CANDIDATE_FILE",
    "DEFAULT_REPORT_DIR",
]
