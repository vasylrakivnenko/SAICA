# Architecture Review — System Design

## Verdict (≤150 words)

SAICA-KG's pipeline is in good shape for v0.1: layering is mostly clean (`db` → `sources`/`nlp`/`extract`/`rerank` → `cli`), the graduation gate is load-bearing and well-defended, and the test footprint is respectable. Top 3 issues: (1) **duplicated env-loading** across `pipeline/db.py`, `pipeline/sources/_http.py`, `pipeline/rerank/cohere.py` — three copies, one with a hardcoded absolute path; (2) **fractured ingest surface** — `validator/` hosts several ingestion scripts that belong in `pipeline/cli/`; (3) **no structured logging** — a candidate can't be traced end-to-end without grepping stdout. Concurrency is used only in Kimi extract; NLP preprocess, rerank, and discovery are serial and leave throughput on the table. No show-stoppers for launch.

## Strengths (keep these)

- **Single source of truth for models.** Pydantic `pipeline/models.py` → `validator/generate_schemas.py` → `schema/*.json` → `site/scripts/gen-types.mjs` → `types.generated.ts`. `--check` mode enforces no drift.
- **Cache keys are correct.** `pipeline/extract/cache.py` keys on `(prompt_version, kind, candidate_id, source_url)` with `PROMPT_VERSION` bump.
- **Confidence-fields everywhere** (`pipeline/extract/schemas.py:48-76`). Every Kimi field carries `(value, confidence, evidence)`; fallback ladder in `pipeline/graduate/fallbacks.py` prefers GitHub-API ground truth for data-only fields.
- **Graduation gate is structurally enforced.** `pipeline/cli/graduate.py:519-531` (no payload, no graduation); `:579-585` (no overwrite); validator runs on the new file.
- **Dedup is layered** YAML → candidate → batch with documented rule order (`pipeline/dedup.py:326-386`). `canonical_github_url` strips `/tree/`, `.git`, handles reserved owners.
- **Shared rate-limiter** (`pipeline/sources/_http.py:51-73`) + Elicit file-counter — right tradeoff for the 100/day quota.

## Issues and proposals

### Issue 1: Three duplicate env-loaders, one with a hardcoded absolute path
**Observation.** `pipeline/db.py:47-68`, `pipeline/sources/_http.py:23-48`, `pipeline/rerank/cohere.py:60-77`. `_http.py:20` has `_ENV_PATH = Path("/Users/vasyl/saicakg/.env.local")` — broken on any other machine. `pipeline/sources/elicit.py:23` has the same absolute-path antipattern for `.pipeline/`.
**Impact.** Breaks CI/Docker/other dev machines; three copies silently diverge.
**Proposal (S).** `pipeline/env.py` with `load_env_local()` and `RUN_DIR` constant. Path = `Path(__file__).resolve().parents[1] / ".env.local"`. Delete duplicates.

### Issue 2: Discovery/ingest scripts split between `validator/` and `pipeline/cli/`
**Observation.** `validator/discover_candidates.py`, `validator/ingest_github.py`, `validator/fetch_github_stars.py`, `validator/coverage_report.py` all write to `data/` or the DB but live in `validator/`. They use hand-rolled `urllib.request` (vs `requests`), different argparse style, different env conventions. Only `validator/cli.py` and `validator/generate_schemas.py` actually validate.
**Impact.** CLI discoverability; new contributors learn two places.
**Proposal (M).** Move all four to `pipeline/cli/`. Keep `validator/` for invariant enforcement only.

### Issue 3: No structured logging; candidates can't be traced end-to-end
**Observation.** Mix of `print()` (`pipeline/cli/extract.py:63,82`; `pipeline/cli/graduate.py:590,613`) and `log.info/warning`. No correlation id, no `candidate_id` on source-layer logs. No event table.
**Impact.** Debugging a failed graduation requires grepping stdout. Gets worse at 500 tools with concurrent runs.
**Proposal (M).** (a) `structlog` with mandatory `candidate_id`/`source_url`/`kind` fields; (b) `pipeline_events` table `(candidate_id, stage, event_type, payload, ts)` with one row per lifecycle transition. Add `pipeline.cli.trace <id>`.

### Issue 4: Serial rerank and NLP preprocess; low-hanging parallelism
**Observation.** `pipeline/rerank/cohere.py:316-338` serial with 0.25s sleep; session is thread-safe. `pipeline/nlp/pipeline.py:141-252` processes rows one at a time with a per-row `_source_url_exists` round-trip.
**Impact.** Wall-time scales linearly with candidate count; noticeable at 500 tools.
**Proposal (M).** Rerank: `ThreadPoolExecutor(max_workers=4)`. Preprocess: batch `_source_url_exists` into `WHERE source_url = ANY(%s)`, keep results in a set; `executemany` per transaction.

### Issue 5: `DupChecker` rebuilds YAML+DB index on every instantiation
**Observation.** `pipeline/dedup.py:254-317` reads every `data/tools/*.yml` on construction. Bulk-ingest hits this once per run, but tests/nested call sites could make it quadratic.
**Impact.** ~200ms per CLI run at 500 tools. Minor.
**Proposal (S).** Module-level singleton keyed on `(yaml_dir, max(mtime))`.

### Issue 6: Inconsistent retry/error shapes across source clients
**Observation.** `pipeline/extract/kimi.py:326-341` — 3 retries, string-match 429. `pipeline/rerank/cohere.py:214-253` — 2 retries, status-code check, respects 5xx. `pipeline/sources/{github,semantic_scholar,perplexity,elicit}.py` — **no retry**; one network blip drops the batch.
**Impact.** Silent 5-10% drop rate on discovery.
**Proposal (M).** Richer `HttpClient` in `_http.py` with uniform retry policy (respect `Retry-After`, exponential backoff, typed `SourceError`). Have every source use it.

### Issue 7: No HTTP response caching for idempotent source calls
**Observation.** Re-running `discover perplexity --query X` always re-pays. Only Kimi is cached.
**Impact.** Wasted API spend; Elicit's 100/day means one bad run locks out the day.
**Proposal (S).** Hash `(source, method, url, body)` → cached response in a `http_cache` table with per-source TTL.

### Issue 8: Fragile string-based rate-limit detection
**Observation.** `kimi.py:331` — `"429" in str(exc) or "rate" in str(exc).lower()`. `github.py:75` — `status_code == 403 and "rate limit" in resp.text.lower()`.
**Impact.** Low; occasional misclassification.
**Proposal (S).** Exception-class branching (`openai.RateLimitError`, `requests.HTTPError`) + status-code checks.

### Issue 9: `upsert_candidate_tool` has 8-argument binding with 4x duplicated params
**Observation.** `pipeline/db.py:200-230` binds `extracted_j`/`nlp_tags_j` four times to work around psycopg binding `dict → json` not `jsonb`, plus CASE-WHEN null-checks. Correct but fragile.
**Impact.** A future edit that adds a column will silently clobber on conflict.
**Proposal (S).** Register a `psycopg` adapter that binds `dict → jsonb` directly; collapse to `COALESCE(EXCLUDED.extracted, candidate_tools.extracted)`.

### Issue 10: JSON API endpoints have inconsistent envelope
**Observation.** `site/src/pages/api/v1/snapshot.json.ts` wraps with `{kg_version, kg_last_updated, counts, disclaimer, nodes}`. `tools.json.ts` returns bare `Object.values(graph.tools)` — no envelope. Same for `failure_modes`, `papers`, `taxonomies`.
**Impact.** Consumers can't tell stale from fresh; no version stamp on listing endpoints.
**Proposal (S).** Wrap all `/api/v1/*.json` in `{kg_version, kg_last_updated, count, data}`.

### Issue 11: Elicit budget counter + `DupChecker` batch state are non-atomic
**Observation.** `pipeline/sources/elicit.py:51-61` read-modify-write of JSON file is racy; two concurrent runs could both pass. `pipeline/dedup.py:244-246` batch dicts have no lock (currently single-threaded only).
**Impact.** Low today; latent.
**Proposal (S).** `os.rename` atomic swap for Elicit counter; threading lock if `DupChecker` ever fans out.

## Naming inconsistencies found

| current | proposed | rationale |
|---|---|---|
| `_KIND_TABLE` singular keys in `pipeline/cli/graduate.py:68` vs plural in `pipeline/cli/extract.py:42` and `pipeline/db.py:37` | plural everywhere | same-name constant, different semantics |
| `ToolExtraction.proposed_id` | `id_suggested` (per arch doc) or update doc | `PIPELINE_ARCHITECTURE.md:170` uses `id_suggested`; code uses `proposed_id` |
| `pipeline/nlp/pipeline.py` | `pipeline/nlp/runner.py` | `pipeline.nlp.pipeline.run` is confusingly nested |
| `validator/fetch_github_stars.py` | `pipeline/cli/refresh_stars.py` | see Issue 2 |
| `DupHit.kind` (`yaml`/`candidate`/`batch`) overlaps `db.kind` (`tools`/`papers`) | rename to `DupHit.source` | avoid double-meaning |
| `candidate_incidents` has no `UNIQUE(source_url)` | add it | inconsistent with tools/papers (`schema.sql:59-70`) |
| `MAX_RETRIES` = 3 in kimi, 2 in cohere | central `pipeline/config.py` | magic numbers scattered |

## Concurrency observations

- **Kimi extract**: `ThreadPoolExecutor(3)` + `BoundedSemaphore(3)` (`kimi.py:47,580`). Correct; jittered backoff.
- **NLP preprocess**: serial with per-row DB round-trip (`nlp/pipeline.py:268`). Easy win (Issue 4).
- **Rerank**: serial + 0.25s sleep. Easy win.
- **Discovery**: each source serial; runbook walks sources sequentially though they don't share rate limits.
- **Race conditions**: Elicit counter file (Issue 11); `DupChecker` batch state (unused multi-thread, latent).

## Configuration observations

- Three env-loaders; two hardcoded absolute paths (Issue 1).
- `POSTGRES_URL` silently defaults (`db.py:22`) — `cli.db status` should announce which DSN is in use.
- No `.env.example` observed at repo root.
- Env-var naming is consistent (`AZURE_KIMI_*`, `AZURE_COHERE_RERANK_*`, `GITHUB_TOKEN`, …).
- `MAX_CONCURRENCY`, `MAX_RETRIES`, `BASE_BACKOFF_SECONDS` duplicated across modules with inconsistent values — centralize.

## Quick wins (≤1hr each)

1. Unify env-loading (`pipeline/env.py`); delete 3 duplicates. (Issue 1)
2. Delete hardcoded absolute paths in `_http.py:20` and `elicit.py:23`.
3. Exception-class-based retry in `kimi.py`/`github.py`. (Issue 8)
4. Unify `_KIND_TABLE` singular/plural.
5. Commit `.env.example` enumerating every required var.
6. Add `UNIQUE(source_url)` to `candidate_incidents`.
7. `cli.db status` prints DSN in use.
8. Wrap all `/api/v1/*.json` in a uniform envelope. (Issue 10)
9. `DupChecker` module-level cache keyed on mtime. (Issue 5)

## Medium-effort (≤1 day)

1. Move `validator/`'s ingest scripts into `pipeline/cli/`. (Issue 2)
2. Parallelise NLP preprocess + rerank (batched `source_url` lookup; `ThreadPoolExecutor`). (Issue 4)
3. Uniform `HttpClient` with retry + backoff + response cache. (Issues 6, 7)
4. `psycopg` `dict → jsonb` adapter to simplify `upsert_candidate_*`. (Issue 9)
5. Atomic swap for Elicit counter. (Issue 11)

## Strategic changes (multi-day)

1. **Structured logging + `pipeline_events` table + `pipeline.cli.trace <id>`.** Highest-leverage once the KG grows past v0.1. (Issue 3)
2. **Containerise the pipeline.** `Dockerfile` + `docker-compose.pipeline.yml` so CI can exercise discovery → graduation without a maintainer's laptop.
3. **Separate `candidate_extractions` table** — one row per `(candidate, prompt_version, model)`. Cleanly separates cache from candidate state, enables re-run comparison.
4. **Move to managed staging DB** (Neon/Supabase) once multi-person review kicks in. Arch doc anticipates this already.
5. **Site-side graph indexing** — precompute adjacency JSON at build time so `KGGraph.ts` doesn't rebuild edges on every visit. Needed at 500+ nodes.
