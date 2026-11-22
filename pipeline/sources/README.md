# pipeline/sources/ — discovery sources

> **Dormant since 2026-04-23.** These discovery sources feed the Postgres ingestion pipeline (discovery → NLP
> preprocess → rerank → LLM extraction → graduation), which ran for one night, 2026-04-22/23. Every row in the
> staging database dates from those hours; 4 of today's 49 tool nodes came through it, and no paper or
> incident did. The catalogue has been curated by hand and by one-off scripts since. Nothing is scheduled,
> the Azure model deployment it called returned 404 in November 2026, and several statements below
> describe a design that was not built or not followed (thresholds, the review gate, the reranker's role):
> see `research/review_20261121_r2/pipeline_validator.md`, PV-02 to PV-04 and PV-15. The code is kept, not
> archived (owner decision, 2026-11-21). What is still live in `pipeline/`: `models.py` (the schema
> source), `config.py`, `cost_caps.py`, `embeddings/compute.py` and `query.py`, `maturity/`, and the served
> packages `ask/`, `audit/`, `mcp/`, `supervision/`, `saica_index/`, `shared/`, `webapp.py`.
>
> Rows these modules ever stored: github 103, perplexity 15, elicit 0 (one call), semantic_scholar 0.
> Corrections to the text below: the Semantic Scholar key is read from `SEMANTIC_SCHOLAR_API_KEY` (not
> `S2_API_KEY`); the table is `raw_search_results` (not `raw_results`); fixtures live in
> `pipeline/sources/tests/fixtures/`. `data/trending.json` was last scraped on 2026-05-01 and none of its
> repositories is in the catalogue.

Each module in this package wraps one external discovery source. They all
land their results in the staging Postgres tables (see `pipeline/db.py`)
*except* `github_trending`, which writes a small JSON snapshot directly to
`data/trending.json` for the read-side ranker in
`pipeline.shared.trending`.

| Module | Source | Auth | Output |
|---|---|---|---|
| `perplexity.py` | Perplexity Sonar search | `PERPLEXITY_API_KEY` | `raw_results` |
| `elicit.py` | Elicit paper search | `ELICIT_API_KEY` | `raw_results` |
| `semantic_scholar.py` | Semantic Scholar Graph API | `S2_API_KEY` (optional) | `raw_results` |
| `github.py` | GitHub `/search/repositories` + READMEs | `GITHUB_TOKEN` (optional) | `raw_results`, `raw_readmes` |
| `github_trending.py` | github.com/trending HTML scrape | none (public) | `data/trending.json` |
| `arxiv_recent.py` | export.arxiv.org Atom feed (recent submissions in cs.SE / cs.AI / cs.LG) | none (public) | `data/arxiv_candidates.json` |

## github_trending — trending ranking signal

Visits `github.com/trending` (daily + weekly × all/python/typescript/rust),
classifies each unique repo as either already in the KG (`matched_in_kg`)
or a new candidate to triage (`new_candidates`). For each new candidate
we fetch the README, score it against a hand-tuned weighted-keyword map,
and only keep repos whose score crosses
`RELEVANCE_THRESHOLD`. Failure-mode tagging reuses
`pipeline.audit.kg.FM_KEYWORDS` so the rule stays identical to the
heatmap.

Run it:

```bash
.venv/bin/python -m validator.screen_trending           # real scrape
.venv/bin/python -m validator.screen_trending --no-network   # cache only
.venv/bin/python -m validator.screen_trending --dry          # no writes
```

The orchestrator lives in `validator/screen_trending.py`; this module is
just pure functions. Polite-scraper defaults: 2.0s minimum interval,
`SAICA-KG-Trending-Bot/0.2` User-Agent, 8 pages per run.

Tests are network-free and use `tests/fixtures/trending_sample.html`:

```bash
.venv/bin/python -m pytest pipeline/sources/tests -q
```

## arxiv_recent — recent-submission discovery signal

Polls `export.arxiv.org` for the last `--lookback-days` (default 30) of
submissions in `cs.SE`, `cs.AI`, `cs.LG` (and optionally `cs.CL`),
dedupes by arxiv id, and routes each entry to either `matched_in_kg`
(already in `data/papers/*.yml`) or `new_candidates` (above the same
0.4 relevance threshold). The orchestrator lives in
`validator/screen_arxiv.py`. Polite-scraper defaults: 3.0s minimum
interval, `SAICA-KG-Arxiv-Bot/0.1` User-Agent, per-day per-category
disk cache under `.cache/arxiv/`, paginated until the lookback window
is exhausted (capped at 1000 entries / category).

```bash
.venv/bin/python -m validator.screen_arxiv                   # real scrape
.venv/bin/python -m validator.screen_arxiv --no-network      # cache only
.venv/bin/python -m validator.screen_arxiv --dry             # no writes
.venv/bin/python -m validator.screen_arxiv --lookback-days 60 --categories cs.SE,cs.AI,cs.LG,cs.CL
```

Tests use `tests/fixtures/arxiv_sample.xml` and are network-free.
