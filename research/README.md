# SAICA-KG Research Directory

One-line index of every research artefact under `research/`. These files back the SAICA-KG paper and the ingestion pipeline; they are not served by the website but are referenced from the top-level `README.md`, `/about`, and `/pipeline`.

## Synthesis and framing

| File | What it is |
|---|---|
| [`SYNTHESIS.md`](SYNTHESIS.md) | Sharpened angle after three parallel research runs: where SAICA-KG sits in the 2026 landscape and what the specific gap looks like. |
| [`landscape_report.md`](landscape_report.md) | Industry / registry / vendor-doc / awesome-list scan. Answers the "is anyone else already doing this?" question. |

## Architecture reviews (2026-04-22 / 23)

| File | Angle |
|---|---|
| [`ARCH_REVIEW_SYSTEM_DESIGN.md`](ARCH_REVIEW_SYSTEM_DESIGN.md) | Layering, duplication, logging, concurrency. |
| [`ARCH_REVIEW_RELIABILITY.md`](ARCH_REVIEW_RELIABILITY.md) | Retries, partial-failure recovery, cost caps, secret hygiene. |
| [`ARCH_REVIEW_GOVERNANCE.md`](ARCH_REVIEW_GOVERNANCE.md) | CI enforcement, COI, id-immutability, taxonomy drift. |

## Pipeline

| File | What it is |
|---|---|
| [`PIPELINE_ARCHITECTURE.md`](PIPELINE_ARCHITECTURE.md) | Canonical architecture doc. Discovery sources, Postgres schema, NLP preprocess, Azure Kimi-K2.5 extraction, Cohere rerank, human-review graduation. The `/pipeline` site page is the visual version of this. |
| [`bulk_ingest_20260423070759.md`](bulk_ingest_20260423070759.md) | Log line from the most recent bulk ingest run (timestamped). |

## Semantic Scholar corpus (341 papers, 18 queries)

| File | What it is |
|---|---|
| [`s2_report.md`](s2_report.md) | Synthesis: top papers by theme, recommendations into the KG. |
| [`s2_ranked.md`](s2_ranked.md) | Full ranked corpus — 341 papers with relevance scores. |
| [`s2_raw/`](s2_raw/) | Raw Semantic Scholar JSON, one file per query. |

## Elicit systematic review

| File | What it is |
|---|---|
| [`elicit_report.md`](elicit_report.md) | Synthesis of 4 structured systematic-review queries (40 papers, from a per-day budget of 100). |
| [`elicit_raw/`](elicit_raw/) | Raw Elicit responses per query (`Q1.json` … `Q4.json`). |

## Coverage and candidates

| File | What it is |
|---|---|
| [`coverage_report.md`](coverage_report.md) | Which MECE cells and FailureModes are under-covered; produced by `validator/coverage_report.py`. Never blocks CI. |
| [`coverage_report.json`](coverage_report.json) | Machine-readable version of the same. |
| [`candidates_20260422.md`](candidates_20260422.md) | Human-readable candidate pool (2675 rows) from the 2026-04-22 bulk discovery run. |
| [`candidates_20260422.json`](candidates_20260422.json) | Same, JSON. Pipeline reads this. |

## Supporting scripts

| File | What it is |
|---|---|
| [`analyze.py`](analyze.py) | Ad-hoc analysis helper used while drafting reports. |
| [`run_searches.sh`](run_searches.sh) | Bash driver that kicks off the discovery queries. |

---

All documents here are editorial artefacts, not canonical KG data. Canonical data lives under `data/` and is the only thing the paper cites and the website renders.
