"""Tests for the /ask FastAPI backend + context builder.

All HTTP is exercised via Starlette's ``TestClient``; no real Kimi or
retrieval calls are made. The real ``find_similar`` and Kimi client are
replaced via ``create_app``'s injection seams.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pipeline.ask import context as ask_context
from pipeline.ask.server import create_app
from pipeline.cost_caps import CallBudget


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _fake_usage(total: int = 250) -> Any:
    return SimpleNamespace(total_tokens=total, prompt_tokens=200, completion_tokens=50)


def _fake_kimi_response(answer: str, *, tokens: int = 250, model: str = "Kimi-K2.5") -> Any:
    """Shape-of-an-OpenAI-response stub with just the fields our code reads."""
    return SimpleNamespace(usage=_fake_usage(tokens), model=model)


def _make_find_similar(hits: list[tuple[str, float]]):
    def _fake(question: str, k: int) -> list[tuple[str, float]]:
        return hits[:k]

    return _fake


def _make_kimi_call(answer: str, *, tokens: int = 250):
    captured: dict[str, Any] = {}

    def _fake(prompt: str) -> tuple[str, Any]:
        captured["prompt"] = prompt
        return answer, _fake_kimi_response(answer, tokens=tokens)

    _fake.captured = captured  # type: ignore[attr-defined]
    return _fake


# ---------------------------------------------------------------------------
# /ask happy path
# ---------------------------------------------------------------------------


def test_ask_returns_answer_and_citations() -> None:
    """End-to-end: retrieval + context build + fake Kimi + JSON response."""
    hits = [
        ("guardrails-ai", 0.81),
        ("fabrication", 0.77),
        ("owasp-agentic-top-10-2026", 0.72),
        ("spracklen-2024-we-have-a-package", 0.68),
    ]
    fake_kimi = _make_kimi_call(
        "Guardrails AI catches hallucinated output post-generation "
        "[guardrails-ai]. Fabrication is the canonical failure mode "
        "[fabrication].",
        tokens=310,
    )
    app = create_app(
        find_similar=_make_find_similar(hits),
        kimi_call=fake_kimi,
        budget=CallBudget(max_calls=5),
    )
    client = TestClient(app)

    resp = client.post("/ask", json={"question": "what prevents hallucinations?"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "Guardrails AI" in body["answer"]
    assert "[guardrails-ai]" in body["answer"]
    assert body["kimi_tokens_used"] == 310

    cits = body["citations"]
    # Retrieval returned 4 ids that all exist in `data/`; hydration should keep all 4.
    assert {c["id"] for c in cits} == {h[0] for h in hits}
    # Citation URLs should point at the right collection pages.
    urls = {c["id"]: c["url"] for c in cits}
    assert urls["guardrails-ai"] == "/tools/guardrails-ai"
    assert urls["fabrication"] == "/failure-modes/fabrication"
    assert urls["owasp-agentic-top-10-2026"] == "/taxonomies/owasp-agentic-top-10-2026"
    assert urls["spracklen-2024-we-have-a-package"] == "/papers/spracklen-2024-we-have-a-package"

    # The prompt we handed to Kimi must carry the context blocks + question
    # so a failure where we silently drop context is caught here.
    prompt = fake_kimi.captured["prompt"]  # type: ignore[attr-defined]
    assert "what prevents hallucinations?" in prompt
    assert "[guardrails-ai]" in prompt
    assert "[fabrication]" in prompt


def test_ask_empty_question_returns_400() -> None:
    """Whitespace-only and zero-length questions both 400."""
    app = create_app(
        find_similar=_make_find_similar([]),
        kimi_call=_make_kimi_call("should-not-be-called"),
    )
    client = TestClient(app)

    # Empty string is rejected by pydantic's min_length=1 => 422.
    resp_empty = client.post("/ask", json={"question": ""})
    assert resp_empty.status_code in (400, 422)

    # Whitespace-only gets past pydantic but is rejected in the handler.
    resp_ws = client.post("/ask", json={"question": "   "})
    assert resp_ws.status_code == 400
    assert "blank" in resp_ws.json()["detail"].lower()


def test_ask_kimi_failure_returns_500_with_message() -> None:
    """When the Kimi call raises, the client sees a 500 with a useful detail."""

    def exploding_kimi(prompt: str) -> tuple[str, Any]:
        raise RuntimeError("azure endpoint returned 503")

    app = create_app(
        find_similar=_make_find_similar([("guardrails-ai", 0.9)]),
        kimi_call=exploding_kimi,
        budget=CallBudget(max_calls=5),
    )
    client = TestClient(app)

    resp = client.post("/ask", json={"question": "anything"})
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "kimi" in detail.lower()
    assert "503" in detail


def test_ask_respects_budget() -> None:
    """Budget with max_calls=1 lets the first /ask through and 429s the second."""
    fake_kimi = _make_kimi_call("fine")
    app = create_app(
        find_similar=_make_find_similar([("guardrails-ai", 0.9)]),
        kimi_call=fake_kimi,
        budget=CallBudget(max_calls=1),
    )
    client = TestClient(app)

    first = client.post("/ask", json={"question": "q1"})
    assert first.status_code == 200

    second = client.post("/ask", json={"question": "q2"})
    assert second.status_code == 429


# ---------------------------------------------------------------------------
# Context builder — one test per node type so a regression in a single
# hydrator can't silently take down just that page's citations.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "node_id,expected_type",
    [
        ("fabrication", "failure_mode"),
        ("guardrails-ai", "tool"),
        ("owasp-agentic-top-10-2026", "taxonomy"),
        ("spracklen-2024-we-have-a-package", "paper"),
        ("cursor-support-bot-fabricated-policy-2025", "incident"),
    ],
)
def test_context_builder_extracts_description_for_each_node_type(
    node_id: str, expected_type: str
) -> None:
    """Each of the four shipping node types yields a non-empty snippet."""
    [node] = ask_context.hydrate([(node_id, 0.5)])
    assert node.id == node_id
    assert node.type == expected_type
    assert node.name  # non-empty display name
    assert node.snippet  # non-empty descriptive text
    # Snippet is bounded so we never ship a whole README to Kimi.
    assert len(node.snippet) <= ask_context.SNIPPET_CHARS


def test_hydrate_skips_unknown_node_ids() -> None:
    """Retrieval returning a stale id (pre-rename, typo) is dropped, not raised."""
    nodes = ask_context.hydrate(
        [("guardrails-ai", 0.9), ("definitely-not-a-node", 0.8), ("fabrication", 0.7)]
    )
    ids = [n.id for n in nodes]
    assert ids == ["guardrails-ai", "fabrication"]


def test_render_context_block_includes_ids_in_brackets() -> None:
    """The context block must surface the id in the exact [id] shape the LLM will echo."""
    nodes = ask_context.hydrate([("guardrails-ai", 0.9)])
    block = ask_context.render_context_block(nodes)
    assert "[guardrails-ai]" in block
    # The renderer should include the human name too so Kimi can explain what the id refers to.
    assert "Guardrails AI" in block


def test_build_prompt_contains_instructions_and_question() -> None:
    """Regression guard against someone accidentally stripping the cite-in-brackets instruction."""
    nodes = ask_context.hydrate([("fabrication", 0.9)])
    prompt = ask_context.build_prompt("What is fabrication?", nodes)
    assert "What is fabrication?" in prompt
    # The exact phrasing has evolved (now "cites a node id"), but the
    # cite-in-brackets convention must remain.
    assert "cite" in prompt and "in brackets" in prompt
    assert "The KG doesn't have this information." in prompt


# ---------------------------------------------------------------------------
# Health endpoint — cheap sanity check for the create_app wiring
# ---------------------------------------------------------------------------


def test_health_endpoint() -> None:
    app = create_app(
        find_similar=_make_find_similar([]),
        kimi_call=_make_kimi_call("unused"),
    )
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
