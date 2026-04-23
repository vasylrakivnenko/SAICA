#!/usr/bin/env python3
"""Refresh GitHub stargazer counts on Tool YAMLs.

Walks every ``data/tools/*.yml`` and, for tools whose ``repository_url`` points
at ``github.com/<owner>/<repo>``, calls the GitHub REST API and writes
``stars`` and ``stars_updated_at`` back into the YAML. The script is designed
to be safe to run repeatedly and to exit 0 even if some fetches fail — it
only prints a summary of what worked and what didn't.

Usage::

    python validator/fetch_github_stars.py

If ``GITHUB_TOKEN`` is set, it's sent as a Bearer token (5000 req/hour).
Otherwise the script uses the 60 req/hour unauthenticated quota, which is
plenty for the current tool catalog.

YAML round-trip: prefers ``ruamel.yaml`` to preserve formatting, falls back
to ``pyyaml`` (which is lossy for comments/ordering) if ruamel isn't
installed.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("Missing dependency: requests. Install with: pip install requests", file=sys.stderr)
    sys.exit(2)

# Prefer ruamel.yaml for round-trip; fall back to pyyaml.
_USE_RUAMEL = False
try:
    from ruamel.yaml import YAML  # type: ignore

    _USE_RUAMEL = True
except ImportError:
    try:
        import yaml  # type: ignore
    except ImportError:
        print(
            "Missing dependency: install ruamel.yaml (preferred) or pyyaml.",
            file=sys.stderr,
        )
        sys.exit(2)


REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "data" / "tools"

GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+)(?:[/?#].*)?$",
    re.IGNORECASE,
)


@dataclass
class FetchResult:
    tool_id: str
    repo: str | None
    stars: int | None
    error: str | None = None


# ---------------------------------------------------------------------------
# YAML round-trip helpers
# ---------------------------------------------------------------------------


def _represent_none(self: Any, data: Any) -> Any:  # pragma: no cover - ruamel hook
    # Represent Python None as the literal string "null" so that YAMLs that
    # had an explicit `null` value keep it on write-back instead of being
    # collapsed to an empty scalar.
    return self.represent_scalar("tag:yaml.org,2002:null", "null")


def _make_yaml() -> Any:
    if _USE_RUAMEL:
        y = YAML()
        y.preserve_quotes = True
        # Keep the block style users wrote; don't re-flow.
        y.width = 4096
        y.indent(mapping=2, sequence=4, offset=2)
        y.representer.add_representer(type(None), _represent_none)
        return y
    return None


def load_yaml(path: Path) -> dict[str, Any]:
    if _USE_RUAMEL:
        y = _make_yaml()
        with path.open() as fh:
            return y.load(fh)
    with path.open() as fh:
        return yaml.safe_load(fh)  # type: ignore[name-defined]


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    if _USE_RUAMEL:
        y = _make_yaml()
        with path.open("w") as fh:
            y.dump(data, fh)
        return
    with path.open("w") as fh:
        yaml.safe_dump(  # type: ignore[name-defined]
            data, fh, sort_keys=False, allow_unicode=True, default_flow_style=False
        )


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------


def parse_github_repo(url: str | None) -> tuple[str, str] | None:
    if not url or not isinstance(url, str):
        return None
    m = GITHUB_URL_RE.match(url.strip())
    if not m:
        return None
    owner = m.group("owner")
    repo = m.group("repo").removesuffix(".git")
    return owner, repo


def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "saica-kg-stars-refresh/1.0",
        }
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def fetch_stars(session: requests.Session, owner: str, repo: str) -> tuple[int | None, str | None]:
    """Return (stars, error). One retry on 403 (rate limit) with backoff."""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    for attempt in (1, 2):
        try:
            r = session.get(url, timeout=15)
        except requests.RequestException as exc:
            return None, f"network error: {exc}"
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                return None, "non-JSON response"
            stars = data.get("stargazers_count")
            if isinstance(stars, int):
                return stars, None
            return None, "missing stargazers_count in response"
        if r.status_code == 403 and attempt == 1:
            # Could be secondary rate limit; back off and retry once.
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
            print(f"  rate-limited by GitHub; sleeping {delay:.0f}s then retrying…")
            time.sleep(delay)
            continue
        if r.status_code == 404:
            return None, "404 not found"
        return None, f"HTTP {r.status_code}"
    return None, "rate-limited (gave up after retry)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    if not TOOLS_DIR.exists():
        print(f"No tools directory at {TOOLS_DIR}", file=sys.stderr)
        return 2

    paths = sorted(TOOLS_DIR.glob("*.yml")) + sorted(TOOLS_DIR.glob("*.yaml"))
    if not paths:
        print("No tool YAMLs to process.")
        return 0

    session = build_session()
    today = dt.date.today().isoformat()
    results: list[FetchResult] = []
    skipped_no_repo: list[str] = []
    failures: list[FetchResult] = []

    for path in paths:
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            print(f"  skipping {path.name}: top-level is not a mapping")
            continue
        tool_id = str(doc.get("id") or path.stem)
        repo_url = doc.get("repository_url")
        parsed = parse_github_repo(str(repo_url) if repo_url else None)
        if not parsed:
            print(f"[skip] {tool_id}: no GitHub repository_url")
            skipped_no_repo.append(tool_id)
            results.append(FetchResult(tool_id, None, None, "no github repo"))
            continue
        owner, repo = parsed
        repo_label = f"{owner}/{repo}"
        print(f"[fetch] {tool_id} -> {repo_label}")
        stars, err = fetch_stars(session, owner, repo)
        if stars is None:
            print(f"  failed: {err}")
            res = FetchResult(tool_id, repo_label, None, err)
            results.append(res)
            failures.append(res)
            continue
        print(f"  {stars:,} stars")
        doc["stars"] = int(stars)
        doc["stars_updated_at"] = today
        try:
            dump_yaml(path, doc)
        except Exception as exc:  # noqa: BLE001
            print(f"  failed to write {path.name}: {exc}")
            res = FetchResult(tool_id, repo_label, stars, f"write error: {exc}")
            results.append(res)
            failures.append(res)
            continue
        results.append(FetchResult(tool_id, repo_label, stars))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n=== Summary ===")
    header = f"{'tool_id':<22}  {'repo':<40}  stars"
    print(header)
    print("-" * len(header))
    for r in results:
        repo = r.repo or "—"
        if r.stars is not None:
            stars_s = f"{r.stars:,}"
        elif r.error:
            stars_s = f"(skipped: {r.error})"
        else:
            stars_s = "—"
        print(f"{r.tool_id:<22}  {repo:<40}  {stars_s}")

    total = len(results)
    ok = sum(1 for r in results if r.stars is not None)
    print(f"\n{ok}/{total} tools updated")
    if skipped_no_repo:
        print(f"No GitHub repo (expected for proprietary tools): {', '.join(skipped_no_repo)}")
    if failures:
        print("Failures:")
        for r in failures:
            print(f"  - {r.tool_id} ({r.repo}): {r.error}")

    # Exit 0 even if some fetches failed — this is a soft-refresh tool.
    return 0


if __name__ == "__main__":
    sys.exit(main())
