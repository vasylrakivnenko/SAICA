"""FastAPI service that answers natural-language questions against SAICA-KG.

Run with::

    .venv/bin/python -m pipeline.ask.server

The static site's /ask page POSTs to ``http://localhost:4322/ask`` with
``{"question": "..."}``. This process owns the Kimi API key; the browser
never sees it.

The backend is optional — the /ask page builds statically even if this
process is down. In that case submit fails with a friendly network error.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pipeline.ask.context import NodeContext, build_prompt, hybrid_retrieve, hydrate
from pipeline.config import load_env_once
from pipeline.cost_caps import CallBudget, CostCapExceeded

# Pull AZURE_KIMI_* from .env.local into os.environ at module import so the
# first Kimi call doesn't error just because uvicorn wasn't launched via the
# repo's shell profile.
load_env_once()

log = logging.getLogger(__name__)

# Port chosen to sit adjacent to Astro's default dev port 4321. Keeping
# them on different ports avoids hijacking the site's CORS story.
DEFAULT_PORT = 4322

# Default retrieval fan-out. K=20 gives the coverage-guard rule enough
# candidates to find tools that actually declare coverage for the
# inferred failure mode with a surface fit — at K=12, questions phrased
# in agent-behavior vocabulary ("agent changed X") pulled back mostly
# IDE/hosted agents and squeezed out pipeline-friendly libraries.
DEFAULT_K = 20

# Kimi-K2.5 is a reasoning model: the think-trace silently consumes part of
# max_tokens before any visible content is emitted. With the richer prompt
# that enforces coverage/paradigm/surface rules, the trace routinely hits
# ~3.5k tokens on ambiguous questions; anything below ~5k leaves content
# empty. 6144 gives headroom for a full multi-tool recommendation.
KIMI_MAX_TOKENS = 6144
KIMI_TEMPERATURE = 0.2


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------


class Question(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class AssessRequest(BaseModel):
    """Input for the /assess endpoint — a public GitHub repo URL."""

    repo_url: str = Field(..., min_length=1, max_length=500)


class Citation(BaseModel):
    id: str
    type: str
    name: str
    snippet: str
    similarity: float
    url: str


class Answer(BaseModel):
    answer: str
    citations: list[Citation]
    kimi_tokens_used: int
    model: str


# ---------------------------------------------------------------------------
# App factory (so tests can spin up clean instances)
# ---------------------------------------------------------------------------


def _default_budget() -> CallBudget:
    """Construct the lifetime :class:`CallBudget` from ``SAICA_ASK_BUDGET``."""
    raw = os.environ.get("SAICA_ASK_BUDGET", "50")
    try:
        cap = int(raw)
    except (TypeError, ValueError):
        log.warning("invalid SAICA_ASK_BUDGET=%r; falling back to 50", raw)
        cap = 50
    return CallBudget(max_calls=cap)


def _default_find_similar(
    question: str, k: int, *, node_type: str | None = None,
) -> list[tuple[str, float]]:
    """Thin wrapper around ``pipeline.embeddings.query.find_similar``.

    Imported lazily so the server module imports even before the
    embeddings agent has landed its module. At runtime the call path is:
    HTTP -> ``ask()`` -> ``hybrid_retrieve`` -> this wrapper ->
    ``embeddings.query.find_similar``. ``node_type`` lets the hybrid
    retriever narrow the second pass to tool-only results.
    """
    from pipeline.embeddings.query import find_similar  # local import

    return list(find_similar(question, k=k, node_type=node_type))


def _default_kimi_call(prompt: str) -> tuple[str, Any]:
    """Issue one Kimi chat completion and return (answer_text, raw_response).

    Reuses :func:`pipeline.extract.kimi.get_client` so the Azure env-var
    plumbing and retry/concurrency logic stay in one place. Returns the
    raw response too so the caller can surface token counts.
    """
    from pipeline.extract.kimi import _model_name, get_client

    client = get_client()
    resp = client.chat.completions.create(
        model=_model_name(),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=KIMI_MAX_TOKENS,
        temperature=KIMI_TEMPERATURE,
    )
    content = resp.choices[0].message.content or ""
    return content.strip(), resp


def create_app(
    *,
    find_similar=_default_find_similar,
    kimi_call=_default_kimi_call,
    budget: CallBudget | None = None,
    k: int = DEFAULT_K,
) -> FastAPI:
    """Build a FastAPI app with injected collaborators.

    Tests pass fakes for ``find_similar`` and ``kimi_call`` so the server
    can be exercised without Postgres or Azure. The default factory
    (``app`` at module scope below) wires in the real dependencies.
    """
    app = FastAPI(title="SAICA-KG /ask backend")
    lifetime_budget = budget if budget is not None else _default_budget()

    # Astro dev server runs on :4321 by default; allow it to POST here.
    # In prod this is a deployed service behind a gateway, so wide-open
    # CORS here is not a risk — there's no auth to leak.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, Any]:  # noqa: D401 — trivial ping
        return {"ok": True, "budget": lifetime_budget.summary()}

    @app.post("/ask", response_model=Answer)
    def ask(q: Question) -> Answer:  # noqa: D401 — HTTP endpoint
        question = q.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="question must not be blank")

        try:
            hits = hybrid_retrieve(question, k, find_similar=find_similar)
        except Exception as exc:  # noqa: BLE001
            log.exception("retrieval failed")
            raise HTTPException(status_code=500, detail=f"retrieval failed: {exc}") from exc

        nodes = hydrate(hits)
        prompt = build_prompt(question, nodes)

        try:
            lifetime_budget.consume(call=True, tokens=0)
        except CostCapExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

        try:
            answer_text, raw = kimi_call(prompt)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("kimi call failed")
            raise HTTPException(status_code=500, detail=f"kimi call failed: {exc}") from exc

        tokens = _extract_total_tokens(raw)
        lifetime_budget.consume(call=False, tokens=tokens)

        citations = [_node_to_citation(n) for n in nodes]
        return Answer(
            answer=answer_text,
            citations=citations,
            kimi_tokens_used=tokens,
            model=_raw_model_name(raw),
        )

    @app.post("/assess")
    def assess(req: AssessRequest) -> Any:  # noqa: D401 — HTTP endpoint
        """Audit a public GitHub repo and return an :class:`AuditReport`.

        The audit analyzer (`pipeline.audit.analyzer`) is built in parallel
        and may not be importable yet. We try-import inside the handler so
        the server starts cleanly and only `/assess` itself returns 503
        when the analyzer module is missing.
        """
        try:
            from pipeline.audit.analyzer import audit_repo  # local import
        except ImportError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"audit analyzer not available yet: {exc}",
            ) from exc

        repo_url = req.repo_url.strip()
        if not repo_url:
            raise HTTPException(status_code=400, detail="repo_url must not be blank")

        try:
            report = audit_repo(repo_url)
        except ValueError as exc:
            # Bad URL / unsupported host / not a public repo — user-facing.
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("audit failed for %s", repo_url)
            raise HTTPException(status_code=500, detail=f"audit failed: {exc}") from exc

        # Returning the Pydantic instance directly lets FastAPI serialize
        # via model_dump(mode="json"). We deliberately avoid a static
        # `response_model=AuditReport` annotation so the server still
        # imports when `pipeline.audit.analyzer` isn't present.
        return report

    return app


def _extract_total_tokens(raw: Any) -> int:
    usage = getattr(raw, "usage", None)
    if usage is None:
        return 0
    return int(getattr(usage, "total_tokens", 0) or 0)


def _raw_model_name(raw: Any) -> str:
    return str(getattr(raw, "model", "") or os.environ.get("AZURE_KIMI_MODEL", "Kimi-K2.5"))


def _node_to_citation(n: NodeContext) -> Citation:
    return Citation(
        id=n.id,
        type=n.type,
        name=n.name,
        snippet=n.snippet,
        similarity=n.similarity,
        url=n.url,
    )


# Module-level app used by `python -m pipeline.ask.server` and uvicorn.
app = create_app()


def main() -> None:
    """Entrypoint: ``python -m pipeline.ask.server``."""
    import uvicorn

    port = int(os.environ.get("SAICA_ASK_PORT", DEFAULT_PORT))
    logging.basicConfig(level=logging.INFO)
    log.info("starting SAICA-KG /ask backend on port %d", port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
