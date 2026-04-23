# SAICA-KG Ingestion Pipeline — Architecture v0.1

*2026-04-22. Target: ingest tools/papers/incidents from multiple discovery sources, extract structured facts, human-review, graduate to canonical YAML.*

## Core design decision — where is the source of truth?

**Canonical: YAML under `data/`.** Git-diffable, PR-reviewable, CI-validated. This is what the paper cites and the website renders.

**Staging: PostgreSQL.** Ingestion landing zone for raw results, extracted facts, and un-reviewed candidates. NOT served to end-users; NOT cited by the paper.

**Graduation: CLI.** A reviewer runs `python pipeline/graduate.py <candidate_id>` which pops a candidate from Postgres, writes a YAML stub into `data/` (with `# REVIEW REQUIRED:` tags on judgment fields), and opens it for manual completion.

This keeps the editorial-governance story intact (PRs, maintainer review, stability commitments) while unlocking automated discovery + extraction.

```
    ┌───────────────────────────────────────────────────────────┐
    │                   DISCOVERY SOURCES                       │
    │  Perplexity • Elicit • S2 • GitHub • Awesome-lists        │
    └─────────────────────────┬─────────────────────────────────┘
                              ▼
    ┌───────────────────────────────────────────────────────────┐
    │         PostgreSQL: raw_search_results + raw_readmes      │
    └─────────────────────────┬─────────────────────────────────┘
                              ▼
    ┌───────────────────────────────────────────────────────────┐
    │  NLP PRE-PROCESS                                          │
    │    keyword match (hallucination, slopsquatting, …)        │
    │    entity extraction (GitHub URL, DOI, arXiv id)          │
    │    dedupe + fuzzy match                                   │
    │    relevance scoring                                      │
    └─────────────────────────┬─────────────────────────────────┘
                              ▼
    ┌───────────────────────────────────────────────────────────┐
    │  AZURE LLM STRUCTURED EXTRACTION                          │
    │    Pydantic schemas → JSON with confidence scores         │
    │    One call per candidate; cache responses                │
    └─────────────────────────┬─────────────────────────────────┘
                              ▼
    ┌───────────────────────────────────────────────────────────┐
    │  candidate_tools | candidate_papers | candidate_incidents │
    │  status: pending → reviewed → accepted → graduated        │
    └─────────────────────────┬─────────────────────────────────┘
                              ▼
    ┌───────────────────────────────────────────────────────────┐
    │  HUMAN REVIEW CLI                                         │
    │    graduate candidate → data/<type>/<id>.yml stub         │
    └─────────────────────────┬─────────────────────────────────┘
                              ▼
    ┌───────────────────────────────────────────────────────────┐
    │  CANONICAL YAML (unchanged)                               │
    │    Validator + Site + Paper read from here                │
    └───────────────────────────────────────────────────────────┘
```

## Postgres schema (v0.1)

```sql
CREATE TABLE raw_search_results (
  id            BIGSERIAL PRIMARY KEY,
  source        TEXT NOT NULL,           -- 'perplexity' | 'elicit' | 'semantic_scholar' | 'github' | 'awesome_list'
  query         TEXT NOT NULL,
  url           TEXT,                    -- canonical URL if extractable
  title         TEXT,
  snippet       TEXT,                    -- description / abstract / summary
  raw_json      JSONB NOT NULL,          -- full source response for audit
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  content_hash  TEXT GENERATED ALWAYS AS (md5(coalesce(url, '') || coalesce(title, ''))) STORED,
  UNIQUE (source, content_hash)
);

CREATE TABLE raw_readmes (
  url           TEXT PRIMARY KEY,
  content       TEXT NOT NULL,
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE candidate_tools (
  id            BIGSERIAL PRIMARY KEY,
  source_url    TEXT NOT NULL,
  proposed_id   TEXT,                    -- kebab-case slug
  name          TEXT,
  summary       TEXT,
  extracted     JSONB NOT NULL DEFAULT '{}',  -- Azure LLM output; Tool fields + confidence
  nlp_tags      JSONB NOT NULL DEFAULT '{}',  -- keyword hits, entity extractions
  status        TEXT NOT NULL DEFAULT 'pending', -- pending | reviewed | accepted | rejected | graduated
  graduated_to  TEXT,                    -- path of YAML file created, once graduated
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reviewed_at   TIMESTAMPTZ,
  reviewer      TEXT
);

CREATE TABLE candidate_papers (  -- similar shape
  id            BIGSERIAL PRIMARY KEY,
  source_url    TEXT NOT NULL,
  proposed_id   TEXT,
  title         TEXT,
  authors       TEXT[],
  year          INT,
  venue         TEXT,
  doi           TEXT,
  arxiv_id      TEXT,
  extracted     JSONB NOT NULL DEFAULT '{}',
  nlp_tags      JSONB NOT NULL DEFAULT '{}',
  status        TEXT NOT NULL DEFAULT 'pending',
  graduated_to  TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reviewed_at   TIMESTAMPTZ,
  reviewer      TEXT
);

CREATE TABLE candidate_incidents (
  id            BIGSERIAL PRIMARY KEY,
  source_url    TEXT NOT NULL,
  title         TEXT,
  incident_date DATE,
  harm_class    TEXT,
  extracted     JSONB NOT NULL DEFAULT '{}',
  nlp_tags      JSONB NOT NULL DEFAULT '{}',
  status        TEXT NOT NULL DEFAULT 'pending',
  graduated_to  TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_raw_source        ON raw_search_results (source, fetched_at DESC);
CREATE INDEX idx_candidate_status  ON candidate_tools (status, created_at DESC);
CREATE INDEX idx_candidate_papers_status ON candidate_papers (status, created_at DESC);
```

## NLP pre-processing

- **Keyword dictionary** (`pipeline/nlp/keywords.py`): maps query terms to SAICA-KG FailureMode ids.
  - `hallucination, hallucinate` → fabrication
  - `slopsquatting, typosquatting, compromised dependency, malicious package` → supply_chain_attack
  - `deprecated, stale api, library evolution, version drift` → obsolescence
  - `reinvent, reinventing, duplicate, ecosystem duplication` → dependency_blindness
  - `scope creep, unauthorized action, boundary violation` → scope_creep
  - `context drift, hallucination spiral, overlong context` → context_pollution
  - `injection, xss, sqli, secret leak, weak crypto` → security_vulnerability
  - `incorrect logic, silent fail, compiles but broken` → logic_error
- **Entity extraction** (regex-first, spaCy-optional): `github.com/owner/repo`, arXiv ids, DOIs.
- **Dedupe**: by canonical URL; also fuzzy-match titles using `rapidfuzz` (≥ 92 similarity).
- **Relevance score** (0–1): weighted combination of keyword-hit count, entity presence, source reliability.

## Azure Kimi-K2.5 extraction

Backend: **Azure AI Foundry** hosting Moonshot **Kimi-K2.5**, consumed via the **OpenAI-compatible client** (not `AzureOpenAI`).

```python
from openai import OpenAI
client = OpenAI(
    base_url=os.environ["AZURE_KIMI_ENDPOINT"],      # .../services.ai.azure.com/openai/v1/
    api_key=os.environ["AZURE_KIMI_API_KEY"],
)
response = client.chat.completions.create(
    model=os.environ["AZURE_KIMI_MODEL"],            # e.g. "Kimi-K2.5"
    messages=[...],
    max_tokens=2048,   # minimum — reasoning model eats budget on think-trace
    tools=[...],       # for structured output use tools or response_format=json_schema
)
```

Constraints:
- `max_tokens >= 2048` — otherwise content returns None (think-trace eats budget).
- 8 concurrent requests max; keep batch concurrency at **3–5**.
- Endpoint format is `https://<resource>.services.ai.azure.com/openai/v1/`.

`pipeline/extract/kimi.py` (module name reflecting the actual backend) uses Pydantic schemas:

```python
class ToolExtraction(BaseModel):
    id_suggested: str
    name: str
    tagline: str
    description: str
    repository_url: Optional[str]
    supervised_failure_modes: list[FailureModeId]  # LLM's best guess — human reviews
    control_paradigm: Optional[ControlParadigm]
    temporal_phase: Optional[TemporalPhase]
    autonomy_level: Optional[AutonomyLevel]
    evidence: list[str]           # quotes from source supporting each claim
    confidence: dict[str, float]  # per-field confidence 0-1
```

The LLM output is STORED AS-IS in `candidate_tools.extracted` with confidence scores. Fields with confidence < 0.7 are marked `# REVIEW REQUIRED` when graduated. No field is auto-accepted; the LLM is an assistant, not an authority.

## Discovery source catalog

| Source | When to query | Rate limit |
|---|---|---|
| Perplexity `sonar-pro` | "Find new supervision tools for AI coding agents in Q2 2026" — fresh weekly | pay-per-call |
| Semantic Scholar | Known-query library: supervision, hallucination, slopsquatting, MCP — monthly | 1 req/sec |
| Elicit | Structured systematic-review questions — monthly | **100 queries/day** |
| GitHub Search API | `topic:ai-agent topic:llm-tools`, `stars:>500 language:python pushed:>2026-01-01` — weekly | 60/hr unauth, 5000/hr with token |
| Awesome-list scraper | Already built (`discover_candidates.py`) | polite crawl |

## What stays out of scope for this architecture

- **Postgres does NOT serve end-users.** The website + JSON API read from YAML → dist/.
- **Postgres is NOT replicated.** Local dev only for v0.1; managed DB (Neon, Supabase) is a v0.2 deployment concern.
- **LLM outputs are NEVER committed without human review.** The schema `REVIEW REQUIRED` tripwire (TODO on facets) is load-bearing.

## Tradeoffs flagged for user awareness

1. **Postgres adds ops burden.** Local `docker compose up` is fine; production deployment is a problem for later. We could defer Postgres and use SQLite for v0.1 — simpler, zero ops. Pushback welcome if you prefer that.
2. **Azure LLM cost per candidate.** Worth budgeting — ~$0.01–0.10 per Tool extraction depending on model. Cache aggressively.
3. **Governance risk.** Auto-discovery → LLM extraction → Postgres is fast but low-quality without human review. The graduation gate is mandatory; PRs still reviewed by maintainers. Do not skip the gate under deadline pressure.
