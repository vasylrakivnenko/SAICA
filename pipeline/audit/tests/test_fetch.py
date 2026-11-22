"""Tests for the bounded remote fetch behind ``audit_repo`` (review H1).

No test here talks to GitHub. ``FakeGitHub`` stands in for the client and
serves a repository from a dict; the real :class:`GitHubClient` is tested
against a throw-away HTTP server on 127.0.0.1.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from pipeline import kg
from pipeline.audit import analyzer
from pipeline.audit.analyzer import (
    FetchLimits,
    FetchUnavailable,
    GitHubClient,
    RepoNotFound,
    RepoTooLarge,
    audit_repo,
    audit_repo_local,
    fetch_repo,
)
from pipeline.audit.detectors import (
    CONTENT_PATTERNS,
    _AGENT_RULES,
    _EVAL_CONFIG_RULES,
    CI_PROVIDER_MARKERS,
    DEPENDABOT_FILES,
    LANGUAGE_MARKERS,
    PACKAGE_MANAGER_LOCKS,
    PRE_COMMIT_FILES,
    RENOVATE_FILES,
    RUNTIME_HINT_FILES,
    fetch_plan,
)
from pipeline.shared.kg_fixture import write_kg


@pytest.fixture(autouse=True, scope="module")
def fixture_kg(tmp_path_factory):
    with kg.use_data_dir(write_kg(tmp_path_factory.mktemp("kg"))):
        yield


# ---------------------------------------------------------------------------
# A fake GitHub
# ---------------------------------------------------------------------------


def _sha(path: str) -> str:
    return hashlib.sha256(path.encode()).hexdigest()


class FakeGitHub:
    """Serves ``files`` (path -> bytes) the way the two GitHub hosts would."""

    def __init__(
        self,
        files: dict[str, bytes],
        *,
        truncated: bool = False,
        extra_tree: list[dict] | None = None,
    ):
        self.files = files
        self.truncated = truncated
        self.extra_tree = extra_tree or []
        self.calls: list[str] = []
        self.time_left = 100.0

    def remaining(self) -> float:
        return self.time_left

    def close(self) -> None:
        pass

    def _dirs(self) -> set[str]:
        out: set[str] = set()
        for path in self.files:
            parts = path.split("/")
            for i in range(1, len(parts)):
                out.add("/".join(parts[:i]))
        return out

    def _tree(self, prefix: str, recursive: bool) -> list[dict]:
        entries: list[dict] = []
        for d in sorted(self._dirs()):
            if d.startswith(prefix) and (recursive or "/" not in d[len(prefix) :]):
                entries.append(
                    {"path": d[len(prefix) :], "type": "tree", "sha": _sha(d)}
                )
        for f in sorted(self.files):
            if f.startswith(prefix) and (recursive or "/" not in f[len(prefix) :]):
                entries.append(
                    {
                        "path": f[len(prefix) :],
                        "type": "blob",
                        "sha": _sha(f),
                        "size": len(self.files[f]),
                    }
                )
        return entries

    def get(self, url: str, *, max_bytes: int):
        self.calls.append(url)
        api = "https://api.github.com/repos/o/r/git/trees/"
        raw = "https://raw.githubusercontent.com/o/r/HEAD/"
        if url.startswith(api):
            ref, _, query = url[len(api) :].partition("?")
            recursive = query == "recursive=1"
            if ref == "HEAD":
                tree = self._tree("", recursive) + self.extra_tree
                truncated = self.truncated and recursive
                if truncated:
                    tree = tree[:1]  # GitHub cut the listing short
            else:
                folder = next(d for d in self._dirs() if _sha(d) == ref)
                tree, truncated = self._tree(folder + "/", False), False
            body = json.dumps(
                {"sha": "x", "tree": tree, "truncated": truncated}
            ).encode()
            return 200, body[:max_bytes], len(body) > max_bytes, {}
        if url.startswith(raw):
            path = url[len(raw) :]
            if path not in self.files:
                return 404, b"", False, {}
            body = self.files[path]
            return 200, body[:max_bytes], len(body) > max_bytes, {}
        raise AssertionError(f"unexpected url {url}")


REPO_FILES: dict[str, bytes] = {
    "pyproject.toml": b"[project]\nname='x'\ndependencies=['litellm']\n[tool.ruff]\n",
    "requirements-dev.txt": b"guardrails-ai\n",
    "requirements/prod.txt": b"promptfoo\n",  # sub-folder: not read
    "package.json": b'{"devDependencies": {"eslint": "9"}}',
    "yarn.lock": b"x" * 3_000_000,  # presence only: must not be downloaded
    "README.md": b"# hello\n",
    "src/app.py": b"print('x')\n",
    "python/pyproject.toml": b"[tool.mypy]\n",  # monorepo package: not read
    ".github/workflows/ci.yml": b"jobs:\n  a:\n    steps:\n      - uses: semgrep/semgrep-action@v1\n",
    ".github/workflows/notes.txt": b"not a workflow\n",
    ".github/dependabot.yml": b"version: 2\n",
    ".claude/settings.json": b"{}",
    ".claude/skills/big.md": b"y" * 2_000_000,
    "CLAUDE.md": b"z" * 1_000_000,
    ".pre-commit-config.yaml": b"repos:\n  - repo: https://github.com/PyCQA/bandit\n    hooks: [{id: bandit}]\n",
}


def _materialise(root: Path, files: dict[str, bytes]) -> Path:
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(body)
    return root


# ---------------------------------------------------------------------------
# What is fetched
# ---------------------------------------------------------------------------


def test_fetch_downloads_only_what_the_detectors_read(tmp_path: Path):
    client = FakeGitHub(REPO_FILES)
    stats = fetch_repo("o", "r", tmp_path / "repo", client=client)

    downloaded = sorted(u.rsplit("/HEAD/", 1)[1] for u in client.calls if "/HEAD/" in u)
    assert downloaded == [
        ".github/workflows/ci.yml",
        ".pre-commit-config.yaml",
        "package.json",
        "pyproject.toml",
        "requirements-dev.txt",
    ]
    # One listing call, then the five files: no clone, no second API call.
    assert len(client.calls) == 6
    assert stats.files_listed == len(REPO_FILES)
    assert stats.files_read == 5
    assert stats.bytes_read == sum(len(REPO_FILES[p]) for p in downloaded)
    assert stats.truncated == []

    repo = tmp_path / "repo"
    # Presence-only markers exist and are empty: 6 MB were never downloaded.
    for rel in ("yarn.lock", "CLAUDE.md", ".github/dependabot.yml"):
        assert (repo / rel).is_file() and (repo / rel).stat().st_size == 0
    assert (repo / ".claude").is_dir() and not any((repo / ".claude").iterdir())
    for rel in (
        "README.md",
        "src",
        "python",
        "requirements",
        ".github/workflows/notes.txt",
    ):
        assert not (repo / rel).exists()


def test_remote_audit_equals_local_audit_of_the_same_tree(tmp_path: Path):
    """The two fetch paths used to see different files (SV-09)."""
    local = audit_repo_local(
        _materialise(tmp_path / "checkout", REPO_FILES),
        repo_url="https://github.com/o/r",
    )
    remote = audit_repo("https://github.com/o/r.git", client=FakeGitHub(REPO_FILES))
    assert remote.repo_url == "https://github.com/o/r"
    assert remote.stack == local.stack
    assert remote.coverage == local.coverage
    assert remote.gaps == local.gaps
    assert {t.id for t in remote.stack.supervision_tools} == {
        "semgrep",
        "dependabot",
        "bandit",
        "litellm",
        "guardrails-ai",
        "eslint",
        "ruff",
    }
    assert [a.id for a in remote.stack.agents] == ["claude-code"]
    assert remote.limits.files_read == 5 and local.limits.files_read is None
    assert "This run listed 15 files and read 5 of them" in remote.markdown


def test_every_marker_of_every_rule_table_is_in_the_fetch_plan():
    """A rule that looks at a file the fetch does not bring would be blind
    for remote audits. The plan is derived from the tables; this pins it."""
    files: list[str] = list(RUNTIME_HINT_FILES) + list(PACKAGE_MANAGER_LOCKS)
    files += list(DEPENDABOT_FILES) + list(RENOVATE_FILES) + list(PRE_COMMIT_FILES)
    folders: list[str] = []
    markers = [m for _, group in LANGUAGE_MARKERS for m in group]
    markers += [m for _, group in CI_PROVIDER_MARKERS for m in group]
    markers += [m for _, _, rules in _AGENT_RULES for m, _ in rules]
    markers += [m for _, _, group in _EVAL_CONFIG_RULES for m in group]
    for marker in markers:
        (folders if marker.endswith("/") else files).append(marker.rstrip("/"))
    files = [f.replace("*", "App") for f in files]  # "*.csproj" -> "App.csproj"
    files += [
        "requirements.txt",
        "requirements-dev.txt",
        ".github/workflows/x.yml",
        ".github/workflows/y.yaml",
    ]

    content, presence, dirs = fetch_plan(sorted(set(files)), sorted(set(folders)))
    assert sorted(content + presence) == sorted(set(files))
    assert dirs == sorted(set(folders))
    # Content files are exactly the ones a parser opens.
    assert all(
        any(
            analyzer.fetch_plan.__globals__["_matches"](c, pat)
            for pat in CONTENT_PATTERNS
        )
        for c in content
    )
    assert "yarn.lock" in presence and "pyproject.toml" in content


def test_patterns_do_not_reach_into_sub_folders():
    blobs = [
        "requirements/dev.txt",
        "sub/pyproject.toml",
        ".github/workflows/deep/x.yml",
        "a/b.csproj",
        "x.csproj",
    ]
    content, presence, dirs = fetch_plan(blobs, ["requirements", "sub", "a"])
    assert content == []
    assert presence == ["x.csproj"]
    # The workflows folder exists (it holds a sub-folder), so it is created;
    # the file below it is not a workflow and is not downloaded.
    assert dirs == [".github/workflows"]


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------


def test_file_count_cap(tmp_path: Path):
    files = {f".github/workflows/w{i:03d}.yml": b"jobs: {}\n" for i in range(80)}
    files["pyproject.toml"] = b"[tool.ruff]\n"
    client = FakeGitHub(files)
    stats = fetch_repo(
        "o", "r", tmp_path / "repo", client=client, limits=FetchLimits(max_files=10)
    )
    assert stats.files_read == 10
    assert len(client.calls) == 11
    assert stats.truncated == [
        "Only the first 10 of 81 manifest and workflow files were read."
    ]
    report = audit_repo(
        "https://github.com/o/r",
        client=FakeGitHub(files),
        limits=FetchLimits(max_files=10),
    )
    assert "Cut short: Only the first 10 of 81" in report.markdown
    assert report.limits.truncated


def test_total_byte_cap_and_per_file_cap(tmp_path: Path):
    files = {
        ".github/workflows/a.yml": b"a" * 600,
        ".github/workflows/b.yml": b"b" * 600,
        ".github/workflows/c.yml": b"c" * 600,
        "pyproject.toml": b"[tool.ruff]\n",
    }
    limits = FetchLimits(max_file_bytes=500, max_total_bytes=1200)
    stats = fetch_repo(
        "o", "r", tmp_path / "repo", client=FakeGitHub(files), limits=limits
    )
    repo = tmp_path / "repo"
    sizes = {p.name: p.stat().st_size for p in (repo / ".github/workflows").iterdir()}
    assert sizes == {"a.yml": 500, "b.yml": 500, "c.yml": 200}
    assert stats.bytes_read == 1200
    assert not (repo / "pyproject.toml").exists()  # the budget was spent
    assert (
        "The download limit was reached; some files were not read." in stats.truncated
    )
    assert (
        ".github/workflows/a.yml was read in part (it is very large)."
        in stats.truncated
    )


def test_listing_larger_than_the_cap_is_refused(tmp_path: Path):
    files = {f"src/file{i:05d}.py": b"" for i in range(2000)}
    with pytest.raises(RepoTooLarge):
        fetch_repo(
            "o",
            "r",
            tmp_path / "repo",
            client=FakeGitHub(files),
            limits=FetchLimits(max_listing_bytes=10_000),
        )
    assert not (tmp_path / "repo").exists()


def test_time_running_out_stops_the_downloads_and_says_so(tmp_path: Path):
    client = FakeGitHub(REPO_FILES)
    original = client.get

    def get(url, *, max_bytes):
        result = original(url, max_bytes=max_bytes)
        if "/HEAD/" in url:
            client.time_left = 0.0  # the clock runs out after the first file
        return result

    client.get = get
    stats = fetch_repo("o", "r", tmp_path / "repo", client=client)
    assert stats.files_read == 1
    assert stats.truncated == ["The time limit was reached; some files were not read."]


def test_paths_that_would_leave_the_folder_are_never_written(tmp_path: Path):
    evil = [
        {"path": "../pyproject.toml", "type": "blob", "sha": "1"},
        {"path": "/etc/pyproject.toml", "type": "blob", "sha": "2"},
        {"path": ".github/workflows/../../../escape.yml", "type": "blob", "sha": "3"},
        {"path": ".github/workflows/..\\x.yml", "type": "blob", "sha": "4"},
        {"path": 7, "type": "blob"},
        "not a dict",
        {"path": "..", "type": "tree", "sha": "5"},
    ]
    client = FakeGitHub({"pyproject.toml": b"[tool.ruff]\n"}, extra_tree=evil)
    fetch_repo("o", "r", tmp_path / "work" / "repo", client=client)
    written = sorted(
        p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()
    )
    assert written == ["work/repo/pyproject.toml"]


def test_very_large_repository_falls_back_to_a_folder_walk(tmp_path: Path):
    client = FakeGitHub(REPO_FILES, truncated=True)
    stats = fetch_repo("o", "r", tmp_path / "repo", client=client)
    api_calls = [u for u in client.calls if "api.github.com" in u]
    # recursive listing (cut short), root, .github, .github/workflows
    assert len(api_calls) == 4
    assert stats.files_read == 5
    report = audit_repo_local(tmp_path / "repo", repo_url="https://github.com/o/r")
    assert {t.id for t in report.stack.supervision_tools} == {
        "semgrep",
        "dependabot",
        "bandit",
        "litellm",
        "guardrails-ai",
        "eslint",
        "ruff",
    }


# ---------------------------------------------------------------------------
# Errors a user can be shown
# ---------------------------------------------------------------------------


class _Answer:
    def __init__(self, status: int, headers: dict | None = None, body: bytes = b"{}"):
        self.status, self.headers, self.body = status, headers or {}, body

    def remaining(self) -> float:
        return 10.0

    def close(self) -> None:
        pass

    def get(self, url, *, max_bytes):
        return self.status, self.body, False, self.headers


@pytest.mark.parametrize(
    "client, error",
    [
        (_Answer(404), RepoNotFound),
        (_Answer(409), RepoNotFound),
        (_Answer(403, {"X-RateLimit-Remaining": "0"}), FetchUnavailable),
        (_Answer(429), FetchUnavailable),
        (_Answer(403), FetchUnavailable),
        (_Answer(500), FetchUnavailable),
        (_Answer(200, body=b"<html>not json"), FetchUnavailable),
        (_Answer(200, body=b'["a list"]'), FetchUnavailable),
        (_Answer(200, body=b'{"tree": "nope"}'), FetchUnavailable),
    ],
)
def test_listing_failures_become_plain_audit_errors(tmp_path: Path, client, error):
    with pytest.raises(error) as excinfo:
        audit_repo("https://github.com/o/r", client=client)
    message = str(excinfo.value)
    assert message and "Traceback" not in message and "api.github.com" not in message


def test_bad_url_is_refused_before_any_request():
    client = FakeGitHub({})
    for url in (
        "https://gitlab.com/o/r",
        "https://github.com/../..",
        "file:///etc/passwd",
    ):
        with pytest.raises(ValueError):
            audit_repo(url, client=client)
    assert client.calls == []


# ---------------------------------------------------------------------------
# The real client, against a local server
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    def do_GET(self):  # noqa: N802 - http.server API
        self.server.seen.append((self.path, dict(self.headers)))
        if self.path == "/big":
            self.send_response(200)
            self.send_header("Content-Length", str(2_000_000))
            self.end_headers()
            try:
                self.wfile.write(b"x" * 2_000_000)
            except OSError:
                pass
        elif self.path == "/drip":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            try:
                for _ in range(1000):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.05)
            except OSError:
                pass
        elif self.path == "/away":
            self.send_response(302)
            self.send_header("Location", "https://example.com/elsewhere")
            self.end_headers()
        elif self.path == "/hop":
            self.send_response(301)
            self.send_header("Location", "/small")
            self.end_headers()
        elif self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Length", "5")
            self.end_headers()
            self.wfile.write(b"hello")


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    httpd.seen = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _client(server, **kwargs) -> tuple[GitHubClient, str]:
    kwargs.setdefault("deadline_seconds", 5.0)
    client = GitHubClient(
        allowed_hosts=frozenset({"127.0.0.1"}), schemes=("http",), **kwargs
    )
    return client, f"http://127.0.0.1:{server.server_address[1]}"


def test_client_reads_a_small_body(server):
    client, base = _client(server)
    assert client.get(base + "/small", max_bytes=100)[:3] == (200, b"hello", False)
    assert client.get(base + "/small", max_bytes=3)[:3] == (200, b"hel", True)
    client.close()


def test_client_stops_reading_at_the_byte_cap(server):
    client, base = _client(server)
    status, body, cut, _ = client.get(base + "/big", max_bytes=10_000)
    assert (status, len(body), cut) == (200, 10_000, True)
    client.close()


def test_client_gives_up_at_the_deadline_on_a_slow_drip(server):
    """A server that sends one byte every 50 ms would take 50 s."""
    client, base = _client(server, deadline_seconds=0.5)
    started = time.monotonic()
    with pytest.raises(FetchUnavailable, match="ran out of time"):
        client.get(base + "/drip", max_bytes=10_000)
    assert time.monotonic() - started < 2.0
    # And nothing more is attempted once the time is gone.
    with pytest.raises(FetchUnavailable):
        client.get(base + "/small", max_bytes=10)
    client.close()


def test_client_follows_a_redirect_on_the_same_host_only(server):
    client, base = _client(server)
    assert client.get(base + "/hop", max_bytes=100)[1] == b"hello"
    with pytest.raises(FetchUnavailable, match="redirected off GitHub"):
        client.get(base + "/away", max_bytes=100)
    with pytest.raises(FetchUnavailable, match="Too many redirects"):
        client.get(base + "/loop", max_bytes=100)
    client.close()


def test_client_refuses_other_hosts_and_plain_http_by_default():
    client = GitHubClient(deadline_seconds=1.0)
    for url in (
        "http://api.github.com/repos/o/r",
        "https://example.com/x",
        "https://api.github.com.evil.example/x",
        "https://127.0.0.1/x",
        "file:///etc/passwd",
    ):
        with pytest.raises(FetchUnavailable):
            client.get(url, max_bytes=10)
    client.close()


def test_client_sends_a_token_only_when_given_one_and_only_to_the_api(
    server, monkeypatch
):
    monkeypatch.setattr(analyzer, "API_HOST", "127.0.0.1")
    with_token, base = _client(server, token="t0ken")
    with_token.get(base + "/small", max_bytes=10)
    assert server.seen[-1][1]["Authorization"] == "Bearer t0ken"
    assert server.seen[-1][1]["User-Agent"].startswith("saica-audit")
    without, _ = _client(server)
    without.get(base + "/small", max_bytes=10)
    assert "Authorization" not in server.seen[-1][1]
    # A host that is not the API host never gets the token.
    monkeypatch.setattr(analyzer, "API_HOST", "api.github.com")
    with_token.get(base + "/small", max_bytes=10)
    assert "Authorization" not in server.seen[-1][1]
    with_token.close()
    without.close()


def test_client_reports_an_unreachable_server_without_details():
    client = GitHubClient(
        deadline_seconds=2.0, allowed_hosts=frozenset({"127.0.0.1"}), schemes=("http",)
    )
    with pytest.raises(FetchUnavailable) as excinfo:
        client.get("http://127.0.0.1:1/x", max_bytes=10)  # port 1: nothing listens
    assert str(excinfo.value) == "GitHub could not be reached."
    client.close()
