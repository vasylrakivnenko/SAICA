# pipeline/ — SAICA-KG ingestion staging

> **Dormant since 2026-04-23.** The Postgres ingestion pipeline described here (discovery → NLP
> preprocess → rerank → LLM extraction → graduation) ran for one night, 2026-04-22/23. Every row in the
> staging database dates from those hours; 4 of today's 49 tool nodes came through it, and no paper or
> incident did. The catalogue has been curated by hand and by one-off scripts since. Nothing is scheduled,
> the Azure model deployment it called returned 404 in November 2026, and several statements below
> describe a design that was not built or not followed (thresholds, the review gate, the reranker's role):
> see `research/review_20261121_r2/pipeline_validator.md`, PV-02 to PV-04 and PV-15. The code is kept, not
> archived (owner decision, 2026-11-21). What is still live in `pipeline/`: `models.py` (the schema
> source), `config.py`, `cost_caps.py`, `embeddings/compute.py` and `query.py`, `maturity/`, and the served
> packages `ask/`, `audit/`, `mcp/`, `supervision/`, `saica_index/`, `shared/`, `webapp.py`.
>
> Safety, added 2026-11-21: `python -m pipeline.cli.db init --drop-first` prints the target database and
> does nothing without `--yes`; `tests/test_db_smoke.py` runs its round trip only against a database
> whose name contains `_test`. The local staging database holds the only copy of the 48 paid extractions
> and has never been backed up (`python -m pipeline.cli.backup` exists and was never used).

Local Postgres infrastructure for landing raw search results, README snapshots,
and LLM-extracted candidate rows before a reviewer graduates them to canonical
YAML under `data/`. Architecture: [`research/PIPELINE_ARCHITECTURE.md`](../research/PIPELINE_ARCHITECTURE.md).

## Quick start (Docker)

```bash
# bring up Postgres (listens on host :5433 so it doesn't collide with a
# locally-installed Postgres on the default :5432)
docker compose up -d postgres

# wait until healthy
docker compose ps

# install pipeline deps
.venv/bin/pip install -r pipeline/requirements.txt

# initialize schema
.venv/bin/python -m pipeline.cli.db init

# verify
.venv/bin/python -m pipeline.cli.db status
```

Stop / tear down:

```bash
docker compose down           # stop container, keep data
docker compose down -v        # stop AND wipe ./.postgres-data
```

The DSN `pipeline/db.py` uses is read from `POSTGRES_URL` (`.env.local`); the
default matches the compose service:

```
postgresql://saica:saica_local_dev@localhost:5433/saica_kg
```

## Fallback: no Docker available

If Docker is unavailable (e.g. macOS without Docker Desktop / Colima /
OrbStack), point at any local Postgres 16 instead. Example using Homebrew
`postgresql@16` already running on `:5432`:

```bash
# one-time: create role + database
/opt/homebrew/opt/postgresql@16/bin/psql postgres <<'SQL'
CREATE ROLE saica LOGIN PASSWORD 'saica_local_dev';
CREATE DATABASE saica_kg OWNER saica;
SQL

# run the CLI with an overridden DSN (note :5432, not :5433)
POSTGRES_URL=postgresql://saica:saica_local_dev@localhost:5432/saica_kg \
  .venv/bin/python -m pipeline.cli.db init

POSTGRES_URL=postgresql://saica:saica_local_dev@localhost:5432/saica_kg \
  .venv/bin/python -m pipeline.cli.db status
```

SQLite is NOT a drop-in replacement — the schema uses `JSONB`, `TEXT[]`,
generated columns, and `TIMESTAMPTZ`. Use real Postgres.

## Module layout

- `db.py` — connection + CRUD helpers. Stable public API; other pipeline
  modules (NLP, extractor, graduation CLI) depend on it.
- `schema.sql` — DDL matching `PIPELINE_ARCHITECTURE.md` § "Postgres schema
  (v0.1)".
- `cli/db.py` — `python -m pipeline.cli.db {init,status}`.

## Public API (`pipeline.db`)

- `get_conn()` — context manager yielding a `psycopg.Connection`.
- `init_schema(drop_first=False)` — apply `schema.sql`.
- `insert_raw_result(source, query, *, url, title, snippet, raw_json)` →
  `int | None` (None on duplicate `(source, content_hash)`).
- `insert_readme(url, content)` — upsert by URL.
- `upsert_candidate_tool(...)` → `int` candidate id (upsert by `source_url`).
- `upsert_candidate_paper(...)` → `int` candidate id.
- `get_pending(kind, limit=100)` — kind ∈ `{'tools','papers','incidents'}`.
- `update_candidate_status(kind, candidate_id, status, reviewer=None, graduated_to=None)`.
- `raw_results_by_query(source, query)` — list rows for an exact query.
- `table_counts()` — `[(table, count), ...]` across all pipeline tables.

## Backup & restore

Local-only Postgres snapshots via `pg_dump` + gzip (plain SQL, not `-F c`,
so a reviewer can `zless` them).

```bash
# snapshot -> research/backups/saica_kg_<ISO>.sql.gz
.venv/bin/python -m pipeline.cli.backup

# custom destination
.venv/bin/python -m pipeline.cli.backup --out /tmp/kg.sql.gz

# list known snapshots (newest first)
.venv/bin/python -m pipeline.cli.backup --list

# restore (interactive confirmation required; --yes to skip)
.venv/bin/python -m pipeline.cli.backup --restore research/backups/saica_kg_<ISO>.sql.gz
```

DSN comes from `POSTGRES_URL`. Snapshots live under `research/backups/`
which is git-ignored.
