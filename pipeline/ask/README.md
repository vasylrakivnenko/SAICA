# SAICA API: Ask and Assess

The code in this folder builds the API behind the site's Ask and Assess
pages. It is served by one entry point, `pipeline/webapp.py`, under `/api`:

| Route | What it does |
|---|---|
| `POST /api/ask` | `{"question": "…"}` → an answer written by an LLM from retrieved KG nodes, with the nodes as citations. |
| `POST /api/assess` | `{"repo_url": "https://github.com/<owner>/<repo>"}` → an audit report of that public repository. |
| `GET /api/health` | `{"ok": true}` |

The site works without it; the two pages show an error on submit when the
API is not running.

## Run locally

```bash
.venv/bin/pip install -r requirements/web.txt -c requirements/constraints.txt

.venv/bin/python -m pipeline.webapp --help   # prints help and exits
.venv/bin/python -m pipeline.webapp          # API on 127.0.0.1:4322
```

```bash
curl -X POST http://127.0.0.1:4322/api/ask \
     -H 'Content-Type: application/json' \
     -d '{"question":"what catches made-up package names?"}'
curl http://127.0.0.1:4322/api/health
```

`/api/ask` calls a paid model. `python -m pipeline.ask.server` runs the
same entry point.

## Environment

Model (keys may also sit in `.env.local`, which is read at start-up):

- `HYPERBOLIC_API_KEY`, `ASK_MODEL` — the hosted provider and model; or
- `AZURE_KIMI_API_KEY`, `AZURE_KIMI_ENDPOINT`, `AZURE_KIMI_MODEL` — any
  OpenAI-compatible endpoint. These win when both are set.

Server: `ASK_HOST` (default `127.0.0.1`), `ASK_PORT` (default `4322`),
`SERVE_STATIC=1` (also serve `site/dist`), `FORWARDED_ALLOW_IPS`.

Limits (each has a default):

| Variable | Default | Meaning |
|---|---|---|
| `SAICA_ASK_BUDGET` | 50 | questions per UTC day, all visitors together |
| `SAICA_ASK_TOKEN_BUDGET` | 600000 | model tokens per UTC day |
| `SAICA_ASK_PER_CLIENT` | 10 | questions per hour per client address |
| `SAICA_ASK_CONCURRENCY` | 4 | questions answered at once |
| `SAICA_ASSESS_BUDGET` | 100 | audits per UTC day (cached reports are free) |
| `SAICA_ASSESS_PER_CLIENT` | 10 | audits per hour per client address |
| `SAICA_ASSESS_CONCURRENCY` | 2 | audits running at once |
| `SAICA_TRUSTED_PROXY_HOPS` | 1 | proxies in front of the app (see below) |
| `SAICA_CORS_ORIGINS` | the site and local dev origins | comma-separated list |
| `SAICA_API_DOCS` | off | `1` turns `/docs` and `/openapi.json` on |

The budgets live in the server process. They start again at midnight UTC
and after a restart, and each instance of an autoscaled deployment has its
own: the real daily ceiling is the budget times the number of instances.

The client address comes from the last entry of `X-Forwarded-For`, the one
the nearest proxy wrote; entries further left can be forged by the caller
and are ignored. This is only as good as the proxy: it must be the only
way to reach the app and must append the address it saw. That has not been
checked against the live deployment.

## Responses

`POST /api/ask`, 200:

```json
{
  "answer": "...",
  "citations": [
    { "id": "...", "type": "tool", "name": "...", "snippet": "...",
      "similarity": 0.78, "url": "/tools/..." }
  ],
  "kimi_tokens_used": 834,
  "model": "..."
}
```

(`kimi_tokens_used` is an old field name; it holds the tokens of whatever
model answered.)

`POST /api/assess`, 200: an `AuditReport` (`pipeline/audit/schemas.py`),
including `limits`: what the audit can and cannot detect. A repository is
audited at most once a day; the header `x-saica-cache` says `hit` or `miss`.

Errors are `{"detail": "<one sentence>", "request_id": "<id>"}`. The same
id is in the `X-Request-ID` header and in the server log, where the cause
is recorded; the response never carries it.

| Status | When |
|---|---|
| 400 | blank question; a URL that is not a GitHub repository root |
| 404 | (assess) no public repository at that address |
| 413 | request body over 8,192 bytes |
| 422 | the JSON does not have the expected fields; (assess) repository too large to list |
| 429 | per-client limit, all slots busy, or the day's budget is used up |
| 500 / 502 / 503 / 504 | the model or GitHub failed or took too long |
