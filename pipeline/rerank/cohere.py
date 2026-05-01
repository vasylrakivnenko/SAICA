"""Azure-hosted Cohere Rerank v4.0 Pro client.

Sits between the NLP preprocess pass and Kimi extraction. Given a set of
supervision-focused query passages (``SUPERVISION_QUERIES``) and a list of
candidate rows from ``candidate_tools``, scores each (query, candidate) pair
with one HTTP call per query and returns a fused ``DocScore`` per candidate.

Key contract points:

* One HTTP request per query, not per (query, document). That means total
  cost scales with ``len(queries)`` rather than ``len(queries) * len(docs)``.
* Uses the ``api-key`` header (NOT ``Authorization: Bearer``) because that's
  what Azure AI Foundry requires for the Cohere deployment.
* Retries once on 429 / 5xx with exponential backoff capped at 30s.
* Serial calls with a polite 0.25s sleep between requests — well under the
  250 RPM budget and simpler than a real concurrent dispatcher.
* Document text is ``name + summary + (optional README excerpt)``, capped at
  25,000 chars to stay safely under the 32k-token per-query+document limit.
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import requests

from pipeline.config import load_env_once
from pipeline.cost_caps import CallBudget
from pipeline.rerank.queries import (
    QUERY_SET_VERSION,
    SUPERVISION_QUERIES,
    RerankQuery,
    queries_content_hash,
)


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ENV_ENDPOINT = "AZURE_COHERE_RERANK_ENDPOINT"
ENV_API_KEY = "AZURE_COHERE_RERANK_API_KEY"
ENV_MODEL = "AZURE_COHERE_RERANK_MODEL"
DEFAULT_MODEL = "Cohere-rerank-v4.0-pro"

# Hard caps (see module docstring).
MAX_DOC_CHARS = 25_000
README_CHARS = 12_000
HTTP_TIMEOUT_SECONDS = 60
RATE_LIMIT_SLEEP_SECONDS = 0.25  # ~4 req/s, well below 250 RPM
MAX_RETRIES = 2  # 1 initial attempt + 1 retry
MAX_BACKOFF_SECONDS = 30.0
BASE_BACKOFF_SECONDS = 2.0
MAX_RETRY_AFTER_SECONDS = 120.0  # cap for server-specified Retry-After

# Back-compat alias so tests / external callers that monkeypatch the
# pre-refactor name (``pipeline.rerank.cohere._load_env_local_once``) still
# work; delegates to the canonical loader in ``pipeline.config``.
_load_env_local_once = load_env_once


# ---------------------------------------------------------------------------
# Public data type
# ---------------------------------------------------------------------------


@dataclass
class DocScore:
    """Aggregated per-candidate score across all queries.

    ``score_max`` is the primary ranking signal; ``score_mean`` gives a
    secondary tie-breaker that rewards tools that are broadly on-topic
    rather than narrowly spiking on one facet.
    """

    candidate_id: int
    score_max: float
    score_mean: float
    per_query: dict[str, float] = field(default_factory=dict)
    best_query: str = ""


# ---------------------------------------------------------------------------
# Document composition
# ---------------------------------------------------------------------------


def compose_document(
    row: dict,
    *,
    readme_lookup: Optional[Callable[[str], Optional[str]]] = None,
    max_chars: int = MAX_DOC_CHARS,
    readme_chars: int = README_CHARS,
) -> str:
    """Build the text blob that Cohere sees for a candidate.

    Uses ``name`` and ``summary`` from the row; optionally appends a README
    excerpt via ``readme_lookup(source_url)``. If neither ``summary`` nor
    README are available the document falls back to just the name — callers
    that pass rows lacking a name will get an empty string, which Cohere
    accepts (scores will simply be low).
    """
    name = (row.get("name") or row.get("proposed_id") or "").strip()
    summary = (row.get("summary") or "").strip()
    parts: list[str] = []
    if name:
        parts.append(name)
    if summary:
        parts.append(summary)

    # Prefer an explicitly-attached readme on the row (tests / in-memory
    # pipelines use this); fall back to the optional lookup callable.
    readme: Optional[str] = row.get("readme") or row.get("readme_text")
    if not readme and readme_lookup is not None:
        source_url = row.get("source_url")
        if source_url:
            try:
                readme = readme_lookup(str(source_url))
            except Exception as exc:  # noqa: BLE001
                log.warning("readme_lookup failed for %s: %s", source_url, exc)
                readme = None
    if readme:
        parts.append(str(readme)[:readme_chars])

    text = "\n".join(p for p in parts if p)
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


class CohereRerankClient:
    """Thin wrapper over Azure's Cohere Rerank v2 endpoint.

    Inject a custom instance into :func:`rerank_candidates` via the
    ``client=`` kwarg to stub HTTP in tests.
    """

    def __init__(
        self,
        *,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        # Indirect through the module-level alias so tests that patch
        # ``_load_env_local_once`` to a no-op still take effect.
        _load_env_local_once()
        self.endpoint = endpoint or os.environ.get(ENV_ENDPOINT, "")
        self.api_key = api_key or os.environ.get(ENV_API_KEY, "")
        self.model = model or os.environ.get(ENV_MODEL, DEFAULT_MODEL)
        self._session = session or requests.Session()
        # Populated after each call so CLI / telemetry can surface them.
        self.last_headers: dict[str, str] = {}

    def _check_configured(self) -> None:
        missing = []
        if not self.endpoint:
            missing.append(ENV_ENDPOINT)
        if not self.api_key:
            missing.append(ENV_API_KEY)
        if missing:
            raise RuntimeError(
                "Azure Cohere rerank env not configured. Missing: " + ", ".join(missing)
            )

    def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: Optional[int] = None,
        budget: Optional[CallBudget] = None,
    ) -> list[dict]:
        """POST once to the rerank endpoint; return the ``results`` list.

        Each result is ``{"index": int, "relevance_score": float}``.

        When ``budget`` is non-None, each HTTP attempt (successful or not)
        records one call; passing the cap raises ``CostCapExceeded``.
        ``Retry-After`` headers are honored on 429 / 5xx (capped at
        :data:`MAX_RETRY_AFTER_SECONDS`); without the header, falls back
        to capped exponential backoff.
        """
        self._check_configured()
        payload: dict = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "return_documents": False,
        }
        if top_n is not None:
            payload["top_n"] = top_n
        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }
        last_exc: Optional[BaseException] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._session.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=HTTP_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                last_exc = exc
                # Network-level failure: the request did go out, so charge
                # the budget. The CostCapExceeded that may result propagates
                # instead of being silently retried.
                if budget is not None:
                    budget.consume(call=True, tokens=0)
                if attempt >= MAX_RETRIES:
                    raise
                self._sleep_backoff(attempt, reason=f"network: {exc}")
                continue

            self.last_headers = {k: v for k, v in resp.headers.items()}

            if budget is not None:
                budget.consume(call=True, tokens=0)

            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results") or []
                return list(results)

            if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                retry_after = _parse_retry_after_header(resp.headers)
                if retry_after is not None:
                    log.warning(
                        "cohere rerank http %d — honoring Retry-After=%.1fs "
                        "(attempt %d)",
                        resp.status_code,
                        retry_after,
                        attempt,
                    )
                    time.sleep(retry_after)
                else:
                    self._sleep_backoff(
                        attempt,
                        reason=f"http {resp.status_code}: {resp.text[:200]}",
                    )
                continue

            # Non-retriable or out of attempts: raise with the body for
            # debugging.
            raise RuntimeError(
                f"Cohere rerank call failed: status={resp.status_code} "
                f"body={resp.text[:500]!r}"
            )

        # Should be unreachable; defensive re-raise of the last network error.
        raise RuntimeError(
            f"Cohere rerank exhausted retries ({MAX_RETRIES}): {last_exc}"
        ) from last_exc

    @staticmethod
    def _sleep_backoff(attempt: int, *, reason: str) -> None:
        backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
        backoff += random.uniform(0, 0.5)
        backoff = min(backoff, MAX_BACKOFF_SECONDS)
        log.warning(
            "cohere rerank retry in %.1fs (attempt %d, %s)",
            backoff,
            attempt,
            reason,
        )
        time.sleep(backoff)


def _parse_retry_after_header(headers) -> Optional[float]:
    """Pull ``Retry-After`` out of a ``requests`` response headers mapping.

    Returns seconds-to-sleep (clamped to :data:`MAX_RETRY_AFTER_SECONDS`),
    or ``None`` when the header is absent, non-numeric, or negative. This
    impl handles only the delta-seconds format; HTTP-date Retry-After
    values are uncommon from SaaS APIs and fall through to exp-backoff.
    """
    if headers is None:
        return None
    try:
        raw = headers.get("Retry-After") or headers.get("retry-after")
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rerank_provenance() -> dict:
    """Return the provenance block that pairs with rerank scores in ``nlp_tags``.

    Callers merge this into each candidate row's ``nlp_tags`` alongside
    ``rerank_score`` so that, when ``SUPERVISION_QUERIES`` is later edited,
    stale scores can be detected by hash mismatch and re-ranked.
    """
    return {
        "rerank_query_set_version": QUERY_SET_VERSION,
        "rerank_query_set_hash": queries_content_hash(),
        "rerank_scored_at": datetime.now(timezone.utc).isoformat(),
    }


def rerank_candidates(
    candidate_rows: list[dict],
    queries: Optional[list[RerankQuery]] = None,
    *,
    readme_lookup: Optional[Callable[[str], Optional[str]]] = None,
    top_n: Optional[int] = None,
    client: object | None = None,
    budget: Optional[CallBudget] = None,
) -> list[DocScore]:
    """Score each candidate against every query; return sorted DocScores.

    One HTTP request per query (so ``len(queries)`` calls total). Each
    candidate_row must have at minimum an ``id``; ``name``, ``summary``,
    ``source_url``, and ``nlp_tags`` are used where present. Pass a
    ``readme_lookup`` callable to attach README excerpts.

    Pass a :class:`CallBudget` to cap HTTP calls; ``CostCapExceeded``
    propagates to the caller. The CLI converts that to exit code 3.

    Returns DocScores sorted by ``score_max`` descending. If
    ``candidate_rows`` is empty, returns ``[]`` without making any HTTP
    calls.
    """
    if not candidate_rows:
        return []

    query_list = list(queries) if queries is not None else list(SUPERVISION_QUERIES)
    if not query_list:
        # No queries means no scoring; return zero-score rows so callers can
        # still iterate a stable shape.
        return [
            DocScore(candidate_id=int(r["id"]), score_max=0.0, score_mean=0.0)
            for r in candidate_rows
        ]

    documents = [
        compose_document(r, readme_lookup=readme_lookup) for r in candidate_rows
    ]
    candidate_ids = [int(r["id"]) for r in candidate_rows]
    effective_top_n = top_n if top_n is not None else len(candidate_rows)

    rerank_client = client if client is not None else CohereRerankClient()

    # per_candidate[cid][query_id] = score
    per_candidate: dict[int, dict[str, float]] = {cid: {} for cid in candidate_ids}

    for i, q in enumerate(query_list):
        t0 = time.time()
        # Pass ``budget`` through as a kwarg so test doubles that don't
        # accept it still work — inspect the client's signature lazily.
        rerank_kwargs: dict = {
            "query": q.text,
            "documents": documents,
            "top_n": effective_top_n,
        }
        if budget is not None:
            rerank_kwargs["budget"] = budget
        results = rerank_client.rerank(**rerank_kwargs)  # type: ignore[attr-defined]
        elapsed = time.time() - t0
        top_score = max((r["relevance_score"] for r in results), default=0.0)
        log.info(
            "cohere rerank query=%s docs=%d top=%.3f elapsed=%.2fs",
            q.id,
            len(documents),
            top_score,
            elapsed,
        )

        for result in results:
            idx = int(result["index"])
            if 0 <= idx < len(candidate_ids):
                cid = candidate_ids[idx]
                per_candidate[cid][q.id] = float(result["relevance_score"])

        # Polite pacing between calls; skip sleep after the last one.
        if i < len(query_list) - 1:
            time.sleep(RATE_LIMIT_SLEEP_SECONDS)

    out: list[DocScore] = []
    for cid in candidate_ids:
        scores = per_candidate[cid]
        if scores:
            score_max = max(scores.values())
            score_mean = sum(scores.values()) / len(scores)
            best_query = max(scores.items(), key=lambda kv: kv[1])[0]
        else:
            score_max = 0.0
            score_mean = 0.0
            best_query = ""
        out.append(
            DocScore(
                candidate_id=cid,
                score_max=score_max,
                score_mean=score_mean,
                per_query=dict(scores),
                best_query=best_query,
            )
        )

    out.sort(key=lambda d: d.score_max, reverse=True)
    return out


__all__ = [
    "CohereRerankClient",
    "DocScore",
    "compose_document",
    "rerank_candidates",
    "rerank_provenance",
]
