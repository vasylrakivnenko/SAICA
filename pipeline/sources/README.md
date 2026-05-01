# pipeline/sources/ — discovery sources

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
