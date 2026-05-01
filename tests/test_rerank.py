"""Unit tests for ``pipeline.rerank.*``.

All HTTP is stubbed. The live Azure call is exercised manually via the CLI
with ``--limit 5 --top 5`` — see the task brief's verify step.
"""

from __future__ import annotations

from typing import Optional

import pytest

from pipeline.rerank.cohere import (
    CohereRerankClient,
    compose_document,
    rerank_candidates,
)
from pipeline.rerank.queries import SUPERVISION_QUERIES, RerankQuery


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeClient:
    """In-memory stand-in for CohereRerankClient.

    ``score_fn(query_text, doc_text) -> float`` computes the relevance score
    for a given (query, document) pair; the fake builds the ``results`` list
    in index order. Call count is exposed so tests can assert cost-cap
    (one HTTP call per query, not per (query, doc) pair).
    """

    def __init__(self, score_fn=None):
        self.calls: list[dict] = []
        self.score_fn = score_fn or (lambda q, d: 0.5)
        self.last_headers: dict[str, str] = {}

    def rerank(self, *, query, documents, top_n=None):
        self.calls.append(
            {"query": query, "documents": list(documents), "top_n": top_n}
        )
        results = [
            {"index": i, "relevance_score": float(self.score_fn(query, doc))}
            for i, doc in enumerate(documents)
        ]
        results.sort(key=lambda r: r["relevance_score"], reverse=True)
        if top_n is not None:
            results = results[:top_n]
        return results


# ---------------------------------------------------------------------------
# compose_document
# ---------------------------------------------------------------------------


def test_compose_document_name_summary_readme():
    row = {
        "id": 1,
        "name": "ai-infra-guard",
        "summary": "Guardrails for agentic coding tools.",
        "source_url": "https://github.com/example/ai-infra-guard",
    }
    doc = compose_document(row, readme_lookup=lambda url: "README body here")
    assert "ai-infra-guard" in doc
    assert "Guardrails for agentic coding tools." in doc
    assert "README body here" in doc


def test_compose_document_name_only_fallback():
    """A candidate with neither summary nor README must still produce text."""
    row = {"id": 1, "name": "last-layer"}
    doc = compose_document(row)
    assert doc.strip() == "last-layer"


def test_compose_document_empty_row_is_empty_string():
    doc = compose_document({"id": 1})
    assert doc == ""


def test_compose_document_respects_max_chars():
    row = {
        "id": 1,
        "name": "x",
        "summary": "y",
        "readme": "z" * 100_000,
    }
    doc = compose_document(row, max_chars=5000)
    assert len(doc) == 5000


def test_compose_document_readme_lookup_errors_are_swallowed():
    def bad_lookup(_url: str) -> Optional[str]:
        raise RuntimeError("network down")

    row = {"id": 1, "name": "foo", "source_url": "https://example.com"}
    doc = compose_document(row, readme_lookup=bad_lookup)
    assert doc.strip() == "foo"


# ---------------------------------------------------------------------------
# rerank_candidates
# ---------------------------------------------------------------------------


def test_rerank_candidates_happy_path():
    rows = [
        {"id": 10, "name": "sandbox-x", "summary": "runs agent code safely"},
        {"id": 11, "name": "fab-shield", "summary": "detects hallucinated packages"},
        {"id": 12, "name": "random-thing", "summary": "unrelated"},
    ]
    queries = [
        RerankQuery(id="general", text="agent supervision"),
        RerankQuery(id="fabrication", text="hallucinated packages"),
    ]

    def scorer(q: str, d: str) -> float:
        if "hallucinated" in q and "hallucinated" in d:
            return 0.95
        if "supervision" in q and "agent" in d:
            return 0.60
        return 0.05

    client = FakeClient(score_fn=scorer)
    scores = rerank_candidates(rows, queries, client=client)

    assert len(scores) == 3
    assert [s.candidate_id for s in scores][0] == 11  # fab-shield wins

    fab = next(s for s in scores if s.candidate_id == 11)
    assert fab.best_query == "fabrication"
    assert fab.score_max == pytest.approx(0.95)


def test_rerank_candidates_aggregation_max_and_mean():
    rows = [{"id": 1, "name": "a", "summary": "x"}]
    queries = [
        RerankQuery(id="q1", text="first"),
        RerankQuery(id="q2", text="second"),
        RerankQuery(id="q3", text="third"),
    ]
    score_map = {"first": 0.1, "second": 0.9, "third": 0.5}
    client = FakeClient(score_fn=lambda q, d: score_map[q])
    [score] = rerank_candidates(rows, queries, client=client)

    assert score.score_max == pytest.approx(0.9)
    assert score.score_mean == pytest.approx((0.1 + 0.9 + 0.5) / 3)
    assert score.best_query == "q2"
    assert score.per_query == {
        "q1": pytest.approx(0.1),
        "q2": pytest.approx(0.9),
        "q3": pytest.approx(0.5),
    }


def test_rerank_candidates_empty_list_no_http():
    client = FakeClient()
    out = rerank_candidates([], client=client)
    assert out == []
    assert client.calls == []


def test_rerank_candidates_cost_cap_is_per_query_not_per_doc():
    """Contract: len(HTTP calls) == len(queries), regardless of doc count."""
    rows = [{"id": i, "name": f"tool-{i}", "summary": "x"} for i in range(25)]
    queries = [
        RerankQuery(id="q_alpha", text="alpha"),
        RerankQuery(id="q_beta", text="beta"),
        RerankQuery(id="q_charlie", text="charlie"),
    ]
    client = FakeClient()
    rerank_candidates(rows, queries, client=client)

    assert len(client.calls) == len(queries) == 3
    # Each call must bundle all 25 documents.
    for call in client.calls:
        assert len(call["documents"]) == 25


def test_rerank_candidates_default_uses_supervision_queries():
    rows = [{"id": 1, "name": "agent-guard", "summary": "guardrails"}]
    client = FakeClient(score_fn=lambda q, d: 0.3)
    scores = rerank_candidates(rows, client=client)

    assert len(client.calls) == len(SUPERVISION_QUERIES)
    expected_ids = {q.id for q in SUPERVISION_QUERIES}
    assert set(scores[0].per_query.keys()) == expected_ids


def test_rerank_candidates_sorted_by_score_max_desc():
    rows = [
        {"id": 1, "name": "low"},
        {"id": 2, "name": "high"},
        {"id": 3, "name": "mid"},
    ]
    score_lookup = {"low": 0.1, "high": 0.9, "mid": 0.5}
    client = FakeClient(score_fn=lambda q, d: score_lookup[d.strip()])
    scores = rerank_candidates(
        rows,
        [RerankQuery(id="qa", text="anything")],
        client=client,
    )
    assert [s.candidate_id for s in scores] == [2, 3, 1]


def test_rerank_candidates_passes_top_n_through():
    rows = [{"id": i, "name": f"t{i}"} for i in range(4)]
    client = FakeClient()
    rerank_candidates(
        rows,
        [RerankQuery(id="qa", text="x")],
        client=client,
        top_n=2,
    )
    assert client.calls[0]["top_n"] == 2


def test_rerank_candidates_missing_result_yields_zero_score():
    """If Cohere omits a doc from results entirely, aggregate gracefully."""

    class SparseClient:
        def __init__(self):
            self.last_headers: dict[str, str] = {}

        def rerank(self, *, query, documents, top_n=None):
            # Only return index=0; doc index 1 is missing from results.
            return [{"index": 0, "relevance_score": 0.42}]

    rows = [
        {"id": 100, "name": "present", "summary": "s"},
        {"id": 101, "name": "absent", "summary": "s"},
    ]
    scores = rerank_candidates(
        rows,
        [RerankQuery(id="gq", text="x")],
        client=SparseClient(),
    )
    by_id = {s.candidate_id: s for s in scores}
    assert by_id[100].score_max == pytest.approx(0.42)
    assert by_id[101].score_max == 0.0
    assert by_id[101].score_mean == 0.0
    assert by_id[101].best_query == ""


# ---------------------------------------------------------------------------
# HTTP client surface (no network; stub requests.Session)
# ---------------------------------------------------------------------------


class _StubResp:
    def __init__(
        self, status_code: int, json_body: dict, headers: Optional[dict] = None
    ):
        self.status_code = status_code
        self._body = json_body
        self.headers = headers or {}
        self.text = str(json_body)

    def json(self):
        return self._body


class _StubSession:
    def __init__(self, response: _StubResp):
        self.response = response
        self.last_call: dict = {}

    def post(self, url, *, json, headers, timeout):
        self.last_call = {
            "url": url,
            "json": json,
            "headers": headers,
            "timeout": timeout,
        }
        return self.response


def test_cohere_client_sends_api_key_header_not_bearer():
    resp = _StubResp(
        200,
        {"results": [{"index": 0, "relevance_score": 0.7}]},
        headers={"x-ratelimit-remaining": "249"},
    )
    session = _StubSession(resp)
    client = CohereRerankClient(
        endpoint="https://example/rerank",
        api_key="k-abc",
        model="Cohere-rerank-v4.0-pro",
        session=session,
    )
    results = client.rerank(query="q", documents=["d"], top_n=1)
    assert results == [{"index": 0, "relevance_score": 0.7}]
    headers = session.last_call["headers"]
    assert headers.get("api-key") == "k-abc"
    assert "Authorization" not in headers
    payload = session.last_call["json"]
    assert payload["model"] == "Cohere-rerank-v4.0-pro"
    assert payload["return_documents"] is False
    assert payload["top_n"] == 1
    assert client.last_headers.get("x-ratelimit-remaining") == "249"


def test_cohere_client_raises_on_non_200():
    session = _StubSession(_StubResp(401, {"error": "unauthorized"}))
    client = CohereRerankClient(
        endpoint="https://example/rerank",
        api_key="nope",
        session=session,
    )
    with pytest.raises(RuntimeError):
        client.rerank(query="q", documents=["d"])


def test_cohere_client_requires_configuration(monkeypatch):
    # Clear env so the client has nothing to fall back on.
    for var in (
        "AZURE_COHERE_RERANK_ENDPOINT",
        "AZURE_COHERE_RERANK_API_KEY",
        "AZURE_COHERE_RERANK_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    # Prevent the constructor from re-loading .env.local.
    from pipeline.rerank import cohere as cohere_mod

    monkeypatch.setattr(cohere_mod, "_load_env_local_once", lambda: None)
    client = CohereRerankClient(endpoint="", api_key="")
    with pytest.raises(RuntimeError, match="not configured"):
        client.rerank(query="q", documents=["d"])
