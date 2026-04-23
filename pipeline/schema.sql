-- SAICA-KG ingestion-staging schema v0.1
-- Matches research/PIPELINE_ARCHITECTURE.md section "Postgres schema (v0.1)".

CREATE TABLE IF NOT EXISTS raw_search_results (
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

CREATE TABLE IF NOT EXISTS raw_readmes (
  url           TEXT PRIMARY KEY,
  content       TEXT NOT NULL,
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS candidate_tools (
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
  reviewer      TEXT,
  UNIQUE (source_url)
);

CREATE TABLE IF NOT EXISTS candidate_papers (
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
  reviewer      TEXT,
  UNIQUE (source_url)
);

CREATE TABLE IF NOT EXISTS candidate_incidents (
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

CREATE INDEX IF NOT EXISTS idx_raw_source              ON raw_search_results (source, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_status        ON candidate_tools (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_papers_status ON candidate_papers (status, created_at DESC);
