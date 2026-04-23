# SAICA-KG /ask backend

Small FastAPI service that powers the site's `/ask` RAG page. It accepts a
natural-language question, retrieves relevant KG nodes via semantic search
(`pipeline.embeddings.query.find_similar`), and synthesizes an answer via
Kimi-K2.5 with bracketed node-id citations.

The site builds statically without this service running; `/ask` will render
fine and show an error only on submit when the backend is unreachable.

## Run locally

```bash
# one-time
.venv/bin/pip install fastapi uvicorn

# start the service (listens on 127.0.0.1:4322)
.venv/bin/python -m pipeline.ask.server
```

In another shell:

```bash
curl -X POST http://localhost:4322/ask \
     -H 'Content-Type: application/json' \
     -d '{"question":"what prevents hallucinations in python agents?"}'
```

Health check:

```bash
curl http://localhost:4322/health
```

## Environment

The service reuses the Kimi env vars defined in `.env.local`:

- `AZURE_KIMI_API_KEY`
- `AZURE_KIMI_ENDPOINT`
- `AZURE_KIMI_MODEL` (optional, defaults to `Kimi-K2.5`)

Backend-specific knobs:

- `SAICA_ASK_BUDGET` — max Kimi calls per server lifetime (default `50`).
  When exceeded, `/ask` returns HTTP 429. Restart to reset the budget.
- `SAICA_ASK_PORT` — override the default 4322.

## Site → backend URL

The site reads `PUBLIC_ASK_API` (build-time) or falls back to
`http://localhost:4322/ask`. Set `PUBLIC_ASK_API=https://your-prod-host/ask`
when building for production.

## Cost cap

`SAICA_ASK_BUDGET=50` is roughly $0.25 at current Kimi-K2.5 Azure pricing
— stays well inside the "don't blow up the bill on a dev laptop" rule.
For a public deploy set a stricter cap or put the service behind rate
limiting.

## Contract

Request:

```json
{ "question": "..." }
```

Response (200):

```json
{
  "answer": "...",
  "citations": [
    { "id": "...", "type": "tool", "name": "...", "snippet": "...",
      "similarity": 0.78, "url": "/tools/..." }
  ],
  "kimi_tokens_used": 834,
  "model": "Kimi-K2.5"
}
```

Error shapes:

- `400` — empty/blank question
- `429` — budget exceeded (`SAICA_ASK_BUDGET`)
- `500` — retrieval or Kimi call failed (message in `detail`)
