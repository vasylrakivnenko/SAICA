"""Top-level orchestrator: ``audit_repo(url) -> AuditReport``.

Pipeline:
  1. Validate URL (https://github.com/<owner>/<repo>, no /tree/, no /blob/).
  2. Fetch — shallow ``git clone --depth=1 --filter=blob:limit=100k`` into
     a temp dir; fall back to GitHub REST API tree-listing + per-file
     fetches when ``git`` isn't on PATH (or the local path is supplied via
     the ``local_path`` shortcut for tests).
  3. Detect stack: languages, runtime hints, CI, package managers, agents,
     supervision tools.
  4. Build coverage grid (FM × paradigm × tier).
  5. Compute gaps and KG-backed recommendations.
  6. Render Markdown.
  7. Return :class:`AuditReport`.

The ``audit_repo_local(path)`` helper is exposed for tests so we can audit
a local working copy without going through git.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

import requests

from pipeline.audit.coverage import build_coverage_grid, find_gaps
from pipeline.audit.detectors import (
    detect_agents,
    detect_ci_providers,
    detect_languages,
    detect_package_managers,
    detect_runtime_hints,
    detect_supervision_tools,
)
from pipeline.audit.kg import load_tool_index
from pipeline.audit.render import to_markdown
from pipeline.audit.schemas import (
    AuditReport,
    CoverageGrid,
    DetectedStack,
    DetectedTool,
    GapItem,
)

log = logging.getLogger(__name__)

GITHUB_URL_RE = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


# ---------------------------------------------------------------------------
# URL parsing + validation
# ---------------------------------------------------------------------------


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    """Validate ``repo_url`` and return ``(owner, repo)`` tuple.

    Raises ``ValueError`` for any URL that isn't ``https://github.com/<o>/<r>``
    (no ``/tree/``, no ``/blob/``, no fragments).
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
# Fetch
# ---------------------------------------------------------------------------

# Marker files we care about for the API-fallback fetch path.
_MARKER_FILES: tuple[str, ...] = (
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "setup.py",
    "setup.cfg",
    "package.json",
    "tsconfig.json",
    "go.mod",
    "Cargo.toml",
    "Gemfile",
    "composer.json",
    "Dockerfile",
    "docker-compose.yml",
    "Makefile",
    ".pre-commit-config.yaml",
    ".pre-commit-config.yml",
    ".github/dependabot.yml",
    ".github/dependabot.yaml",
    "renovate.json",
    ".github/renovate.json",
    ".renovaterc",
    "CLAUDE.md",
    ".cursorrules",
    ".windsurfrules",
    ".cursorignore",
    "promptfooconfig.yaml",
    "promptfooconfig.yml",
    "promptfooconfig.json",
    "deepeval.yaml",
    "deepeval.yml",
    "judgeval.yaml",
    "lm-eval-config.yaml",
)
_MARKER_DIRS: tuple[str, ...] = (
    ".github/workflows",
    ".claude",
    ".cursor",
    ".windsurf",
    ".zed",
    ".github/copilot",
    ".continue",
    ".sourcegraph",
    ".cody",
    ".codeium",
    "judgeval",
    ".deepeval",
)


def _git_shallow_clone(repo_url: str, dest: Path, timeout: float = 60.0) -> None:
    cmd = [
        "git",
        "clone",
        "--depth=1",
        "--filter=blob:limit=100k",
        "--quiet",
        repo_url,
        str(dest),
    ]
    log.info("git clone: %s", " ".join(cmd))
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"git clone failed (rc={res.returncode}): {res.stderr.strip()}"
        )


def _api_fetch(owner: str, repo: str, dest: Path, timeout: float = 30.0) -> None:
    """Fallback fetch via GitHub REST API — pulls only the marker files we use.

    Anonymous, so subject to 60 req/hr rate limit.  We deliberately fetch
    only ~30 files in the worst case.
    """
    headers = {"Accept": "application/vnd.github+json"}
    # Discover default branch.
    r = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers=headers,
        timeout=timeout,
    )
    r.raise_for_status()
    branch = r.json().get("default_branch") or "main"

    # Fetch flat tree to discover what's actually present (one request).
    tree_r = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        headers=headers,
        timeout=timeout,
    )
    tree_r.raise_for_status()
    tree = tree_r.json().get("tree") or []
    present_paths = {item.get("path") for item in tree if item.get("type") == "blob"}
    present_dirs = {item.get("path") for item in tree if item.get("type") == "tree"}

    targets: set[str] = set()
    for marker in _MARKER_FILES:
        if marker in present_paths:
            targets.add(marker)
    # For directories, fetch any blobs whose path starts with the dir.
    for d in _MARKER_DIRS:
        if d in present_dirs:
            for p in present_paths:
                if p and p.startswith(d + "/"):
                    targets.add(p)
    # Always grab every workflow file.
    for p in present_paths:
        if p and p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml")):
            targets.add(p)

    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"
    for p in sorted(targets):
        out_path = dest / p
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            rr = requests.get(raw_base + p, timeout=timeout)
            if rr.status_code == 200:
                out_path.write_bytes(rr.content)
        except requests.RequestException as exc:  # pragma: no cover - network flakiness
            log.warning("api-fallback fetch failed for %s: %s", p, exc)


def _fetch_repo(repo_url: str, dest: Path) -> None:
    """Populate ``dest`` with the audited repo's files. Tries git first."""
    if shutil.which("git"):
        try:
            _git_shallow_clone(repo_url, dest)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("git clone failed (%s); falling back to API", exc)
    owner, repo = parse_repo_url(repo_url)
    _api_fetch(owner, repo, dest)


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


def _build_summary(
    repo_url: str,
    stack: DetectedStack,
    coverage: CoverageGrid,
    gaps: list[GapItem],
) -> str:
    n_tools = len(stack.supervision_tools)
    n_covered = len(coverage.failure_modes_covered)
    n_missing = len(coverage.failure_modes_missing)
    high = sum(1 for g in gaps if g.severity == "high")
    medium = sum(1 for g in gaps if g.severity == "medium")
    repo_name = repo_url.rstrip("/").rsplit("/", 1)[-1]
    agent_phrase = ""
    if stack.agents:
        names = ", ".join(a.name for a in stack.agents)
        agent_phrase = f" Coding agent(s) detected: {names}."

    if n_tools == 0:
        head = f"{repo_name} has no SAICA-KG-recognised supervision tools wired in."
    else:
        head = (
            f"{repo_name} has {n_tools} SAICA-KG-recognised supervision tool"
            f"{'s' if n_tools != 1 else ''} covering {n_covered} of "
            f"{n_covered + n_missing} failure modes."
        )
    gap_phrase = (
        f" {high} high-severity and {medium} medium-severity gap"
        f"{'s' if (high + medium) != 1 else ''} identified."
    )
    return head + gap_phrase + agent_phrase


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------


def audit_repo_local(
    repo_path: str | Path, repo_url: Optional[str] = None
) -> AuditReport:
    """Audit an already-checked-out local copy of a repo.

    Useful for tests and for re-using a previously cloned tree.  ``repo_url``
    is the URL we report in the output; if omitted we synthesize a
    ``file://`` URL from the path.
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
    )
    report.markdown = to_markdown(report)
    return report


def audit_repo(repo_url: str) -> AuditReport:
    """Audit a public GitHub repo by URL. Performs a shallow clone + analysis."""
    parse_repo_url(repo_url)  # validate; raises ValueError on bad input

    with tempfile.TemporaryDirectory(prefix="saica-audit-") as tmp:
        dest = Path(tmp) / "repo"
        try:
            _fetch_repo(repo_url, dest)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Could not fetch {repo_url}: {exc}. "
                "Confirm the URL is a public GitHub repo and that git or network "
                "access is available."
            ) from exc

        if not dest.exists() or not any(dest.iterdir()):
            raise RuntimeError(
                f"Fetched {repo_url} but the working tree is empty. "
                "If this is a private repo, /assess does not support OAuth in this MVP."
            )

        return audit_repo_local(dest, repo_url=repo_url)


__all__ = [
    "audit_repo",
    "audit_repo_local",
    "parse_repo_url",
]
