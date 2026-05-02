#!/usr/bin/env python3
"""SAICA-KG discovery scraper.

Fetch curated "awesome-*" lists and tool registries, extract candidate
GitHub-repo URLs, and flag which ones are already represented as a Tool
in SAICA-KG vs which ones are new leads for editorial review.

Usage::

    python validator/discover_candidates.py              # default sources
    python validator/discover_candidates.py --sources urls.txt
    python validator/discover_candidates.py --since 2026-04-01

The script reads each source's top-level ``README.md`` (via
``raw.githubusercontent.com``), extracts ``github.com/<owner>/<repo>``
links, canonicalizes + de-duplicates them, and cross-checks each one
against ``data/tools/*.yml`` by filename and ``repository_url`` match.

Outputs
-------
* ``research/candidates_<YYYYMMDD>.md`` — ranked Markdown table.
* ``research/candidates_<YYYYMMDD>.json`` — parallel machine-readable list.

Rules
-----
* One request per second per host (``sleep 1.1s`` between fetches).
* Custom User-Agent: ``saica-kg-discovery/0.1 (+https://saica-kg.dev)``.
* 404s and parse errors are tolerated — that source is skipped with a note.
* Top-level READMEs only; no recursion.

Additional sources to consider for v0.2 (not implemented here)
--------------------------------------------------------------
* Official MCP Registry (https://registry.modelcontextprotocol.io)
* PulseMCP, Glama, Smithery directories
* HN "Show HN" search for AI coding-agent keywords
* GitHub topic search for ``ai-agent``, ``coding-agent``, ``llm-guardrails``
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print(
        "Missing dependency: pyyaml. Install with: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(2)


REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "data" / "tools"
RESEARCH_DIR = REPO / "research"

USER_AGENT = "saica-kg-discovery/0.1 (+https://saica-kg.dev)"
REQUEST_DELAY = 1.1  # seconds between fetches (per host ≈ github.com)

DEFAULT_SOURCES: list[str] = [
    "https://github.com/punkpeye/awesome-mcp-servers",
    "https://github.com/wong2/awesome-mcp-servers",
    "https://github.com/VoltAgent/awesome-agent-skills",
    "https://github.com/caramaschiHG/awesome-ai-agents-2026",
    "https://github.com/Prat011/awesome-llm-skills",
    "https://github.com/Vvkmnn/awesome-ai-eval",
    "https://github.com/Shubhamsaboo/awesome-llm-apps",
]

# Match any github.com/<owner>/<repo> link in Markdown, HTML, or plain text.
# <owner>/<repo> segments cannot contain "/", "#", "?", ")", "]", quotes, or
# whitespace. We strip trailing punctuation (".", ",", ")", "]", ";", ":")
# below because links in prose often sit next to it.
GITHUB_LINK_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9][A-Za-z0-9._-]*)",
    re.IGNORECASE,
)

# Non-repo top-level paths on github.com to exclude.
GENERIC_OWNERS = {
    "features",
    "topics",
    "collections",
    "sponsors",
    "marketplace",
    "about",
    "pricing",
    "enterprise",
    "customer-stories",
    "readme",
    "search",
    "trending",
    "explore",
    "settings",
    "notifications",
    "pulls",
    "issues",
    "codespaces",
    "orgs",
    "login",
    "join",
    "new",
    "site",
    "security",
    "apps",
}

# Reserved top-level repo names (e.g. `github.com/<owner>/<reserved>`) that
# aren't actual repositories — mostly GitHub profile / UI sub-pages.
GENERIC_REPOS = {
    "followers",
    "following",
    "stars",
    "repositories",
    "projects",
    "packages",
    "sponsors",
    "sponsoring",
}


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _raw_readme_url(source_url: str) -> str | None:
    """Turn ``github.com/<owner>/<repo>`` into its raw HEAD README URL."""
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/?#]+)",
        source_url.strip(),
        re.IGNORECASE,
    )
    if not m:
        return None
    owner = m.group(1)
    repo = m.group(2).removesuffix(".git")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"


def fetch_text(url: str, *, timeout: int = 30) -> tuple[str | None, str | None]:
    """Fetch a URL and return (body, error). Tolerates common HTTP errors."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace"), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return None, f"URL error: {exc.reason}"
    except TimeoutError:
        return None, "timeout"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Link extraction
# ---------------------------------------------------------------------------


def _strip_trailing_punct(s: str) -> str:
    return s.rstrip(".,);:]}>'\"")


def extract_github_repos(text: str) -> set[tuple[str, str]]:
    """Return a set of (owner, repo) tuples found in ``text``."""
    out: set[tuple[str, str]] = set()
    for m in GITHUB_LINK_RE.finditer(text):
        owner = _strip_trailing_punct(m.group(1))
        repo = _strip_trailing_punct(m.group(2)).removesuffix(".git")
        if not owner or not repo:
            continue
        if owner.lower() in GENERIC_OWNERS:
            continue
        if repo.lower() in GENERIC_REPOS:
            continue
        # Avoid bare user profiles that slip in via `github.com/<owner>/`
        # — our regex requires both groups, so this only triggers when repo
        # is legitimately matched. Skip things that are obviously a sub-path
        # like `<owner>/<repo>#readme` — handled by the regex already.
        out.add((owner, repo))
    return out


def canonical_source_repo(source_url: str) -> tuple[str, str] | None:
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/?#]+)",
        source_url.strip(),
        re.IGNORECASE,
    )
    if not m:
        return None
    return m.group(1), m.group(2).removesuffix(".git")


# ---------------------------------------------------------------------------
# KG cross-reference
# ---------------------------------------------------------------------------


def load_kg_index() -> tuple[set[str], dict[str, str]]:
    """Return (existing-id filenames, { 'owner/repo'.lower() -> tool_id }).

    ``existing_ids`` is the set of filename stems under ``data/tools``; it's
    used for the fast "does ``<suggested_id>.yml`` already exist?" check.

    The dict maps lowercased ``owner/repo`` to the tool's ``id``, populated
    from each tool's ``repository_url``. This drives the soft-match fallback.
    """
    existing_ids: set[str] = set()
    repo_to_id: dict[str, str] = {}

    if not TOOLS_DIR.exists():
        return existing_ids, repo_to_id

    for path in sorted(TOOLS_DIR.glob("*.yml")) + sorted(TOOLS_DIR.glob("*.yaml")):
        existing_ids.add(path.stem)
        try:
            with path.open() as fh:
                doc = yaml.safe_load(fh)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        tool_id = str(doc.get("id") or path.stem)
        url = doc.get("repository_url")
        if isinstance(url, str):
            m = re.match(
                r"https?://github\.com/([^/]+)/?([^/?#]*)",
                url.strip(),
                re.IGNORECASE,
            )
            if m:
                owner = m.group(1).lower()
                repo = m.group(2).removesuffix(".git").lower()
                if repo:
                    repo_to_id[f"{owner}/{repo}"] = tool_id
                else:
                    # Owner-only URL (e.g. github.com/SocketDev). Record so
                    # we can still match siblings under the same owner.
                    repo_to_id[f"{owner}/"] = tool_id
    return existing_ids, repo_to_id


def suggested_id(repo: str) -> str:
    """Kebab-case a repo name into a plausible tool id."""
    s = re.sub(r"[_\s]+", "-", repo)
    # Camel/Pascal → kebab: insert `-` between letter boundaries.
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "-", s)
    s = re.sub(r"[^A-Za-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s.lower()


def already_in_kg(
    owner: str,
    repo: str,
    sug_id: str,
    existing_ids: set[str],
    repo_to_id: dict[str, str],
) -> tuple[bool, str | None]:
    """Check filename match first, then soft-match by ``owner/repo``."""
    if sug_id in existing_ids:
        return True, sug_id
    key = f"{owner.lower()}/{repo.lower()}"
    if key in repo_to_id:
        return True, repo_to_id[key]
    # Owner-only registration (Socket-style): if we have a bare owner entry
    # AND the repo name looks like the tool id, treat as covered.
    owner_key = f"{owner.lower()}/"
    if owner_key in repo_to_id and repo_to_id[owner_key] == sug_id:
        return True, repo_to_id[owner_key]
    return False, None


# ---------------------------------------------------------------------------
# Core discovery
# ---------------------------------------------------------------------------


def discover(
    sources: list[str],
    *,
    since: dt.date | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Return (candidates, fetch_errors, per_source_counts).

    ``candidates`` is ranked by descending ``len(sources)`` then repo name.
    ``fetch_errors`` lists sources we couldn't read with a reason.
    """
    existing_ids, repo_to_id = load_kg_index()

    # (owner, repo) -> { 'sources': set[str], 'first_source': str }
    hits: dict[tuple[str, str], dict[str, Any]] = {}
    fetch_errors: list[dict[str, Any]] = []
    per_source_counts: dict[str, int] = {}

    if since is not None:
        # `since` is best-effort: we don't have per-source "last added"
        # signals from a raw README, so we just record it in the header of
        # the output. Leave behavior unchanged — future iterations could
        # diff against a cached prior run.
        pass

    for i, src in enumerate(sources):
        self_repo = canonical_source_repo(src)
        raw_url = _raw_readme_url(src)
        if raw_url is None:
            fetch_errors.append({"source": src, "error": "not a github.com URL"})
            per_source_counts[src] = 0
            continue

        if i > 0:
            time.sleep(REQUEST_DELAY)

        body, err = fetch_text(raw_url)
        if body is None:
            # One courteous retry with lowercase `main` if the HEAD redirect
            # failed (rare, but cheap).
            if err and "404" in err:
                retry = raw_url.replace("/HEAD/", "/main/")
                time.sleep(REQUEST_DELAY)
                body, err2 = fetch_text(retry)
                if body is None:
                    fetch_errors.append({"source": src, "error": err2 or err})
                    per_source_counts[src] = 0
                    continue
            else:
                fetch_errors.append({"source": src, "error": err or "unknown"})
                per_source_counts[src] = 0
                continue

        repos = extract_github_repos(body)
        if self_repo is not None:
            repos.discard(self_repo)

        per_source_counts[src] = len(repos)
        for owner, repo in repos:
            key = (owner, repo)
            bucket = hits.setdefault(key, {"sources": set(), "first_source": src})
            bucket["sources"].add(src)

    candidates: list[dict[str, Any]] = []
    for (owner, repo), info in hits.items():
        sug_id = suggested_id(repo)
        in_kg, matched = already_in_kg(owner, repo, sug_id, existing_ids, repo_to_id)
        candidates.append(
            {
                "owner": owner,
                "repo": repo,
                "full_name": f"{owner}/{repo}",
                "url": f"https://github.com/{owner}/{repo}",
                "suggested_id": sug_id,
                "already_in_kg": in_kg,
                "matched_tool_id": matched,
                "sources": sorted(info["sources"]),
                "source_count": len(info["sources"]),
                "ingest_command": (
                    f"python validator/ingest_github.py "
                    f"https://github.com/{owner}/{repo}"
                ),
            }
        )

    candidates.sort(key=lambda c: (-c["source_count"], c["full_name"].lower()))
    return candidates, fetch_errors, per_source_counts


# ---------------------------------------------------------------------------
# Stage 4 — composite quality gate (optional, kicks in when --enrichment
# JSON is supplied). See pipeline/discovery/quality_gate.py for the rules.
# ---------------------------------------------------------------------------


def apply_quality_gate(
    candidates: list[dict[str, Any]],
    enrichment: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Annotate candidates with a Stage-4 gate verdict + re-sort.

    ``enrichment`` is keyed by ``"owner/repo"`` (lowercase) and carries
    per-repo signals: ``stars``, ``pushed_at``, ``archived``,
    ``license_spdx``, etc. Candidates with no enrichment row stay in
    the queue but are tagged ``gate_decision: "unknown"`` — better to
    surface them with a warning than to drop them silently.

    Re-sort key after gating:
      1. Gate-PASS first (rescued from the long tail)
      2. Within PASS: stars desc, then source_count desc, then name
      3. Then UNKNOWN (no enrichment) — ordered by source_count desc
      4. Then FAIL — same secondary order

    The result is the same list of dicts, mutated with new keys, sorted.
    """
    from pipeline.discovery.quality_gate import (
        CandidateSignals,
        GateDecision,
        evaluate,
    )

    for cand in candidates:
        key = f"{cand['owner']}/{cand['repo']}".lower()
        enriched = enrichment.get(key)
        if not enriched:
            cand["gate_decision"] = "unknown"
            cand["gate_passed_criteria"] = []
            cand["gate_explanation"] = "No enrichment data available."
            cand["stars"] = None
            continue

        signals = CandidateSignals(
            stars=enriched.get("stars"),
            awesome_list_count=cand["source_count"],
            org=cand["owner"],
            archived=enriched.get("archived"),
        )
        result = evaluate(signals)
        cand["gate_decision"] = result.decision.value
        cand["gate_passed_criteria"] = result.passed_criteria
        cand["gate_explanation"] = result.explanation
        cand["stars"] = enriched.get("stars")
        cand["pushed_at"] = enriched.get("pushed_at")
        cand["archived"] = enriched.get("archived", False)
        cand["license_spdx"] = enriched.get("license_spdx")
        cand["language"] = enriched.get("language")

    def sort_key(c: dict[str, Any]) -> tuple[int, int, int, str]:
        bucket = {"pass": 0, "unknown": 1, "fail": 2}.get(c["gate_decision"], 3)
        # Negate stars / source_count so higher values sort first.
        stars = -(c.get("stars") or 0)
        sc = -c.get("source_count", 0)
        return (bucket, stars, sc, c["full_name"].lower())

    candidates.sort(key=sort_key)
    return candidates


def load_enrichment(path: Path) -> dict[str, dict[str, Any]]:
    """Load the enrichment JSON written by the long-tail enrichment
    runner. Keyed by ``"owner/repo"`` (lowercase) for fast lookup."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for row in raw.get("candidates", []):
        owner = (row.get("owner") or "").strip()
        repo = (row.get("repo") or "").strip()
        if owner and repo:
            out[f"{owner}/{repo}".lower()] = row
    return out


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def write_outputs(
    candidates: list[dict[str, Any]],
    fetch_errors: list[dict[str, Any]],
    per_source_counts: dict[str, int],
    sources: list[str],
    since: dt.date | None,
    out_dir: Path,
    today: dt.date,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"candidates_{today.strftime('%Y%m%d')}"
    md_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.json"

    new_count = sum(1 for c in candidates if not c["already_in_kg"])
    covered_count = sum(1 for c in candidates if c["already_in_kg"])

    lines: list[str] = []
    lines.append(f"# SAICA-KG candidate discovery — {today.isoformat()}")
    lines.append("")
    lines.append(
        f"Generated by `validator/discover_candidates.py` on " f"{today.isoformat()}."
    )
    if since is not None:
        lines.append(
            f"`--since {since.isoformat()}` was requested (best-effort; "
            f"top-level READMEs don't carry per-entry add dates)."
        )
    lines.append("")
    lines.append(
        f"**Summary**: {len(candidates)} candidates found, "
        f"{new_count} new (not in KG), {covered_count} already covered."
    )
    lines.append("")
    lines.append("## Sources scraped")
    lines.append("")
    for src in sources:
        count = per_source_counts.get(src)
        err = next((e for e in fetch_errors if e["source"] == src), None)
        if err is not None:
            lines.append(f"- `{src}` — FAILED: {err['error']}")
        else:
            lines.append(f"- `{src}` — {count} candidate link(s)")
    lines.append("")
    if fetch_errors:
        lines.append("## Fetch errors")
        lines.append("")
        for e in fetch_errors:
            lines.append(f"- `{e['source']}`: {e['error']}")
        lines.append("")
    lines.append("## Candidates")
    lines.append("")
    lines.append("| Repo | Sources | Already in KG? | Suggested id | Ingest command |")
    lines.append("|------|---------|----------------|--------------|----------------|")
    for c in candidates:
        if c["already_in_kg"]:
            covered = f"yes ({_md_escape(c['matched_tool_id'] or '')})"
        else:
            covered = "no"
        repo_cell = f"[{_md_escape(c['full_name'])}]({c['url']})"
        lines.append(
            "| {repo} | {n} | {covered} | `{sid}` | `{cmd}` |".format(
                repo=repo_cell,
                n=c["source_count"],
                covered=covered,
                sid=_md_escape(c["suggested_id"]),
                cmd=_md_escape(c["ingest_command"]),
            )
        )
    lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "generated_at": today.isoformat(),
        "since": since.isoformat() if since else None,
        "sources": sources,
        "per_source_counts": per_source_counts,
        "fetch_errors": fetch_errors,
        "summary": {
            "total": len(candidates),
            "new": new_count,
            "already_covered": covered_count,
        },
        "candidates": candidates,
    }
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_since(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--since expects YYYY-MM-DD: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Discover candidate tools from curated awesome-* lists."
    )
    ap.add_argument(
        "--sources",
        help=(
            "Path to a file with one source URL per line "
            "(defaults to the hardcoded list)."
        ),
    )
    ap.add_argument(
        "--since",
        type=_parse_since,
        help=(
            "Best-effort: only report tools added to sources since this "
            "ISO date. README-level signals are weak, so treat as advisory."
        ),
    )
    ap.add_argument(
        "--out-dir",
        default=str(RESEARCH_DIR),
        help="Output directory (default: research/).",
    )
    ap.add_argument(
        "--enrichment",
        type=Path,
        default=None,
        help=(
            "Path to a per-candidate enrichment JSON (stars, pushed_at, "
            "archived, license_spdx — produced by the long-tail enrichment "
            "agent). When supplied, applies the Stage 4 composite quality "
            "gate (pipeline.discovery.quality_gate) and re-sorts the "
            "candidates so gate-PASS rows surface first."
        ),
    )
    args = ap.parse_args(argv)

    if args.sources:
        src_path = Path(args.sources)
        if not src_path.exists():
            print(f"--sources file not found: {src_path}", file=sys.stderr)
            return 2
        sources = [
            ln.strip()
            for ln in src_path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    else:
        sources = list(DEFAULT_SOURCES)

    if not sources:
        print("No sources to scrape.", file=sys.stderr)
        return 2

    today = dt.date.today()
    candidates, fetch_errors, per_source_counts = discover(sources, since=args.since)

    if args.enrichment is not None:
        if not args.enrichment.exists():
            print(f"--enrichment file not found: {args.enrichment}", file=sys.stderr)
            return 2
        enrichment = load_enrichment(args.enrichment)
        candidates = apply_quality_gate(candidates, enrichment)
        n_pass = sum(1 for c in candidates if c.get("gate_decision") == "pass")
        n_fail = sum(1 for c in candidates if c.get("gate_decision") == "fail")
        n_unk = sum(1 for c in candidates if c.get("gate_decision") == "unknown")
        print(
            f"Quality gate: {n_pass} PASS, {n_fail} FAIL, "
            f"{n_unk} UNKNOWN (no enrichment row)."
        )

    md_path, json_path = write_outputs(
        candidates,
        fetch_errors,
        per_source_counts,
        sources,
        args.since,
        Path(args.out_dir),
        today,
    )

    new_count = sum(1 for c in candidates if not c["already_in_kg"])
    covered_count = sum(1 for c in candidates if c["already_in_kg"])
    print(
        f"{len(candidates)} candidates found, "
        f"{new_count} new (not in KG), "
        f"{covered_count} already covered."
    )
    print(f"Wrote: {md_path}")
    print(f"Wrote: {json_path}")
    if fetch_errors:
        print(f"Fetch errors: {len(fetch_errors)}")
        for e in fetch_errors:
            print(f"  - {e['source']}: {e['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
