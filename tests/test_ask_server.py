"""Tests for the Ask / Assess API (``pipeline.ask.server``) and the Ask
context builder.

All HTTP goes through Starlette's ``TestClient``. No model is called, no
embedding is computed and nothing is fetched from GitHub: ``find_similar``,
``kimi_call`` and ``audit`` are fakes injected through ``create_app``.
The KG is the fixture of :mod:`pipeline.shared.kg_fixture`.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pipeline import kg
from pipeline.ask import context as ask_context
from pipeline.ask import server
from pipeline.ask.server import (
    DayCache,
    PerClientLimit,
    Settings,
    client_key,
    create_app,
)
from pipeline.audit.analyzer import (
    FetchUnavailable,
    RepoNotFound,
    RepoTooLarge,
    audit_repo_local,
)
from pipeline.cost_caps import CallBudget, DailyBudget
from pipeline.shared.kg_fixture import write_kg


@pytest.fixture(autouse=True, scope="module")
def fixture_kg(tmp_path_factory):
    with kg.use_data_dir(write_kg(tmp_path_factory.mktemp("kg"))):
        yield


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

HITS = [
    ("guardrails-ai", 0.81),
    ("fabrication", 0.77),
    ("fixture-taxonomy", 0.72),
    ("fixture-paper-2025", 0.68),
]


def _response(tokens: int = 250, model: str = "stub-model") -> Any:
    return SimpleNamespace(usage=SimpleNamespace(total_tokens=tokens), model=model)


class Retrieval:
    """Fake ``find_similar`` that counts its calls."""

    def __init__(self, hits=HITS, error: Exception | None = None):
        self.hits, self.error, self.calls = list(hits), error, 0

    def __call__(self, question: str, k: int, *, node_type: str | None = None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.hits[:k]


class Model:
    """Fake ``kimi_call`` that counts its calls and keeps the prompt."""

    def __init__(
        self,
        answer: str = "fine [guardrails-ai]",
        tokens: int = 250,
        error: Exception | None = None,
    ):
        self.answer, self.tokens, self.error = answer, tokens, error
        self.calls, self.prompts = 0, []

    def __call__(self, prompt: str):
        self.calls += 1
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.answer, _response(self.tokens)


def _report(tmp_path: Path, url: str = "https://github.com/o/r"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return audit_repo_local(tmp_path, repo_url=url)


class Audit:
    """Fake ``audit_repo``: counts calls, can block, can raise."""

    def __init__(
        self,
        tmp_path: Path,
        error: Exception | None = None,
        gate: threading.Event | None = None,
    ):
        self.tmp_path, self.error, self.gate = tmp_path, error, gate
        self.calls: list[str] = []
        self.started = threading.Event()

    def __call__(self, repo_url: str):
        self.calls.append(repo_url)
        self.started.set()
        if self.gate is not None:
            assert self.gate.wait(timeout=10)
        if self.error:
            raise self.error
        return _report(self.tmp_path / "empty", repo_url)


def _client(peer: str = "198.51.100.200", **kwargs) -> TestClient:
    """``peer`` is the address of the socket that reaches the app."""
    kwargs.setdefault("find_similar", Retrieval())
    kwargs.setdefault("kimi_call", Model())
    kwargs.setdefault("settings", Settings())
    return TestClient(
        create_app(**kwargs), raise_server_exceptions=False, client=(peer, 50000)
    )


def _ask(client: TestClient, question: str = "what prevents hallucinations?", **kwargs):
    return client.post("/ask", json={"question": question}, **kwargs)


# ---------------------------------------------------------------------------
# /ask — happy path and input errors
# ---------------------------------------------------------------------------


def test_ask_returns_answer_and_citations() -> None:
    model = Model(
        "Guardrails AI checks output [guardrails-ai]; see [fabrication].", tokens=310
    )
    client = _client(kimi_call=model)
    resp = _ask(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "[guardrails-ai]" in body["answer"]
    assert body["kimi_tokens_used"] == 310 and body["model"] == "stub-model"
    urls = {c["id"]: c["url"] for c in body["citations"]}
    assert urls == {
        "guardrails-ai": "/tools/guardrails-ai",
        "fabrication": "/failure-modes/fabrication",
        "fixture-taxonomy": "/taxonomies/fixture-taxonomy",
        "fixture-paper-2025": "/papers/fixture-paper-2025",
    }
    # The prompt carries the context blocks and the question.
    [prompt] = model.prompts
    assert "what prevents hallucinations?" in prompt
    assert "[guardrails-ai]" in prompt and "[fabrication]" in prompt
    assert resp.headers["x-request-id"]


def test_ask_blank_question_is_a_400_and_costs_nothing() -> None:
    retrieval, model = Retrieval(), Model()
    budget = CallBudget(max_calls=5)
    client = _client(find_similar=retrieval, kimi_call=model, budget=budget)
    assert _ask(client, "").status_code == 422
    resp = _ask(client, "   ")
    assert resp.status_code == 400 and "blank" in resp.json()["detail"]
    assert (retrieval.calls, model.calls, budget.summary()) == (
        0,
        0,
        "calls=0 tokens≈0",
    )


# ---------------------------------------------------------------------------
# H2 — the budget is checked before the expensive step, and is not published
# ---------------------------------------------------------------------------


def test_budget_is_checked_before_retrieval_and_the_counter_is_not_shown() -> None:
    """The review's probe: budget 2, six questions. Retrieval ran 12 times
    and the 429 body said how many calls had been made."""
    retrieval, model = Retrieval(), Model()
    client = _client(
        find_similar=retrieval,
        kimi_call=model,
        budget=CallBudget(max_calls=2),
        settings=Settings(ask_per_client_hour=100),
    )
    responses = [_ask(client, "which library fits a ci pipeline?") for _ in range(6)]
    assert [r.status_code for r in responses] == [200, 200, 429, 429, 429, 429]
    # Two questions were answered; each ran retrieval twice (pipeline wording).
    assert (retrieval.calls, model.calls) == (4, 2)
    refused = responses[-1].json()
    assert (
        refused["detail"]
        == "The question budget for today is used up. Please try again tomorrow."
    )
    assert not any(ch.isdigit() for ch in refused["detail"])
    health = client.get("/health")
    assert health.json() == {"ok": True}


def test_daily_budget_starts_again_the_next_day() -> None:
    day = [dt.date(2026, 11, 21)]
    budget = DailyBudget(max_calls=1, today=lambda: day[0])
    client = _client(budget=budget, settings=Settings(ask_per_client_hour=100))
    assert [_ask(client).status_code for _ in range(2)] == [200, 429]
    day[0] = dt.date(2026, 11, 22)
    assert [_ask(client).status_code for _ in range(2)] == [200, 429]


def test_token_budget_closes_the_day_after_the_paid_answer_is_returned() -> None:
    budget = CallBudget(max_calls=10, max_tokens_estimate=300)
    client = _client(
        kimi_call=Model(tokens=250),
        budget=budget,
        settings=Settings(ask_per_client_hour=100),
    )
    # 250, then 500 tokens: the second answer was paid for and is returned.
    assert [_ask(client).status_code for _ in range(3)] == [200, 200, 429]
    assert budget.summary() == "calls=2 tokens≈500"


def test_failed_retrieval_gives_the_reserved_call_back() -> None:
    budget = CallBudget(max_calls=1)
    retrieval = Retrieval(
        error=FileNotFoundError("/home/runner/workspace/.cache/vectors.npy")
    )
    model = Model()
    client = _client(find_similar=retrieval, kimi_call=model, budget=budget)
    resp = _ask(client)
    assert resp.status_code == 500
    assert model.calls == 0 and budget.summary() == "calls=0 tokens≈0"
    # A failed model call stays counted: it may have been billed.
    client = _client(kimi_call=Model(error=RuntimeError("boom")), budget=budget)
    assert _ask(client).status_code == 500
    assert budget.summary() == "calls=1 tokens≈0"


def test_per_client_limit_counts_the_address_the_proxy_wrote() -> None:
    """The app sits behind a trusted proxy (here: loopback)."""
    retrieval, model = Retrieval(), Model()
    client = _client(
        peer="127.0.0.1",
        find_similar=retrieval,
        kimi_call=model,
        budget=CallBudget(max_calls=100),
        settings=Settings(ask_per_client_hour=2),
    )

    def ask_as(forwarded: str) -> int:
        return _ask(client, headers={"X-Forwarded-For": forwarded}).status_code

    # The caller rotates the left-hand (forgeable) entry; the proxy's entry
    # stays the same, so the limit holds.
    assert [ask_as(f"10.0.0.{i}, 203.0.113.7") for i in range(4)] == [
        200,
        200,
        429,
        429,
    ]
    # Another visitor, as seen by the proxy, has a limit of their own.
    assert ask_as("10.0.0.1, 198.51.100.9") == 200
    assert model.calls == 3  # refused calls reached neither retrieval nor the model
    assert retrieval.calls == 3
    refused = _ask(client, headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.7"})
    assert refused.headers["retry-after"] == "3600"
    assert "this address" in refused.json()["detail"]


def test_forwarded_header_from_an_untrusted_peer_is_ignored() -> None:
    """Reached directly, 12 of 12 requests passed by varying the header."""
    model = Model()
    client = _client(  # the default peer is a public address, not a proxy
        kimi_call=model,
        budget=CallBudget(max_calls=100),
        settings=Settings(ask_per_client_hour=2),
    )
    codes = [
        _ask(client, headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code
        for i in range(12)
    ]
    assert codes == [200, 200] + [429] * 10
    assert model.calls == 2


def test_second_header_line_and_ports_cannot_split_or_merge_buckets() -> None:
    client = _client(
        peer="127.0.0.1",
        budget=CallBudget(max_calls=100),
        settings=Settings(ask_per_client_hour=2),
    )

    def ask_with(lines: list[str]) -> int:
        headers = [("X-Forwarded-For", line) for line in lines]
        return client.post("/ask", json={"question": "q"}, headers=headers).status_code

    # The proxy appends its entry as a second line; the caller varies the first.
    codes = [ask_with([f"9.9.9.{i}", "203.0.113.7"]) for i in range(4)]
    assert codes == [200, 200, 429, 429]
    # "ip:port" entries are two different visitors, not one "unknown" bucket.
    assert ask_with(["198.51.100.1:5555"]) == 200
    assert ask_with(["198.51.100.2:5555"]) == 200
    assert [ask_with(["[2001:db8::1]:443"]) for _ in range(3)] == [200, 200, 429]


LOOP = ("127.0.0.1", 0)
PROXY = ("10.1.1.1", 0)
TRUST_PROXY = ("10.0.0.0/8",)


@pytest.mark.parametrize(
    "peer, forwarded, hops, trusted, expected",
    [
        (("192.0.2.1", 5), None, 1, (), "192.0.2.1"),  # no header: the socket
        # An untrusted peer may write what it likes; it is counted as itself.
        (("192.0.2.1", 5), ["6.6.6.6"], 1, (), "192.0.2.1"),
        (("192.0.2.1", 5), ["6.6.6.6"], 1, TRUST_PROXY, "192.0.2.1"),
        (PROXY, ["203.0.113.7"], 1, TRUST_PROXY, "203.0.113.7"),
        (
            PROXY,
            "6.6.6.6, 203.0.113.7",
            1,
            TRUST_PROXY,
            "203.0.113.7",
        ),  # forged left entry
        (
            PROXY,
            ["6.6.6.6", "203.0.113.7"],
            1,
            TRUST_PROXY,
            "203.0.113.7",
        ),  # two header lines
        (PROXY, ["6.6.6.6, 203.0.113.7, 10.9.9.9"], 2, TRUST_PROXY, "203.0.113.7"),
        (PROXY, ["203.0.113.7"], 2, TRUST_PROXY, "10.1.1.1"),  # fewer entries than hops
        (PROXY, [" , "], 1, TRUST_PROXY, "10.1.1.1"),
        (PROXY, ["not-an-address"], 1, TRUST_PROXY, "10.1.1.1"),  # no shared "unknown"
        (PROXY, ["203.0.113.7:4711"], 1, TRUST_PROXY, "203.0.113.7"),
        (PROXY, ["[2001:db8:1:2::1]:4711"], 1, TRUST_PROXY, "2001:db8:1:2::"),
        (
            PROXY,
            ["2001:db8:1:2:aaaa:bbbb:cccc:dddd"],
            1,
            TRUST_PROXY,
            "2001:db8:1:2::",
        ),  # per /64
        (PROXY, ["::ffff:203.0.113.7"], 1, TRUST_PROXY, "203.0.113.7"),
        (
            LOOP,
            ["203.0.113.7"],
            1,
            server.DEFAULT_TRUSTED_PROXIES,
            "203.0.113.7",
        ),  # default: loopback
        (("::1", 0), ["203.0.113.7"], 1, server.DEFAULT_TRUSTED_PROXIES, "203.0.113.7"),
        (PROXY, ["203.0.113.7"], 1, server.DEFAULT_TRUSTED_PROXIES, "10.1.1.1"),
        (
            ("192.0.2.1", 5),
            ["203.0.113.7"],
            1,
            ("*",),
            "203.0.113.7",
        ),  # the owner's explicit choice
        (None, ["203.0.113.7"], 1, ("*",), "unknown"),
        (("testclient", 5), None, 1, (), "unknown"),
    ],
)
def test_client_key(peer, forwarded, hops, trusted, expected) -> None:
    assert client_key(peer, forwarded, hops, trusted) == expected


def test_trusted_proxies_from_env(monkeypatch) -> None:
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    assert server.trusted_proxies_from_env() == ("127.0.0.0/8", "::1/128")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.0/8, 192.168.1.5, nonsense")
    assert server.trusted_proxies_from_env() == ("10.0.0.0/8", "192.168.1.5")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    assert server.trusted_proxies_from_env() == ("*",)
    assert server.is_trusted_proxy("10.2.3.4", ("10.0.0.0/8",)) is True
    assert server.is_trusted_proxy("11.2.3.4", ("10.0.0.0/8",)) is False
    assert server.is_trusted_proxy("garbage", ("10.0.0.0/8",)) is False
    assert server.is_trusted_proxy("garbage", ("*",)) is True


def test_per_client_limit_window_and_memory_bound() -> None:
    now = [0.0]
    limit = PerClientLimit(2, window=60.0, max_clients=3, clock=lambda: now[0])
    assert [limit.allow("a") for _ in range(3)] == [True, True, False]
    now[0] = 59.0
    assert limit.allow("a") is False
    now[0] = 61.0
    assert limit.allow("a") is True  # the first two calls left the window
    for key in ("b", "c", "d"):
        assert limit.allow(key)
    assert len(limit._seen) == 3 and "a" not in limit._seen  # oldest forgotten
    assert PerClientLimit(0).allow("x") is False


def test_ask_is_refused_when_all_slots_are_taken() -> None:
    gate, started = threading.Event(), threading.Event()

    def slow_model(prompt: str):
        started.set()
        assert gate.wait(timeout=10)
        return "ok", _response()

    client = _client(
        kimi_call=slow_model,
        budget=CallBudget(max_calls=10),
        settings=Settings(ask_concurrency=1, ask_per_client_hour=100),
    )
    with ThreadPoolExecutor(1) as pool:
        first = pool.submit(_ask, client)
        assert started.wait(timeout=10)
        busy = _ask(client)
        assert busy.status_code == 429 and busy.headers["retry-after"] == "5"
        assert busy.json()["detail"] == server.BUSY
        assert client.get("/health").json() == {"ok": True}  # not blocked meanwhile
        gate.set()
        assert first.result(timeout=10).status_code == 200
    assert _ask(client).status_code == 200  # the slot came back


# ---------------------------------------------------------------------------
# H3 — hardening
# ---------------------------------------------------------------------------


def test_upstream_error_text_never_reaches_the_client(caplog) -> None:
    secret = "Error code: 401 - endpoint=https://api.hyperbolic.ai/v1 key=sk-live-123"
    client = _client(
        kimi_call=Model(error=RuntimeError(secret)), budget=CallBudget(max_calls=5)
    )
    with caplog.at_level(logging.ERROR, logger="pipeline.ask.server"):
        resp = _ask(client)
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == server.GENERIC_ERROR
    assert "hyperbolic" not in resp.text and "sk-live" not in resp.text
    # The id in the body is the id in the header and in the server log.
    assert body["request_id"] == resp.headers["x-request-id"]
    assert any(body["request_id"] in r.getMessage() for r in caplog.records)
    assert any(secret in (r.exc_text or "") for r in caplog.records)

    path = "/home/runner/workspace/.cache/embeddings/vectors.npy"
    client = _client(find_similar=Retrieval(error=FileNotFoundError(path)))
    resp = _ask(client)
    assert resp.status_code == 500 and "/home/runner" not in resp.text


def test_body_over_the_limit_is_refused_without_being_parsed_or_echoed() -> None:
    retrieval = Retrieval()
    client = _client(find_similar=retrieval)
    big = json.dumps({"question": "x" * 20_000})
    for path in ("/ask", "/assess", "/no-such-route"):
        resp = client.post(
            path, content=big, headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 413, path
        assert len(resp.content) < 300
        assert resp.json()["detail"] == "The request body is larger than 8192 bytes."
    assert retrieval.calls == 0

    # A body sent in chunks has no Content-Length; it is counted as it arrives.
    def chunks():
        for _ in range(40):
            yield b"x" * 1024

    resp = client.post(
        "/ask", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 413
    # Just under the limit still works.
    ok = client.post("/ask", json={"question": "y" * 1900})
    assert ok.status_code == 200


def test_declared_length_alone_is_enough_to_refuse() -> None:
    """The guard answers before it reads a single byte of the body."""
    import asyncio

    from pipeline.ask.server import ApiGuard

    async def app(scope, receive, send):  # pragma: no cover - must not run
        raise AssertionError("the app must not be called")

    sent: list[dict] = []
    received = 0

    async def receive():
        nonlocal received
        received += 1
        return {"type": "http.request", "body": b"x" * 100, "more_body": True}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/ask",
        "headers": [(b"content-length", b"20971520")],
    }
    asyncio.run(ApiGuard(app)(scope, receive, send))
    assert sent[0]["status"] == 413 and received == 0
    assert any(k == b"x-request-id" for k, _ in sent[0]["headers"])

    sent.clear()
    scope["headers"] = [(b"content-length", b"abc")]
    asyncio.run(ApiGuard(app)(scope, receive, send))
    assert sent[0]["status"] == 400


def test_validation_error_does_not_echo_the_input() -> None:
    client = _client()
    marker = "SECRET-INPUT-" + "z" * 3000  # over max_length=2000, under the body limit
    resp = client.post("/ask", json={"question": marker})
    assert resp.status_code == 422
    body = resp.json()
    assert "SECRET-INPUT" not in resp.text and len(resp.content) < 600
    assert isinstance(body["detail"], str) and body["detail"].startswith(
        "The request could not be read (question:"
    )
    assert set(body["errors"][0]) == {"loc", "msg", "type"}
    assert body["request_id"]
    wrong_type = client.post("/assess", json={"repo_url": {"nested": "SECRET-INPUT"}})
    assert wrong_type.status_code == 422 and "SECRET-INPUT" not in wrong_type.text
    not_json = client.post(
        "/ask", content=b"{SECRET-INPUT", headers={"Content-Type": "application/json"}
    )
    assert not_json.status_code == 422 and "SECRET-INPUT" not in not_json.text


def test_docs_are_off_unless_asked_for() -> None:
    client = _client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        resp = client.get(path)
        assert resp.status_code == 404, path
        assert resp.json()["request_id"]
    with_docs = _client(settings=Settings(docs=True))
    assert with_docs.get("/openapi.json").status_code == 200


def test_cors_allows_the_site_and_no_other_origin() -> None:
    client = _client()

    def preflight(origin: str):
        return client.options(
            "/ask",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    ok = preflight("https://saica.ai")
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "https://saica.ai"
    evil = preflight("https://evil.example")
    assert "access-control-allow-origin" not in evil.headers
    resp = _ask(client, headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers
    resp = _ask(client, headers={"Origin": "http://localhost:5000"})
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5000"
    assert "*" not in Settings().cors_origins


def test_settings_from_env(monkeypatch) -> None:
    for name in list(__import__("os").environ):
        if name.startswith("SAICA_"):
            monkeypatch.delenv(name)
    assert Settings.from_env() == Settings()
    monkeypatch.setenv("SAICA_ASK_BUDGET", "7")
    monkeypatch.setenv("SAICA_ASSESS_BUDGET", "not a number")
    monkeypatch.setenv("SAICA_ASSESS_CONCURRENCY", "0")
    monkeypatch.setenv("SAICA_CORS_ORIGINS", "https://a.example/, https://b.example")
    monkeypatch.setenv("SAICA_API_DOCS", "1")
    cfg = Settings.from_env()
    assert cfg.ask_daily_calls == 7
    assert cfg.assess_daily_calls == Settings.assess_daily_calls  # bad value: default
    assert cfg.assess_concurrency == 1  # never below one
    assert cfg.cors_origins == ("https://a.example", "https://b.example")
    assert cfg.docs is True


# ---------------------------------------------------------------------------
# H1 — /assess is bounded
# ---------------------------------------------------------------------------


def _assess(client: TestClient, url: str = "https://github.com/Owner/Repo", **kwargs):
    return client.post("/assess", json={"repo_url": url}, **kwargs)


def test_assess_returns_a_report_and_caches_it_for_the_repository(
    tmp_path: Path,
) -> None:
    audit = Audit(tmp_path)
    budget = CallBudget(max_calls=10)
    client = _client(audit=audit, assess_budget=budget)
    first = _assess(client)
    assert first.status_code == 200 and first.headers["x-saica-cache"] == "miss"
    report = first.json()
    assert report["repo_url"] == "https://github.com/Owner/Repo"
    assert report["limits"]["not_assessable_failure_modes"] == [
        "cascading_failure",
        "dependency_blindness",
    ]
    # Same repository, other spellings: served from the cache, nothing spent.
    for url in (
        "https://github.com/owner/repo",
        "https://github.com/OWNER/REPO.git",
        "https://github.com/Owner/Repo/",
    ):
        again = _assess(client, url)
        assert again.status_code == 200 and again.headers["x-saica-cache"] == "hit"
        assert again.json() == report
    assert audit.calls == ["https://github.com/Owner/Repo"]
    assert budget.summary() == "calls=1 tokens≈0"
    # Another repository is another audit.
    assert (
        _assess(client, "https://github.com/owner/other").headers["x-saica-cache"]
        == "miss"
    )
    assert len(audit.calls) == 2


def test_day_cache_expires_and_is_bounded() -> None:
    now = [0.0]
    cache = DayCache(ttl=86_400, max_entries=2, clock=lambda: now[0])
    cache.put("a", 1)
    now[0] = 86_399
    assert cache.get("a") == 1
    now[0] = 86_400
    assert cache.get("a") is None
    cache.put("a", 1), cache.put("b", 2), cache.put("c", 3)
    assert (cache.get("a"), cache.get("b"), cache.get("c")) == (None, 2, 3)


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/o/r",
        "https://github.com/../..",
        "https://github.com/o/r/tree/main",
        "http://github.com/o/r",
        "https://github.com.evil.example/o/r",
        "file:///etc/passwd",
        "git@github.com:o/r.git",
        "--upload-pack=touch /tmp/x",
        "   ",
    ],
)
def test_assess_accepts_github_repository_urls_only(tmp_path: Path, url: str) -> None:
    audit = Audit(tmp_path)
    budget = CallBudget(max_calls=10)
    resp = _assess(_client(audit=audit, assess_budget=budget), url)
    assert resp.status_code == 400
    assert "github.com" in resp.json()["detail"] or "repo root" in resp.json()["detail"]
    assert audit.calls == [] and budget.summary() == "calls=0 tokens≈0"


def test_assess_runs_two_audits_at_once_and_refuses_the_third(tmp_path: Path) -> None:
    gate = threading.Event()
    audit = Audit(tmp_path, gate=gate)
    client = _client(audit=audit, assess_budget=CallBudget(max_calls=10))
    with ThreadPoolExecutor(2) as pool:
        running = [
            pool.submit(_assess, client, f"https://github.com/o/r{i}") for i in range(2)
        ]
        deadline = threading.Event()
        for _ in range(100):
            if len(audit.calls) == 2:
                break
            deadline.wait(0.05)
        assert len(audit.calls) == 2
        third = _assess(client, "https://github.com/o/r3")
        assert third.status_code == 429 and third.json()["detail"] == server.BUSY
        assert third.headers["retry-after"] == "5"
        # The event loop is free: health answers while both audits block.
        assert client.get("/health").json() == {"ok": True}
        gate.set()
        assert [f.result(timeout=10).status_code for f in running] == [200, 200]
    assert len(audit.calls) == 2  # the refused one never started
    assert _assess(client, "https://github.com/o/r3").status_code == 200


def test_assess_has_its_own_daily_budget_that_resets(tmp_path: Path) -> None:
    day = [dt.date(2026, 11, 21)]
    audit = Audit(tmp_path)
    client = _client(
        audit=audit,
        assess_budget=DailyBudget(max_calls=2, today=lambda: day[0]),
        budget=CallBudget(max_calls=0),  # Ask's budget is separate and empty
        settings=Settings(assess_per_client_hour=100),
    )
    codes = [
        _assess(client, f"https://github.com/o/r{i}").status_code for i in range(4)
    ]
    assert codes == [200, 200, 429, 429]
    refused = _assess(client, "https://github.com/o/r9").json()
    assert (
        refused["detail"]
        == "The audit budget for today is used up. Please try again tomorrow."
    )
    assert len(audit.calls) == 2
    # A cached report is still served when the budget is gone.
    assert _assess(client, "https://github.com/o/r0").status_code == 200
    day[0] = dt.date(2026, 11, 22)
    assert _assess(client, "https://github.com/o/r5").status_code == 200


def test_assess_per_client_limit(tmp_path: Path) -> None:
    audit = Audit(tmp_path)
    client = _client(
        peer="127.0.0.1",
        audit=audit,
        assess_budget=CallBudget(max_calls=50),
        settings=Settings(assess_per_client_hour=2),
    )
    codes = [
        _assess(
            client,
            f"https://github.com/o/r{i}",
            headers={"X-Forwarded-For": f"9.9.9.{i}, 203.0.113.7"},
        ).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]
    assert len(audit.calls) == 2


def test_assess_wall_clock_limit(tmp_path: Path) -> None:
    gate = threading.Event()
    audit = Audit(tmp_path, gate=gate)
    client = _client(
        audit=audit,
        assess_budget=CallBudget(max_calls=10),
        settings=Settings(
            assess_wall_clock=0.2, assess_concurrency=1, assess_per_client_hour=1000
        ),
    )
    resp = _assess(client)
    assert resp.status_code == 504
    assert resp.json()["detail"] == "The audit took too long and was stopped."
    # The thread is still running, so its slot is still taken.
    assert _assess(client, "https://github.com/o/other").status_code == 429
    gate.set()
    for _ in range(100):
        if _assess(client, "https://github.com/o/other").status_code == 200:
            break
        threading.Event().wait(0.05)
    else:
        pytest.fail("the slot was not released after the thread ended")


@pytest.mark.parametrize(
    "error, status, shown, cached",
    [
        # Will not change within minutes: remembered, so a repeat costs nothing.
        (
            RepoNotFound("GitHub has no public repository at that address."),
            404,
            "GitHub has no public repository at that address.",
            True,
        ),
        (
            RepoTooLarge("The repository's file listing is too large to audit."),
            422,
            "The repository's file listing is too large to audit.",
            True,
        ),
        (
            ValueError("anything"),
            400,
            "repo_url must look like https://github.com/<owner>/<repo>",
            True,
        ),
        # May work on the next try: never remembered.
        (
            FetchUnavailable("GitHub could not be reached."),
            503,
            "GitHub could not be reached.",
            False,
        ),
        (
            RuntimeError("'str' object has no attribute 'get' in /srv/app/x.py"),
            500,
            server.GENERIC_ERROR,
            False,
        ),
        (KeyError("secret-internal-key"), 500, server.GENERIC_ERROR, False),
    ],
)
def test_assess_errors_are_plain(tmp_path: Path, error, status, shown, cached) -> None:
    audit = Audit(tmp_path, error=error)
    client = _client(audit=audit, assess_budget=CallBudget(max_calls=10))
    resp = _assess(client)
    assert resp.status_code == status
    body = resp.json()
    assert body["detail"] == shown and body["request_id"]
    assert "/srv/app" not in resp.text and "secret-internal" not in resp.text
    again = _assess(client)
    assert (again.status_code, again.json()["detail"]) == (status, shown)
    assert len(audit.calls) == (1 if cached else 2)


# ---------------------------------------------------------------------------
# Context builder (on the fixture KG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "node_id,expected_type",
    [
        ("fabrication", "failure_mode"),
        ("guardrails-ai", "tool"),
        ("fixture-taxonomy", "taxonomy"),
        ("fixture-paper-2025", "paper"),
        ("fixture-incident-2025", "incident"),
        ("fixture-recipe", "recipe"),
    ],
)
def test_context_builder_extracts_description_for_each_node_type(
    node_id: str, expected_type: str
) -> None:
    [node] = ask_context.hydrate([(node_id, 0.5)])
    assert (node.id, node.type) == (node_id, expected_type)
    assert node.name and node.snippet
    assert len(node.snippet) <= ask_context.SNIPPET_CHARS


def test_hydrate_skips_ids_that_are_not_citable_nodes() -> None:
    nodes = ask_context.hydrate(
        [
            ("guardrails-ai", 0.9),
            ("definitely-not-a-node", 0.8),  # stale id in the index
            ("fixture-to-saica", 0.75),  # a crosswalk: not a citable kind
            ("../tools/semgrep", 0.7),
            ("fabrication", 0.7),
        ]
    )
    assert [n.id for n in nodes] == ["guardrails-ai", "fabrication"]


def test_tool_facets_come_from_the_validated_node() -> None:
    [node] = ask_context.hydrate([("semgrep", 0.9)])
    assert node.addresses_failure_modes == (
        "security_vulnerability",
        "supply_chain_attack",
    )
    assert (node.control_paradigm, node.temporal_phase, node.autonomy_level) == (
        "detection",
        "post_generation",
        "fully_autonomous",
    )
    assert node.integration_surfaces == ("cli", "ci_app", "library")
    block = ask_context.render_context_block([node])
    assert "[semgrep] (tool) Semgrep" in block
    assert "addresses=security_vulnerability,supply_chain_attack" in block


def test_build_prompt_contains_instructions_and_question() -> None:
    nodes = ask_context.hydrate([("fabrication", 0.9)])
    prompt = ask_context.build_prompt("What is fabrication?", nodes)
    assert "What is fabrication?" in prompt
    assert "cite" in prompt and "in brackets" in prompt
    assert "The KG doesn't have this information." in prompt


def test_no_prompt_rule_calls_a_catalog_tool_the_agent_itself() -> None:
    """Rule 4 told the model that ``recovery`` + ``fully_autonomous`` tools
    "are themselves coding agents". In the catalog those are sandboxes
    (review H5 / SV-16); the fixture's ``daytona`` has exactly that pair."""
    tools = kg.load_tools()
    sandbox = tools["daytona"]
    assert (sandbox["control_paradigm"], sandbox["autonomy_level"]) == (
        "recovery",
        "fully_autonomous",
    )
    for question in ("how do I contain an agent?", "which sandbox fits a ci pipeline?"):
        prompt = ask_context.build_prompt(
            question, ask_context.hydrate([("daytona", 0.9)])
        )
        rules = prompt[: prompt.index("Context:")]
        for phrase in (
            "agent itself",
            "themselves coding agents",
            "CIRCULAR",
            "fully_autonomous",
            "recovery",
        ):
            assert phrase not in rules, phrase
        # The tool's own facets are still shown as data, below the rules.
        assert "paradigm=recovery" in prompt and "[daytona]" in prompt
    # Rules are numbered without a hole after the deletion.
    numbers = [line.split(".")[0] for line in rules.splitlines() if line[:1].isdigit()]
    assert numbers == ["1", "2", "3", "4", "5", "6"]


def test_pipeline_questions_add_declared_pipeline_friendly_tools() -> None:
    calls: list[tuple[int, str | None]] = []

    def find(question, k, node_type=None):
        calls.append((k, node_type))
        if node_type == "tool":
            return [
                ("litellm", 0.6),
                ("fabrication", 0.5),
                ("semgrep", 0.4),
                ("no-such-tool", 0.3),
            ]
        return [("fabrication", 0.9)]

    hits = ask_context.hybrid_retrieve(
        "which library fits my ci pipeline?", 5, find_similar=find
    )
    assert [h[0] for h in hits] == ["fabrication", "litellm", "semgrep"]
    assert calls == [(5, None), (20, "tool")]
    calls.clear()
    assert ask_context.hybrid_retrieve(
        "what is fabrication?", 5, find_similar=find
    ) == [("fabrication", 0.9)]
    assert calls == [(5, None)]


# ---------------------------------------------------------------------------
# Follow-up after the independent review (2026-11-21)
# ---------------------------------------------------------------------------


def test_missing_repositories_do_not_spend_the_daily_budget(tmp_path: Path) -> None:
    """Budget 3, three requests for repositories that do not exist: every
    later caller got 429."""
    audit = Audit(
        tmp_path, error=RepoNotFound("GitHub has no public repository at that address.")
    )
    budget = CallBudget(max_calls=3)
    client = _client(
        audit=audit, assess_budget=budget, settings=Settings(assess_per_client_hour=100)
    )
    codes = [
        _assess(client, f"https://github.com/o/missing{i}").status_code
        for i in range(6)
    ]
    assert codes == [404] * 6
    assert budget.summary() == "calls=0 tokens≈0"
    audit.error = None
    assert _assess(client, "https://github.com/o/real").status_code == 200
    assert budget.summary() == "calls=1 tokens≈0"


def test_negative_results_are_cached_for_minutes(tmp_path: Path) -> None:
    audit = Audit(
        tmp_path, error=RepoNotFound("GitHub has no public repository at that address.")
    )
    now = [1000.0]
    client = _client(
        audit=audit,
        assess_budget=CallBudget(max_calls=10),
        settings=Settings(assess_per_client_hour=100),
        clock=lambda: now[0],
    )
    first = _assess(client, "https://github.com/o/gone")
    again = _assess(client, "https://github.com/O/Gone.git")
    assert (first.status_code, again.status_code) == (404, 404)
    assert again.json()["detail"] == first.json()["detail"]
    assert again.headers["x-saica-cache"] == "hit" and len(audit.calls) == 1
    # A repository created in the meantime is found once the entry has expired.
    audit.error = None
    now[0] += 299
    assert _assess(client, "https://github.com/o/gone").status_code == 404
    now[0] += 2
    assert _assess(client, "https://github.com/o/gone").status_code == 200
    assert len(audit.calls) == 2


def test_an_audit_that_cannot_be_read_within_limits_is_a_plain_422_and_cached(
    tmp_path: Path,
) -> None:
    from pipeline.audit.analyzer import DetectionAborted

    text = "The repository's files could not be analysed within the time limit."
    audit = Audit(tmp_path, error=DetectionAborted(text))
    budget = CallBudget(max_calls=10)
    client = _client(audit=audit, assess_budget=budget)
    responses = [_assess(client, "https://github.com/o/bomb") for _ in range(3)]
    assert [r.status_code for r in responses] == [422, 422, 422]
    assert responses[0].json()["detail"] == text
    # The hostile repository is fetched and parsed once, not once per request.
    assert len(audit.calls) == 1
    # It did cost a fetch and a process: this one stays counted.
    assert budget.summary() == "calls=1 tokens≈0"


def test_a_result_that_arrives_after_the_timeout_is_kept(tmp_path: Path) -> None:
    gate = threading.Event()
    audit = Audit(tmp_path, gate=gate)
    client = _client(
        audit=audit,
        assess_budget=CallBudget(max_calls=10),
        settings=Settings(
            assess_wall_clock=0.2, assess_per_client_hour=1000, assess_concurrency=1
        ),
    )
    assert _assess(client).status_code == 504
    gate.set()
    for _ in range(100):
        late = _assess(client)
        if late.status_code == 200:
            break
        threading.Event().wait(0.05)
    assert late.status_code == 200 and late.headers["x-saica-cache"] == "hit"
    assert len(audit.calls) == 1  # the slow audit was not repeated


def test_value_error_text_from_inside_the_audit_is_not_shown(tmp_path: Path) -> None:
    audit = Audit(
        tmp_path, error=ValueError("internal ValueError text /private/path token=xyz")
    )
    resp = _assess(_client(audit=audit, assess_budget=CallBudget(max_calls=5)))
    assert resp.status_code == 400
    assert (
        resp.json()["detail"]
        == "repo_url must look like https://github.com/<owner>/<repo>"
    )
    assert "token=xyz" not in resp.text


def test_tokens_of_an_answer_that_came_after_the_timeout_are_recorded() -> None:
    gate, started = threading.Event(), threading.Event()

    def slow_model(prompt: str):
        started.set()
        assert gate.wait(timeout=10)
        return "late", _response(tokens=4321)

    budget = CallBudget(max_calls=10)
    client = _client(
        kimi_call=slow_model, budget=budget, settings=Settings(ask_wall_clock=0.2)
    )
    assert _ask(client).status_code == 504
    assert budget.summary() == "calls=1 tokens≈0"
    gate.set()
    for _ in range(100):
        if budget.summary() == "calls=1 tokens≈4321":
            break
        threading.Event().wait(0.05)
    assert budget.summary() == "calls=1 tokens≈4321"
