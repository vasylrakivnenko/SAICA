# SAICA-KG

**Supervising AI Coding Agents — Knowledge Graph**

A living, faceted, queryable knowledge graph for the governance of agentic AI coding tools. Paper + GitHub + website.

SAICA-KG absorbs existing failure-mode taxonomies for AI coding agents (OWASP Agentic Top 10, MAST, DAPLab 9, Microsoft AIRT) as multi-valued tags, then adds orthogonal **strict partitions** — ControlParadigm × TemporalPhase × AutonomyLevel — that no single existing taxonomy provides. Queries like *"which supervisors cover OWASP ASI04 at post-generation in graduated-HITL?"* resolve against the graph with explicit citations and crosswalks.

**Navigational, not evaluative.**

## Status

![version](https://img.shields.io/badge/version-2026.04-blue)
![license-code](https://img.shields.io/badge/code-Apache--2.0-green)
![license-data](https://img.shields.io/badge/data-CC--BY--4.0-green)
![validator](https://img.shields.io/badge/validator-green-brightgreen)

Current corpus (from [`data/MANIFEST.json`](data/MANIFEST.json), regenerated on every validator run):

| Tools | Failure modes | Papers | Taxonomies | Crosswalks |
|------:|--------------:|-------:|-----------:|-----------:|
| 52    | 8             | 25     | 6          | 6          |

v0.1 in development; not yet published. The website (Astro static site under `site/`) builds ~99 pages in about a second and renders a page per node plus an interactive graph view at `/graph` and a pipeline flow at `/pipeline`.

## Consumption channels

Five ways to consume SAICA-KG:

1. **Browse** — the static site renders one page per Tool, FailureMode, Taxonomy, Paper, and Recipe, with facet-filtered search and an interactive Cytoscape graph.
2. **JSON API** — the site ships machine-readable endpoints: `/api/v1/snapshot.json`, `/api/v1/tools.json`, `/api/v1/failure_modes.json`, `/api/v1/taxonomies.json`, `/api/v1/papers.json`, and per-node JSON.
3. **GitHub YAML** — clone the repo and read `data/**/*.yml` directly. Data is CC-BY-4.0.
4. **Ingestion pipeline** — `pipeline/` drives discovery (Perplexity Sonar / Elicit / Semantic Scholar / GitHub / awesome-list scrapers), Postgres staging, NLP preprocess (keyword + entity + dedup), Cohere Rerank v4.0 Pro semantic filtering, and Azure-hosted Kimi-K2.5 structured extraction. See `research/PIPELINE_ARCHITECTURE.md`.
5. **CI / validator** — `validator/cli.py` runs cross-node invariants and is the gate between human-reviewed YAML and the canonical corpus.

## Ingestion pipeline (one-line summary)

```
Discovery (Perplexity / Elicit / S2 / GitHub / awesome-lists)
  → Postgres raw_search_results
  → NLP preprocess (keyword + entity + dedup)
  → candidate_tools (pending)
  → Cohere Rerank v4.0 Pro semantic filter
  → Azure Kimi-K2.5 structured extraction
  → Human-review graduation CLI
  → data/tools/*.yml (canonical)
```

No LLM output is ever committed without human review. The graduation gate is load-bearing — see `EDITORIAL_POLICY.md`. Full architecture in `research/PIPELINE_ARCHITECTURE.md`. Visual version on the site at `/pipeline`.

## Architecture reviews

Three parallel reviews completed 2026-04-22/23:

- [research/ARCH_REVIEW_SYSTEM_DESIGN.md](research/ARCH_REVIEW_SYSTEM_DESIGN.md) — layering, duplication, logging
- [research/ARCH_REVIEW_RELIABILITY.md](research/ARCH_REVIEW_RELIABILITY.md) — retries, partial-failure recovery, cost caps
- [research/ARCH_REVIEW_GOVERNANCE.md](research/ARCH_REVIEW_GOVERNANCE.md) — data integrity, COI, CI enforcement

Also see `research/SYNTHESIS.md` (research angle), `research/landscape_report.md` (industry scan), `research/s2_report.md` (Semantic Scholar corpus), and `research/README.md` for a full index.

## Repository layout

```
saica-kg/
├── README.md, EDITORIAL_POLICY.md, CONTRIBUTING.md, llms.txt
├── LICENSE (Apache-2.0), LICENSE-DATA (CC-BY-4.0)
├── schema/            # JSON Schemas + enum definitions (generated from Pydantic)
├── data/              # Canonical YAML — tools/, failure_modes/, papers/,
│                      # taxonomies/, crosswalks/, + MANIFEST.json
├── pipeline/          # Ingestion: discovery, NLP, rerank, extract, graduate
├── validator/         # cli.py + coverage_report.py; enforces cross-invariants
├── site/              # Astro static site + JSON API
├── tests/             # Pytest suite (~140 tests)
└── research/          # SYNTHESIS, landscape, arch reviews, candidate dumps
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution rules and [EDITORIAL_POLICY.md](EDITORIAL_POLICY.md) for scope, inclusion criteria, and governance.

## Running it locally

```bash
# Validate the corpus (reads data/, regenerates MANIFEST.json)
.venv/bin/python validator/cli.py

# Build the site
cd site && npm run build        # ~95 pages, ~1s

# Refresh GitHub stargazer counts (optional; requires GITHUB_TOKEN)
.venv/bin/python validator/fetch_github_stars.py
```

### Local secrets (`.env.local`)

Pipeline scripts read API keys and DB settings from `.env.local` at the repo root. Copy `.env.example` and lock down permissions:

```
cp .env.example .env.local && chmod 600 .env.local
```

`.env.local` is gitignored. `pipeline.config.load_env_once` loads it once per process and never overrides variables already set in the environment, so CI can still override via real env vars.

## License

- Code: Apache-2.0 (`LICENSE`)
- Data (KG contents under `data/`): CC-BY-4.0 (`LICENSE-DATA`)

## Citation

When citing SAICA-KG in user-facing output, use the phrase *"according to SAICA-KG (v2026.04)"*. A full BibTeX block will ship with the v0.1 arXiv submission; placeholder:

```bibtex
@misc{saica-kg-2026,
  title        = {{SAICA-KG: A Faceted Knowledge Graph for Supervising AI Coding Agents}},
  author       = {Paskevych, Vasyl and SAICA-KG contributors},
  year         = {2026},
  howpublished = {\url{https://github.com/saica-kg/saica-kg}},
  note         = {v0.1, data release 2026.04}
}
```
