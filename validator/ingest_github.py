#!/usr/bin/env python3
"""Draft Tool YAML stubs from GitHub repository metadata.

Given one or more GitHub repo URLs, this CLI fetches metadata via the
GitHub REST API and writes a Tool YAML stub under ``data/tools/<id>.yml``
with as much real data pre-filled as possible. Facet classifications
(control_paradigm, temporal_phase, autonomy_level, addresses_failure_modes,
locus_of_control, implements_techniques, inclusion_rationale) are left as
``# TODO:`` comments for a human reviewer to fill in.

Usage::

    python validator/ingest_github.py <github-url> [<github-url> ...]
    python validator/ingest_github.py --from-file urls.txt
    python validator/ingest_github.py --dry-run <url>

Auth: if ``GITHUB_TOKEN`` is set, it's sent as a Bearer token (5000
req/hour), otherwise unauth 60 req/hour. Between calls the script sleeps
1.2s; on a 403 (rate-limited) it retries once with backoff.

The script does NOT overwrite existing Tool YAML files; if
``data/tools/<id>.yml`` already exists, the URL is skipped with a warning.
Exits 0 even if some URLs fail — failures are surfaced in the summary
table at the end.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print(
        "Missing dependency: requests. Install with: pip install requests",
        file=sys.stderr,
    )
    sys.exit(2)

try:
    from ruamel.yaml import YAML  # type: ignore
    from ruamel.yaml.comments import CommentedMap  # type: ignore
except ImportError:
    print(
        "Missing dependency: ruamel.yaml. Install with: pip install ruamel.yaml",
        file=sys.stderr,
    )
    sys.exit(2)


REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "data" / "tools"

GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+)(?:[/?#].*)?$",
    re.IGNORECASE,
)

API_ROOT = "https://api.github.com"
USER_AGENT = "saica-kg-ingest/0.1"
REQUEST_SLEEP = 1.2  # seconds between API calls


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RepoMeta:
    owner: str
    repo: str
    html_url: str
    name: str
    description: str | None
    homepage: str | None
    stars: int
    forks: int
    spdx: str | None
    created_at: str | None
    pushed_at: str | None
    archived: bool
    disabled: bool
    topics: list[str] = field(default_factory=list)
    default_branch: str | None = None
    readme: str | None = None


@dataclass
class IngestResult:
    url: str
    tool_id: str | None
    stars: int | None
    first_released: str | None
    license: str | None
    status: str  # "created" | "skipped" | "failed" | "dry-run"
    reason: str | None = None


# ---------------------------------------------------------------------------
# URL / slug helpers
# ---------------------------------------------------------------------------


def parse_github_url(url: str) -> tuple[str, str] | None:
    if not url or not isinstance(url, str):
        return None
    m = GITHUB_URL_RE.match(url.strip())
    if not m:
        return None
    owner = m.group("owner")
    repo = m.group("repo").removesuffix(".git")
    return owner, repo


def kebab(s: str) -> str:
    """Lowercased, non-alphanumerics collapsed to a single hyphen."""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def first_sentence(text: str, max_len: int = 140) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    # Split on first period/!/? followed by whitespace or end-of-string.
    m = re.search(r"[^.!?]+[.!?](?=\s|$)", text)
    sentence = m.group(0).strip() if m else text
    if len(sentence) > max_len:
        sentence = sentence[: max_len - 1].rstrip() + "…"
    return sentence


def first_paragraph(text: str) -> str:
    """Return the first non-empty paragraph from README-style prose.

    Strips Markdown headings, badges/images, and HTML comments so we don't
    drag header salad into the description.
    """
    if not text:
        return ""
    # Strip HTML comments and blocks we never want in descriptions.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)  # strip raw HTML tags
    # Drop linked images (badges wrapped in a link): [![alt](img)](url)
    text = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", "", text)
    # Drop bare markdown images (badges, logos).
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # Turn [text](url) into text; drop empty-text links entirely.
    text = re.sub(r"\[\s*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)

    lines = text.splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if cleaned:
                break
            continue
        if stripped.startswith("#"):
            continue
        if set(stripped) <= set("-=*"):
            continue
        # Reject lines that are still mostly link/badge residue.
        alpha = sum(ch.isalpha() for ch in stripped)
        if alpha < 10:
            continue
        cleaned.append(stripped)
    paragraph = " ".join(cleaned)
    # Strip remaining markdown emphasis markers.
    paragraph = re.sub(r"[*_`]+", "", paragraph)
    # Collapse whitespace.
    paragraph = re.sub(r"\s+", " ", paragraph)
    return paragraph.strip()


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------


def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            # mercy-preview unlocks `topics`; the newer Accept also returns them
            # but we're explicit to be safe on older API surfaces.
            "Accept": "application/vnd.github.mercy-preview+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def _get_with_retry(
    session: requests.Session, url: str, accept: str | None = None
) -> tuple[int, Any | None, str | None]:
    """GET with one retry on 403. Returns (status, json_or_text, error)."""
    headers: dict[str, str] = {}
    if accept:
        headers["Accept"] = accept
    for attempt in (1, 2):
        try:
            r = session.get(url, headers=headers or None, timeout=20)
        except requests.RequestException as exc:
            return 0, None, f"network error: {exc}"
        if r.status_code == 200:
            try:
                return 200, r.json(), None
            except ValueError:
                return 200, r.text, None
        if r.status_code == 403 and attempt == 1:
            reset = r.headers.get("X-RateLimit-Reset")
            retry_after = r.headers.get("Retry-After")
            delay = 30.0
            if retry_after:
                try:
                    delay = min(60.0, max(1.0, float(retry_after)))
                except ValueError:
                    pass
            elif reset:
                try:
                    delay = min(60.0, max(1.0, float(reset) - time.time()))
                except ValueError:
                    pass
            print(
                f"  rate-limited (403); sleeping {delay:.0f}s before retry…",
                file=sys.stderr,
            )
            time.sleep(delay)
            continue
        if r.status_code == 404:
            return 404, None, "404 not found"
        return r.status_code, None, f"HTTP {r.status_code}"
    return 403, None, "rate-limited (retry exhausted)"


def fetch_repo(
    session: requests.Session, owner: str, repo: str
) -> tuple[RepoMeta | None, str | None]:
    status, data, err = _get_with_retry(session, f"{API_ROOT}/repos/{owner}/{repo}")
    if err or not isinstance(data, dict):
        return None, err or "malformed response"

    license_obj = data.get("license") or {}
    spdx = license_obj.get("spdx_id") if isinstance(license_obj, dict) else None
    # Normalize GitHub's "NOASSERTION" vs missing license.
    if spdx in (None, "", "NOASSERTION"):
        spdx = None

    topics = data.get("topics")
    if not isinstance(topics, list):
        topics = []

    meta = RepoMeta(
        owner=str(data.get("owner", {}).get("login") or owner),
        repo=str(data.get("name") or repo),
        html_url=str(data.get("html_url") or f"https://github.com/{owner}/{repo}"),
        name=str(data.get("name") or repo),
        description=(data.get("description") or None),
        homepage=(data.get("homepage") or None),
        stars=int(data.get("stargazers_count") or 0),
        forks=int(data.get("forks_count") or 0),
        spdx=spdx,
        created_at=data.get("created_at"),
        pushed_at=data.get("pushed_at"),
        archived=bool(data.get("archived")),
        disabled=bool(data.get("disabled")),
        topics=[str(t) for t in topics],
        default_branch=data.get("default_branch"),
    )

    # README (optional, non-fatal)
    time.sleep(REQUEST_SLEEP)
    _, readme_data, _ = _get_with_retry(
        session, f"{API_ROOT}/repos/{owner}/{repo}/readme"
    )
    if isinstance(readme_data, dict):
        content = readme_data.get("content")
        encoding = readme_data.get("encoding", "base64")
        if isinstance(content, str) and encoding == "base64":
            try:
                meta.readme = base64.b64decode(content).decode(
                    "utf-8", errors="replace"
                )
            except Exception:
                meta.readme = None

    return meta, None


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


def parse_iso_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        # GitHub returns ISO-8601 with Z; fromisoformat tolerates offset on 3.11+.
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return dt.datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def maturity_status(meta: RepoMeta, today: dt.date) -> str:
    """Heuristic per project spec.

    Order matters: abandoned > at_risk > stable > experimental (default).
    """
    if meta.archived or meta.disabled:
        return "abandoned"
    pushed = parse_iso_date(meta.pushed_at)
    created = parse_iso_date(meta.created_at)
    if pushed is not None and (today - pushed).days > 365:
        return "at_risk"
    if meta.stars >= 5000 and pushed is not None and (today - pushed).days <= 180:
        return "stable"
    if created is not None and (today - created).days <= 365:
        return "experimental"
    # Fallback — neither clearly stable, experimental, nor at risk.
    return "experimental"


def derive_name(meta: RepoMeta) -> str:
    """Prefer a parenthetical project name from the description, else repo name.

    Examples:
      "LLM framework (LlamaIndex) for ..." -> "LlamaIndex"
      "Aider is AI pair programming in your terminal" -> "aider"
    """
    desc = meta.description or ""
    m = re.search(r"\(([A-Za-z][\w\-. ]{1,40})\)", desc)
    if m:
        return m.group(1).strip()
    return meta.name


def derive_tagline(meta: RepoMeta) -> str:
    desc = (meta.description or "").strip()
    if desc:
        return first_sentence(desc, 140)
    return ""


def derive_description(meta: RepoMeta) -> str:
    """Compose a short description: repo description + README first-paragraph sentence if short."""
    desc = (meta.description or "").strip()
    if desc and not desc.endswith((".", "!", "?")):
        desc = desc + "."
    if len(desc) >= 200 or not meta.readme:
        return desc or (
            first_sentence(first_paragraph(meta.readme or ""), 400) or meta.name
        )
    para = first_paragraph(meta.readme)
    extra = first_sentence(para, 400) if para else ""
    if not extra:
        return desc or meta.name
    # Avoid duplicating the description if README repeats it.
    if extra.lower().startswith(desc.lower().rstrip(".")[:40].lower()) and desc:
        return desc
    combined = (desc + " " + extra).strip() if desc else extra
    if len(combined) > 800:
        combined = combined[:797].rstrip() + "…"
    return combined


# ---------------------------------------------------------------------------
# YAML composition
# ---------------------------------------------------------------------------


def _make_yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def compose_stub(
    meta: RepoMeta, source_url: str, today: dt.date
) -> tuple[str, CommentedMap]:
    tool_id = kebab(meta.repo)
    name = derive_name(meta)
    tagline = derive_tagline(meta)
    description = derive_description(meta)
    first_released = (parse_iso_date(meta.created_at) or today).isoformat()
    last_updated = (parse_iso_date(meta.pushed_at) or today).isoformat()
    status = maturity_status(meta, today)
    license_id = meta.spdx or "NOASSERTION"
    published_by = kebab(meta.owner)

    doc: CommentedMap = CommentedMap()
    doc["id"] = tool_id
    doc["name"] = name
    if tagline:
        doc["tagline"] = tagline
    doc["description"] = description

    doc["first_released"] = first_released
    doc["last_updated"] = last_updated
    doc["maturity_status"] = status

    doc["published_by"] = published_by
    doc["repository_url"] = meta.html_url
    doc["documentation_url"] = meta.homepage or None
    doc["license"] = license_id

    # --- Facet fields: left blank with TODO comments for human review -----
    # We set sentinel values that are obviously placeholders. ruamel.yaml will
    # emit these as scalar strings so a reviewer notices them instantly; the
    # validator will also reject them, which is the intended tripwire.
    doc["control_paradigm"] = "TODO"
    doc.yaml_add_eol_comment(
        "TODO: one of prevention|detection|correction|recovery", "control_paradigm"
    )
    doc["temporal_phase"] = "TODO"
    doc.yaml_add_eol_comment(
        "TODO: one of pre_generation|in_generation|post_generation", "temporal_phase"
    )
    doc["autonomy_level"] = "TODO"
    doc.yaml_add_eol_comment(
        "TODO: one of fully_autonomous|graduated_hitl|full_hitl", "autonomy_level"
    )

    doc["addresses_failure_modes"] = []
    doc.yaml_add_eol_comment(
        "TODO: from fabrication|obsolescence|dependency_blindness|logic_error|"
        "security_vulnerability|scope_creep|context_pollution|supply_chain_attack",
        "addresses_failure_modes",
    )
    doc["locus_of_control"] = []
    doc.yaml_add_eol_comment(
        "TODO: subset of model|prompt|context|environment|human", "locus_of_control"
    )
    doc["implements_techniques"] = []
    doc.yaml_add_eol_comment(
        "TODO: free-form technique slugs (kebab-case)", "implements_techniques"
    )

    doc["stars"] = int(meta.stars)
    doc["stars_updated_at"] = today.isoformat()

    doc["inclusion_rationale"] = (
        "TODO: explain the MECE cell this tool occupies and why it merits inclusion."
    )

    # --- Top-of-file comment block -----------------------------------------
    header = (
        f" Auto-generated Tool YAML stub — SAICA-KG ingest_github.py\n"
        f" Ingested: {today.isoformat()}\n"
        f" Source:   {source_url}\n"
        f" REVIEW REQUIRED: fill TODO facet fields before merging.\n"
        f" Heuristic maturity_status='{status}' computed from stars/pushed_at/archived — verify.\n"
    )
    doc.yaml_set_start_comment(header)

    return tool_id, doc


def serialize(doc: CommentedMap) -> str:
    y = _make_yaml()
    buf = io.StringIO()
    y.dump(doc, buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def load_urls_from_file(path: Path) -> list[str]:
    urls: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def process_url(
    session: requests.Session,
    url: str,
    today: dt.date,
    *,
    dry_run: bool,
) -> IngestResult:
    parsed = parse_github_url(url)
    if not parsed:
        return IngestResult(url, None, None, None, None, "failed", "unparseable URL")
    owner, repo = parsed
    print(f"[fetch] {owner}/{repo}")
    meta, err = fetch_repo(session, owner, repo)
    if meta is None:
        return IngestResult(
            url, None, None, None, None, "failed", err or "fetch failed"
        )

    tool_id, doc = compose_stub(meta, url, today)
    target = TOOLS_DIR / f"{tool_id}.yml"

    if dry_run:
        text = serialize(doc)
        print(f"--- {target} (dry-run) ---")
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        print(f"--- end {tool_id} ---")
        return IngestResult(
            url,
            tool_id,
            meta.stars,
            parse_iso_date(meta.created_at).isoformat() if meta.created_at else None,
            meta.spdx or "NOASSERTION",
            "dry-run",
        )

    if target.exists():
        print(f"  skipping: {target.name} already exists")
        return IngestResult(
            url,
            tool_id,
            meta.stars,
            parse_iso_date(meta.created_at).isoformat() if meta.created_at else None,
            meta.spdx or "NOASSERTION",
            "skipped",
            "file exists",
        )

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("w") as fh:
            _make_yaml().dump(doc, fh)
    except Exception as exc:  # noqa: BLE001
        return IngestResult(
            url,
            tool_id,
            meta.stars,
            None,
            meta.spdx or "NOASSERTION",
            "failed",
            f"write error: {exc}",
        )
    print(f"  wrote {target}")
    return IngestResult(
        url,
        tool_id,
        meta.stars,
        parse_iso_date(meta.created_at).isoformat() if meta.created_at else None,
        meta.spdx or "NOASSERTION",
        "created",
    )


def print_summary(results: list[IngestResult]) -> None:
    if not results:
        return
    print("\n=== Summary ===")
    header = f"{'url':<55}  {'id':<24}  {'stars':>7}  {'first_rel':<10}  {'license':<14}  status"
    print(header)
    print("-" * len(header))
    for r in results:
        url_s = (r.url[:52] + "…") if len(r.url) > 53 else r.url
        tid = r.tool_id or "—"
        stars = f"{r.stars:,}" if r.stars is not None else "—"
        first = r.first_released or "—"
        lic = r.license or "—"
        extra = (
            f" ({r.reason})" if r.reason and r.status in ("skipped", "failed") else ""
        )
        print(
            f"{url_s:<55}  {tid:<24}  {stars:>7}  {first:<10}  {lic:<14}  {r.status}{extra}"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ingest_github.py",
        description="Draft Tool YAML stubs from GitHub repository metadata.",
    )
    ap.add_argument("urls", nargs="*", help="GitHub repository URLs.")
    ap.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help="Read newline-separated URLs from a file (# comments ignored).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated YAML to stdout; do not write files.",
    )
    args = ap.parse_args(argv)

    urls: list[str] = list(args.urls)
    if args.from_file:
        if not args.from_file.exists():
            print(f"--from-file path does not exist: {args.from_file}", file=sys.stderr)
            return 2
        urls.extend(load_urls_from_file(args.from_file))

    if not urls:
        ap.print_usage()
        print(
            "error: need at least one URL (positional or via --from-file).",
            file=sys.stderr,
        )
        return 2

    session = build_session()
    today = dt.date.today()
    results: list[IngestResult] = []

    for i, url in enumerate(urls):
        if i > 0:
            time.sleep(REQUEST_SLEEP)
        try:
            results.append(process_url(session, url, today, dry_run=args.dry_run))
        except Exception as exc:  # noqa: BLE001
            print(f"  unexpected error for {url}: {exc}", file=sys.stderr)
            results.append(
                IngestResult(url, None, None, None, None, "failed", str(exc))
            )

    print_summary(results)
    # Always exit 0 — partial success is acceptable; the summary is the truth.
    return 0


if __name__ == "__main__":
    sys.exit(main())
