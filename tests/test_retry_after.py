"""Tests for Retry-After handling in Kimi + Cohere retry loops.

These assert the fix for the previous bug where ``"429" in str(exc)`` was
used as a rate-limit classifier and backoff was always exp-backoff — even
when the server explicitly told us how long to wait.

The Kimi fix parses ``.response.headers["Retry-After"]`` from
``openai.RateLimitError``; Cohere reads ``resp.headers["Retry-After"]``
from the ``requests`` response. Both clamp to 120s.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _valid_tool_args() -> dict:
    """Tool-call payload that matches ToolExtraction.model_validate()."""
    def cf(value, confidence: float = 0.9) -> dict:
        return {"value": value, "confidence": confidence, "evidence": []}

    return {
        "proposed_id": cf("x"),
        "name": cf("X"),
        "tagline": cf("t"),
        "description": cf("d"),
        "repository_url": cf("https://github.com/x/x"),
        "license_spdx": cf("MIT"),
        "control_paradigm": cf("detection", 0.6),
        "temporal_phase": cf("post_generation", 0.6),
        "autonomy_level": cf(None, 0.2),
        "addresses_failure_modes": cf([], 0.5),
        "locus_of_control": cf([], 0.5),
        "inclusion_rationale": cf("r"),
        "overall_confidence": 0.7,
    }


def _success_response():
    """MagicMock response matching what _call_kimi_function expects."""
    choice = MagicMock()
    tool_call = MagicMock()
    tool_call.function = MagicMock()
    tool_call.function.name = "record_tool"
    tool_call.function.arguments = json.dumps(_valid_tool_args())
    choice.message = MagicMock()
    choice.message.tool_calls = [tool_call]
    choice.message.content = ""
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(total_tokens=42)
    return resp


class _FakeHttpxResponse:
    """Minimal stand-in for httpx.Response attached to OpenAI errors.

    The OpenAI SDK's ``APIStatusError.__init__`` passes ``response.request``
    up to ``APIError.__init__``, so we need a ``.request`` attribute even
    if our extractor never touches it.
    """

    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self.request = object()  # sentinel; never introspected


def _rate_limit_error(retry_after: str | None = None):
    """Build an ``openai.RateLimitError`` with an optional Retry-After header."""
    from openai import RateLimitError

    headers = {"Retry-After": retry_after} if retry_after else {}
    response = _FakeHttpxResponse(429, headers=headers)
    return RateLimitError("rate limited", response=response, body=None)


# ---------------------------------------------------------------------------
# Kimi
# ---------------------------------------------------------------------------


def test_kimi_honors_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """On 429 with Retry-After, the retry sleeps for the server-specified time."""
    from pipeline.extract import kimi

    client = MagicMock()
    # First attempt raises 429 with Retry-After=7; second attempt succeeds.
    client.chat.completions.create.side_effect = [
        _rate_limit_error(retry_after="7"),
        _success_response(),
    ]

    slept: list[float] = []
    monkeypatch.setattr(kimi.time, "sleep", lambda s: slept.append(s))

    row = {"source_url": "https://github.com/acme/x", "readme": "hi"}
    kimi.extract_tool(row, client=client)

    assert client.chat.completions.create.call_count == 2
    assert slept == [7.0], (
        f"expected one sleep of 7s (Retry-After) — got {slept}"
    )


def test_kimi_falls_back_to_backoff_without_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without Retry-After, exp-backoff is used (≥ BASE_BACKOFF_SECONDS)."""
    from pipeline.extract import kimi

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _rate_limit_error(retry_after=None),
        _success_response(),
    ]

    slept: list[float] = []
    monkeypatch.setattr(kimi.time, "sleep", lambda s: slept.append(s))
    # Stabilise jitter so the assertion is precise.
    monkeypatch.setattr(kimi.random, "uniform", lambda lo, hi: 0.0)

    row = {"source_url": "https://github.com/acme/y", "readme": "hi"}
    kimi.extract_tool(row, client=client)

    assert len(slept) == 1
    # First attempt backoff = BASE * 2**0 = 2.0s; must not be a Retry-After
    # value (there was none).
    assert slept[0] == pytest.approx(kimi.BASE_BACKOFF_SECONDS)


def test_kimi_retry_after_is_clamped_to_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hostile Retry-After (e.g. 9999s) is clamped to MAX_RETRY_AFTER_SECONDS."""
    from pipeline.extract import kimi

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _rate_limit_error(retry_after="9999"),
        _success_response(),
    ]
    slept: list[float] = []
    monkeypatch.setattr(kimi.time, "sleep", lambda s: slept.append(s))

    row = {"source_url": "https://github.com/acme/z", "readme": "hi"}
    kimi.extract_tool(row, client=client)
    assert slept == [kimi.MAX_RETRY_AFTER_SECONDS]


# ---------------------------------------------------------------------------
# Cohere
# ---------------------------------------------------------------------------


class _CohereResp:
    """Stub for the ``requests.Response`` shape CohereRerankClient consumes."""

    def __init__(self, status_code: int, body: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}
        self.text = str(self._body)

    def json(self):
        return self._body


class _CohereSession:
    def __init__(self, responses: list[_CohereResp]):
        self._responses = list(responses)
        self.calls = 0

    def post(self, url, *, json, headers, timeout):
        self.calls += 1
        return self._responses.pop(0)


def test_cohere_honors_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429 with Retry-After on Cohere triggers a sleep of that many seconds."""
    from pipeline.rerank import cohere

    session = _CohereSession([
        _CohereResp(429, body={}, headers={"Retry-After": "4"}),
        _CohereResp(
            200,
            body={"results": [{"index": 0, "relevance_score": 0.9}]},
        ),
    ])
    client = cohere.CohereRerankClient(
        endpoint="https://example/rerank",
        api_key="k",
        session=session,
    )

    slept: list[float] = []
    monkeypatch.setattr(cohere.time, "sleep", lambda s: slept.append(s))

    results = client.rerank(query="q", documents=["doc"])
    assert results == [{"index": 0, "relevance_score": 0.9}]
    assert session.calls == 2
    assert slept == [4.0]


def test_cohere_falls_back_to_backoff_without_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without Retry-After on a 429, the code uses exp-backoff."""
    from pipeline.rerank import cohere

    session = _CohereSession([
        _CohereResp(429, body={}, headers={}),
        _CohereResp(
            200,
            body={"results": [{"index": 0, "relevance_score": 0.5}]},
        ),
    ])
    client = cohere.CohereRerankClient(
        endpoint="https://example/rerank",
        api_key="k",
        session=session,
    )

    slept: list[float] = []
    monkeypatch.setattr(cohere.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(cohere.random, "uniform", lambda lo, hi: 0.0)

    client.rerank(query="q", documents=["doc"])
    assert session.calls == 2
    assert len(slept) == 1
    assert slept[0] == pytest.approx(cohere.BASE_BACKOFF_SECONDS)


def test_cohere_retry_after_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry-After > MAX_RETRY_AFTER_SECONDS is clamped."""
    from pipeline.rerank import cohere

    session = _CohereSession([
        _CohereResp(503, body={}, headers={"Retry-After": "9999"}),
        _CohereResp(
            200,
            body={"results": []},
        ),
    ])
    client = cohere.CohereRerankClient(
        endpoint="https://example/rerank",
        api_key="k",
        session=session,
    )
    slept: list[float] = []
    monkeypatch.setattr(cohere.time, "sleep", lambda s: slept.append(s))

    client.rerank(query="q", documents=["doc"])
    assert slept == [cohere.MAX_RETRY_AFTER_SECONDS]
