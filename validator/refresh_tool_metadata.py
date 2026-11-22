#!/usr/bin/env python3
"""Refresh what each tool record says about its upstream repository from the
GitHub API.

For every ``data/tools/*.yml`` whose ``repository_url`` is a GitHub
repository (``github.com/<owner>/<repo>``) the script asks
``api.github.com/repos/<owner>/<repo>`` once and writes:

===================== ====================================================
``stars``             ``stargazers_count``
``stars_updated_at``  the day of the check
``upstream_pushed_at`` date of ``pushed_at``
``last_reviewed``     the day of the check
``last_updated``      same date as ``upstream_pushed_at``. Legacy field,
                      kept while other code still reads it (see below).
``archived``          ``true`` when the repository is archived; the key is
                      removed when it is not
``repository_url``    the new address when the repository was renamed or
                      moved (GitHub redirects the old one)
``license``           only for ids named with ``--accept-license``: the
                      SPDX id GitHub detects. Otherwise a difference is
                      reported and left, because the detector reads one
                      file: ``microsoft/autogen`` is reported as CC-BY-4.0
                      (its documentation licence) while the code is MIT.
``maturity_status``   see "Status rules"
===================== ====================================================

``last_updated`` used to mean two things: the upstream push date on most
records and the date of an editor's change on others. It is now split into
``upstream_pushed_at`` (what upstream did) and ``last_reviewed`` (when this
record was last compared with upstream). ``last_updated`` stays as a copy of
``upstream_pushed_at`` until the site and the coverage report read the new
field; then it can be deleted.

Status rules (``maturity_status`` is otherwise an editor's judgement and
is never raised by this script):

* archived repository                      → ``deprecated``
* not archived, no push for more than 365
  days on the day of the check             → ``at_risk``
* a record that is ``deprecated`` or ``at_risk`` although upstream is
  active again is reported and left for an editor (the script cannot know
  whether it was ``stable`` or ``experimental``).

What the script never touches: failure-mode tags, facets, descriptions,
rationales, ``first_released`` and every other field. A moved or archived
repository is recorded, never deleted; write the story of the move in
``editorial_notes`` by hand.

A record without a GitHub repository (a product page, an organisation
page) is reported as "not checked" and left alone.

The file is edited as text (single lines only), so comments, key order and
wrapping stay as they are. After each edit the file is parsed again and
compared with the plan; a mismatch aborts before anything is saved.

Token: ``GITHUB_TOKEN`` from the environment, else from ``.env.local`` in
the repository root. It is sent to ``api.github.com`` only, never printed
and never written anywhere. Without a token GitHub allows 60 requests per
hour, which is enough for one run. When GitHub refuses the token (401) the
script says so and goes on without it. Requests carry a generic User-Agent.
Answers are kept in ``.cache/validator/tool_metadata.json`` (not tracked;
public repository fields only); ``--offline`` uses only that file and
``--refetch`` ignores it.

Usage::

    .venv/bin/python validator/refresh_tool_metadata.py            # dry run; exit 1 when a record differs
    .venv/bin/python validator/refresh_tool_metadata.py --write    # rewrite the files
    .venv/bin/python validator/refresh_tool_metadata.py --only daytona pr-agent
    .venv/bin/python validator/refresh_tool_metadata.py --as-of 2026-11-21 --report /tmp/tools.json

Run ``.venv/bin/python validator/cli.py`` afterwards.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "data" / "tools"
CACHE_PATH = REPO / ".cache" / "validator" / "tool_metadata.json"
ENV_PATH = REPO / ".env.local"

USER_AGENT = "kg-metadata-refresh/1.0 (repository status check)"
API_HOST = "api.github.com"
TIMEOUT_S = 30
PAUSE_S = 0.2
MAX_REDIRECTS = 3
STALE_AT_RISK_DAYS = 365  # same threshold as validator/cli.py

GITHUB_REPO_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
# SPDX answers that are not a licence id.
_NO_LICENSE_IDS = {"", "NOASSERTION", "NONE", "OTHER"}
_KEPT_FIELDS = (
    "full_name",
    "html_url",
    "archived",
    "disabled",
    "fork",
    "stargazers_count",
    "pushed_at",
    "created_at",
    "description",
    "homepage",
)


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


def read_token() -> str | None:
    """``GITHUB_TOKEN`` from the environment, else from ``.env.local``."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token.strip()
    try:
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        match = re.match(r"^\s*(?:export\s+)?GITHUB_TOKEN\s*=\s*(.*)$", line)
        if match:
            value = match.group(1).strip().strip("'\"")
            return value or None
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are followed by hand so the token never leaves the API host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: D102
        return None


def _api_get(url: str, token: str | None) -> tuple[int, dict[str, str], bytes]:
    """One GET to the GitHub API. Anything but https to the API host is
    refused before the request is made."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != API_HOST:
        raise ValueError(f"refusing to fetch {url!r}: not a GitHub API URL")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - host checked
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with opener.open(request, timeout=TIMEOUT_S) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def fetch_repo(owner: str, repo: str, token: str | None) -> dict[str, Any]:
    """Return the public fields of one repository, or ``{"error": …}``.

    A renamed or moved repository answers 301 with the new API address;
    the redirect is followed (on the API host only) and the answer carries
    ``redirected: true``."""
    url = f"https://{API_HOST}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"
    redirected = False
    for _ in range(MAX_REDIRECTS + 1):
        try:
            status, headers, body = _api_get(url, token)
        except (OSError, ValueError) as exc:
            return {"error": f"request failed: {exc}"}
        lowered = {k.lower(): v for k, v in headers.items()}
        if status in (301, 302, 307, 308) and lowered.get("location"):
            url = lowered["location"]
            redirected = True
            continue
        if status == 200:
            try:
                raw = json.loads(body.decode("utf-8"))
            except ValueError:
                return {"error": "answer is not JSON"}
            kept = {key: raw.get(key) for key in _KEPT_FIELDS}
            license_block = raw.get("license") or {}
            kept["license_spdx"] = license_block.get("spdx_id")
            kept["redirected"] = redirected
            return kept
        if status == 404:
            return {"error": "404 not found (deleted, private, or never existed)"}
        if status in (403, 429) and lowered.get("x-ratelimit-remaining") == "0":
            return {
                "error": "GitHub rate limit reached; run again later or set GITHUB_TOKEN"
            }
        if status == 401:
            return {"error": "401: GitHub did not accept the token"}
        return {"error": f"HTTP {status}"}
    return {"error": "too many redirects"}


class Cache:
    """GitHub answers on disk, so a second run needs no network."""

    def __init__(self, path: Path, *, offline: bool, refetch: bool) -> None:
        self.path = path
        self.offline = offline
        self.doc: dict[str, Any] = {}
        if path.exists() and not refetch:
            try:
                self.doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.doc = {}
        self._token: str | None = None
        self._token_read = False
        self.used_token = False
        self.token_refused = False
        self.errors = 0

    def repo(self, owner: str, repo: str, today: str) -> dict[str, Any]:
        key = f"{owner}/{repo}".lower()
        if key in self.doc:
            return self.doc[key]
        if self.offline:
            self.errors += 1
            return {"error": "offline: no cached answer"}
        if not self._token_read:
            self._token, self._token_read = read_token(), True
            self.used_token = bool(self._token)
        time.sleep(PAUSE_S)
        answer = fetch_repo(owner, repo, self._token)
        if self._token and str(answer.get("error", "")).startswith("401"):
            # A dead token must not stop a check of public data: say so once
            # and go on without it.
            self.token_refused = True
            self._token = None
            self.used_token = False
            time.sleep(PAUSE_S)
            answer = fetch_repo(owner, repo, None)
        if "error" in answer:
            self.errors += 1
        if "error" not in answer:
            answer["fetched"] = today
            self.doc[key] = answer
            # A moved repository is also filed under its new name, so the
            # rewritten record finds the same answer.
            if answer.get("full_name"):
                self.doc[str(answer["full_name"]).lower()] = answer
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.doc, indent=1, ensure_ascii=False, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        return answer


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def parse_repo_url(url: Any) -> tuple[str, str] | None:
    if not isinstance(url, str):
        return None
    match = GITHUB_REPO_RE.match(url.strip())
    if not match:
        return None
    return match.group("owner"), match.group("repo")


def _iso(value: Any) -> str | None:
    """A YAML date or ISO string as ``YYYY-MM-DD``."""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return None


@dataclass
class Plan:
    """What GitHub says about one tool and what would change."""

    path: Path
    node: dict[str, Any]
    answer: dict[str, Any] | None = None
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def tool_id(self) -> str:
        return str(self.node.get("id") or self.path.stem)


def decide_status(
    current: Any, *, archived: bool, pushed: str | None, as_of: dt.date
) -> tuple[Any, str | None]:
    """Return ``(status, note)``. The status is only ever lowered."""
    age = (as_of - dt.date.fromisoformat(pushed)).days if pushed else None
    if archived:
        if current not in ("deprecated", "abandoned"):
            return "deprecated", None
        return current, None
    if age is not None and age > STALE_AT_RISK_DAYS:
        if current in ("stable", "experimental"):
            return "at_risk", None
        return current, None
    if current in ("deprecated", "abandoned", "at_risk"):
        return current, (
            f"status is '{current}' but the repository is not archived and was"
            f" pushed {age} days before the check; an editor should confirm"
        )
    return current, None


def build_plan(
    path: Path,
    cache: Cache,
    as_of: dt.date,
    accept_license: frozenset[str] = frozenset(),
) -> Plan:
    node = yaml.safe_load(path.read_text(encoding="utf-8"))
    plan = Plan(path=path, node=node if isinstance(node, dict) else {})
    if not isinstance(node, dict):
        plan.notes.append("top level is not a mapping; not checked")
        return plan
    parsed = parse_repo_url(node.get("repository_url"))
    if parsed is None:
        plan.notes.append(
            f"repository_url {node.get('repository_url')!r} is not a GitHub"
            " repository; not checked"
        )
        return plan
    today = as_of.isoformat()
    answer = cache.repo(parsed[0], parsed[1], today)
    if "error" in answer:
        plan.notes.append(f"GitHub: {answer['error']}; left as it is")
        return plan
    plan.answer = answer

    def want(key: str, new: Any) -> None:
        old = node.get(key)
        old_cmp = _iso(old) if isinstance(old, (dt.date, dt.datetime)) else old
        if old_cmp != new:
            plan.changes[key] = (old_cmp, new)

    pushed = _iso(answer.get("pushed_at"))
    archived = bool(answer.get("archived"))
    checked = _iso(answer.get("fetched")) or today

    if isinstance(answer.get("stargazers_count"), int):
        want("stars", answer["stargazers_count"])
        want("stars_updated_at", checked)
    if pushed:
        want("upstream_pushed_at", pushed)
        want("last_updated", pushed)
    want("last_reviewed", checked)
    want("archived", True if archived else None)

    full_name = str(answer.get("full_name") or "")
    if full_name and full_name.lower() != f"{parsed[0]}/{parsed[1]}".lower():
        new_url = str(answer.get("html_url") or f"https://github.com/{full_name}")
        want("repository_url", new_url)
        plan.notes.append(f"repository moved: {parsed[0]}/{parsed[1]} → {full_name}")

    spdx = str(answer.get("license_spdx") or "")
    current_license = str(node.get("license") or "")
    if spdx.upper() in _NO_LICENSE_IDS:
        plan.notes.append(
            f"GitHub detects no standard licence (answer: {spdx or 'none'});"
            f" record says {current_license!r}; check by hand"
        )
    elif current_license.lower() == "proprietary":
        plan.notes.append(
            f"record says 'proprietary', the repository is {spdx}; left for an editor"
        )
    elif spdx != current_license:
        if plan.tool_id in accept_license:
            want("license", spdx)
        else:
            plan.notes.append(
                f"licence: record says {current_license!r}, GitHub detects {spdx!r};"
                " read the licence file, then pass --accept-license"
                f" {plan.tool_id} if the record is wrong"
            )

    status, note = decide_status(
        node.get("maturity_status"),
        archived=archived,
        pushed=pushed,
        as_of=dt.date.fromisoformat(checked),
    )
    want("maturity_status", status)
    if note:
        plan.notes.append(note)
    if archived:
        plan.notes.append(f"repository is archived (last push {pushed})")
    if answer.get("disabled"):
        plan.notes.append("repository is disabled")
    first = _iso(node.get("first_released"))
    if pushed and first and pushed < first:
        plan.notes.append(
            f"last push {pushed} is before first_released {first}; check the dates"
        )
    return plan


# ---------------------------------------------------------------------------
# Rewriting (text level)
# ---------------------------------------------------------------------------

# Where a key goes when the file does not have it yet: after the first of
# these keys that the file has.
_ANCHORS: dict[str, tuple[str, ...]] = {
    "upstream_pushed_at": ("last_updated", "first_released"),
    "last_updated": ("first_released",),
    "last_reviewed": ("upstream_pushed_at", "last_updated", "first_released"),
    "archived": ("maturity_status",),
    "stars": (),
    "stars_updated_at": ("stars",),
}


def _render(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if key == "stars_updated_at":
        return f"'{value}'"  # the style the 47 existing files use
    return str(value)


def rewrite(text: str, changes: dict[str, tuple[Any, Any]]) -> str:
    """Apply single-line changes to the file text."""
    lines = text.split("\n")

    def find(key: str) -> int | None:
        for index, line in enumerate(lines):
            if re.match(rf"^{re.escape(key)}:(\s|$)", line):
                return index
        return None

    # Fixed order, so a key that anchors another one is placed first.
    order = (
        "repository_url",
        "license",
        "maturity_status",
        "archived",
        "last_updated",
        "upstream_pushed_at",
        "last_reviewed",
        "stars",
        "stars_updated_at",
    )
    for key in order:
        if key not in changes:
            continue
        new = changes[key][1]
        index = find(key)
        if new is None:
            if index is not None:
                del lines[index]
            continue
        rendered = f"{key}: {_render(key, new)}"
        if index is not None:
            lines[index] = rendered
            continue
        anchor = next(
            (i for i in (find(a) for a in _ANCHORS.get(key, ())) if i is not None),
            None,
        )
        if anchor is not None:
            lines.insert(anchor + 1, rendered)
        else:
            while lines and lines[-1] == "":
                lines.pop()
            lines.extend([rendered, ""])
    return "\n".join(lines)


def _plain(value: Any) -> Any:
    return _iso(value) if isinstance(value, (dt.date, dt.datetime)) else value


def apply(plan: Plan) -> None:
    """Rewrite one file and check that nothing but the plan changed."""
    old_text = plan.path.read_text(encoding="utf-8")
    new_text = rewrite(old_text, plan.changes)
    before = {k: _plain(v) for k, v in yaml.safe_load(old_text).items()}
    after = {k: _plain(v) for k, v in yaml.safe_load(new_text).items()}
    expected = dict(before)
    for key, (_, new_value) in plan.changes.items():
        if new_value is None:
            expected.pop(key, None)
        else:
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

# A star count or a check date that moves is routine; anything else is
# worth a line of its own in the summary.
_ROUTINE = {
    "stars",
    "stars_updated_at",
    "last_reviewed",
    "upstream_pushed_at",
    "last_updated",
}


def report_doc(plans: list[Plan], as_of: dt.date) -> dict[str, Any]:
    rows = []
    for plan in plans:
        answer = plan.answer or {}
        rows.append(
            {
                "id": plan.tool_id,
                "checked": bool(plan.answer),
                "repository_url": plan.node.get("repository_url"),
                "github": (
                    {
                        key: answer.get(key)
                        for key in (
                            "full_name",
                            "archived",
                            "stargazers_count",
                            "pushed_at",
                            "license_spdx",
                            "redirected",
                            "description",
                            "fetched",
                        )
                    }
                    if plan.answer
                    else None
                ),
                "changes": {
                    k: {"before": o, "after": n} for k, (o, n) in plan.changes.items()
                },
                "notes": plan.notes,
            }
        )
    return {"as_of": as_of.isoformat(), "tools": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare tool records with their GitHub repositories (stars, archived,"
            " moved, licence, last push). Dry run unless --write is given."
        )
    )
    parser.add_argument("--write", action="store_true", help="rewrite the files")
    parser.add_argument("--only", nargs="+", metavar="ID", help="these tool ids only")
    parser.add_argument(
        "--tools-dir", type=Path, default=TOOLS_DIR, help="default: data/tools"
    )
    parser.add_argument(
        "--as-of",
        type=dt.date.fromisoformat,
        default=None,
        help="date written as last_reviewed for new answers (default: today)",
    )
    parser.add_argument(
        "--cache", type=Path, default=CACHE_PATH, help="where GitHub answers are kept"
    )
    parser.add_argument(
        "--accept-license",
        nargs="+",
        default=[],
        metavar="ID",
        help="tool ids whose licence may be overwritten with the SPDX id GitHub detects",
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

    as_of = args.as_of or dt.date.today()
    paths = sorted(args.tools_dir.glob("*.yml"))
    if args.only:
        wanted = set(args.only)
        paths = [p for p in paths if p.stem in wanted]
        unknown = wanted - {p.stem for p in paths}
        if unknown:
            print(f"unknown tool id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
    if not paths:
        print("no tool files", file=sys.stderr)
        return 2

    cache = Cache(args.cache, offline=args.offline, refetch=args.refetch)
    accepted = frozenset(args.accept_license)
    plans = [build_plan(path, cache, as_of, accepted) for path in paths]
    if cache.token_refused:
        print(
            "note: GitHub refused GITHUB_TOKEN (401 Bad credentials); the token is"
            " expired or revoked. Continued without it.",
            file=sys.stderr,
        )
    if not args.offline and not cache.used_token and any(p.answer for p in plans):
        print(
            "note: no GITHUB_TOKEN found; used the anonymous limit (60 requests/hour)",
            file=sys.stderr,
        )

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report_doc(plans, as_of), indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    failed = 0
    written = 0
    for plan in plans:
        notable = {k: v for k, v in plan.changes.items() if k not in _ROUTINE}
        stars = plan.changes.get("stars")
        line = f"{plan.tool_id}:"
        if stars:
            line += f" stars {stars[0]} → {stars[1]};"
        pushed = plan.changes.get("upstream_pushed_at")
        if pushed:
            line += f" last push {pushed[1]};"
        for key, (old, new) in notable.items():
            line += f" {key} {old!r} → {new!r};"
        if plan.changes or plan.notes:
            print(line.rstrip(";") if line.endswith(";") else line)
        for note in plan.notes:
            print(f"  note: {note}")
        if args.write and plan.changes:
            try:
                apply(plan)
                written += 1
            except (OSError, ValueError) as exc:
                print(f"PROBLEM {plan.path.name}: not written — {exc}", file=sys.stderr)
                failed += 1

    differing = [p for p in plans if p.changes]
    unchecked = [p for p in plans if p.answer is None]
    print(
        f"\n{len(plans)} records: {len(plans) - len(differing) - len(unchecked)} match"
        f" GitHub, {len(differing)} differ"
        + (f" ({written} rewritten)" if args.write else "")
        + f", {len(unchecked)} not checked"
    )
    if failed or cache.errors:
        return 2
    if differing and not args.write:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
