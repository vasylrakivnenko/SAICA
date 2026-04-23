"""Tests for :mod:`pipeline.cost_caps` and its integration points.

Three layers exercised here:

1. :class:`CallBudget` arithmetic in isolation — increments, caps, summary.
2. Kimi's ``extract_tool`` wiring — a mocked OpenAI client returns a valid
   tool-call response; the budget must have recorded one call + the
   ``usage.total_tokens`` delta.
3. Perplexity's ``search`` wiring — a stub HTTP session is injected; the
   budget must be consumed exactly once per HTTP call, and a pre-hit
   budget must raise ``CostCapExceeded`` *before* dispatching.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from pipeline.cost_caps import CallBudget, CostCapExceeded


# ---------------------------------------------------------------------------
# Layer 1: CallBudget arithmetic
# ---------------------------------------------------------------------------


def test_budget_consume_increments() -> None:
    """Each consume increments calls + tokens; no cap means no raise."""
    b = CallBudget()
    b.consume(call=True, tokens=100)
    b.consume(call=True, tokens=50)
    b.consume(call=False, tokens=10)
    # After 2 calls + 160 tokens
    assert "calls=2" in b.summary()
    assert "tokens" in b.summary()
    assert "160" in b.summary()


def test_budget_raises_when_max_calls_exceeded() -> None:
    """The call that trips max_calls raises; earlier calls succeed."""
    b = CallBudget(max_calls=2)
    b.consume(call=True)
    b.consume(call=True)
    with pytest.raises(CostCapExceeded, match="max_calls=2"):
        b.consume(call=True)
    # The summary reflects the call that tripped the cap.
    assert "calls=3" in b.summary()


def test_budget_raises_when_tokens_exceeded() -> None:
    """Token tally is a soft running total; ``max_tokens_estimate`` caps it."""
    b = CallBudget(max_tokens_estimate=1000)
    b.consume(call=True, tokens=400)
    b.consume(call=True, tokens=400)
    # 800 < 1000: still fine.
    with pytest.raises(CostCapExceeded, match="max_tokens_estimate=1000"):
        b.consume(call=True, tokens=500)  # pushes to 1300


def test_budget_summary_formats() -> None:
    """Summary is a single short line fit for logs + the CLI's exit print."""
    b = CallBudget()
    assert b.summary() == "calls=0 tokens≈0"
    b.consume(call=True, tokens=42)
    assert b.summary() == "calls=1 tokens≈42"


def test_budget_zero_max_calls_raises_immediately() -> None:
    """``--max-calls 0`` must trip on the first real call (CLI exit-3 path)."""
    b = CallBudget(max_calls=0)
    with pytest.raises(CostCapExceeded):
        b.consume(call=True, tokens=0)


def test_budget_negative_tokens_are_clamped() -> None:
    """Defensive: never let a bogus negative token count shrink the total."""
    b = CallBudget(max_tokens_estimate=100)
    b.consume(call=True, tokens=50)
    b.consume(call=True, tokens=-1_000_000)  # clamped to 0
    # If clamping worked, we're still at 50 tokens and no raise.
    assert "50" in b.summary()


# ---------------------------------------------------------------------------
# Layer 2: Kimi extract_tool integration
# ---------------------------------------------------------------------------


def _fake_tool_args() -> dict:
    """Minimal ToolExtraction-shaped payload. Matches test_kimi_prompt helper."""
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


def _mock_kimi_client(total_tokens: int = 1234) -> MagicMock:
    """MagicMock OpenAI client whose response includes a ``usage`` block."""
    client = MagicMock()
    choice = MagicMock()
    tool_call = MagicMock()
    tool_call.function = MagicMock()
    tool_call.function.name = "record_tool"
    tool_call.function.arguments = json.dumps(_fake_tool_args())
    choice.message = MagicMock()
    choice.message.tool_calls = [tool_call]
    choice.message.content = ""
    response = MagicMock()
    response.choices = [choice]
    response.usage = MagicMock(total_tokens=total_tokens)
    client.chat.completions.create.return_value = response
    return client


def test_extract_tool_respects_budget() -> None:
    """A successful call records exactly one call + the reported tokens."""
    from pipeline.extract import kimi

    client = _mock_kimi_client(total_tokens=1234)
    budget = CallBudget(max_calls=5)
    row = {"source_url": "https://github.com/acme/x", "readme": "hi"}

    kimi.extract_tool(row, client=client, budget=budget)

    # Exactly one wire call was made.
    assert client.chat.completions.create.call_count == 1
    # And exactly one budget tick, with the token estimate surfaced.
    assert "calls=1" in budget.summary()
    assert "1234" in budget.summary()


def test_extract_tool_raises_when_budget_exhausted() -> None:
    """A zero-budget run must raise CostCapExceeded after the wire call records.

    The current implementation charges the budget after a successful HTTP
    round-trip; so a ``max_calls=0`` budget on ``extract_tool`` raises
    CostCapExceeded on the first call. The CLI catches this to exit 3.
    """
    from pipeline.extract import kimi

    client = _mock_kimi_client()
    budget = CallBudget(max_calls=0)
    row = {"source_url": "https://github.com/acme/x", "readme": "hi"}

    with pytest.raises(CostCapExceeded):
        kimi.extract_tool(row, client=client, budget=budget)


# ---------------------------------------------------------------------------
# Layer 3: Perplexity search integration
# ---------------------------------------------------------------------------


class _StubResp:
    def __init__(self, status_code: int = 200, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {
            "search_results": [
                {"url": "https://example.com/a", "title": "A", "snippet": "s"},
            ]
        }

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


class _StubSession:
    def __init__(self, resp: _StubResp):
        self._resp = resp
        self.calls = 0

    def post(self, url, *, json, headers, timeout):
        self.calls += 1
        return self._resp


def test_perplexity_search_respects_budget(monkeypatch) -> None:
    """Each HTTP attempt consumes once; a pre-hit budget skips the request."""
    from pipeline.sources import perplexity

    # Keep the env-load path quiet and make the API-key check pass.
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-key")
    monkeypatch.setattr(perplexity, "load_env", lambda: None)

    # Also stub out insert_raw_result so we don't hit the DB.
    import pipeline.db as db_mod
    monkeypatch.setattr(db_mod, "insert_raw_result", lambda *a, **kw: 1)

    session = _StubSession(_StubResp())
    budget = CallBudget(max_calls=3)

    perplexity.search("hello", session=session, budget=budget)
    assert session.calls == 1
    assert "calls=1" in budget.summary()

    # A second call is still under the cap.
    perplexity.search("hello again", session=session, budget=budget)
    assert session.calls == 2

    # Drain the budget. Third call was fine; fourth trips the cap BEFORE
    # dispatching — session.calls stays at 3.
    perplexity.search("once more", session=session, budget=budget)
    assert session.calls == 3

    with pytest.raises(CostCapExceeded):
        perplexity.search("over the line", session=session, budget=budget)
    assert session.calls == 3, "budget must gate dispatch when exhausted"
