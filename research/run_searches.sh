#!/usr/bin/env bash
set -euo pipefail
source /Users/vasyl/saicakg/.env.local

OUTDIR="/Users/vasyl/saicakg/research/s2_raw"
mkdir -p "$OUTDIR"

FIELDS="title,abstract,year,citationCount,venue,authors,url,externalIds,tldr"
LIMIT=20

declare -a QUERIES=(
  "supervising-ai-coding-agents|supervising AI coding agents"
  "llm-code-failure-taxonomy|LLM code generation failure taxonomy"
  "package-hallucination-slopsquatting|package hallucination slopsquatting"
  "code-gen-hallucination-classification|code generation hallucination classification"
  "kg-software-tools-taxonomy|knowledge graph software tools taxonomy"
  "mece-classification-se|MECE classification software engineering"
  "agent-control-paradigm-prevention-detection|agent control paradigm prevention detection"
  "code-reinvention-duplicate-detection-llm|code reinvention duplicate detection LLM"
  "self-debug-reflexion-coding-agent|self-debug reflexion coding agent"
  "sandboxed-execution-ai-code-agent|sandboxed execution AI code agent"
  "hitl-code-generation|HITL human in the loop code generation"
  "mcp-evaluation|model context protocol MCP evaluation"
  "retrieval-augmented-code-generation|retrieval augmented code generation"
  "llm-code-guardrails-structured-output|LLM code guardrails structured output"
  "software-supply-chain-llm-attack|software supply chain LLM attack"
  "agent-trajectory-supervision-monitoring|agent trajectory supervision monitoring"
  "faceted-classification-kg-survey|faceted classification knowledge graph survey"
  "deprecated-api-detection-llm|deprecated API detection LLM"
)

for entry in "${QUERIES[@]}"; do
  slug="${entry%%|*}"
  query="${entry##*|}"
  outfile="$OUTDIR/$slug.json"
  echo "=== $slug: $query ==="
  # URL encode the query using python3
  encoded=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1]))" "$query")
  url="https://api.semanticscholar.org/graph/v1/paper/search?query=${encoded}&limit=${LIMIT}&fields=${FIELDS}"
  http_code=$(curl -sS -o "$outfile" -w "%{http_code}" \
    -H "x-api-key: $SEMANTIC_SCHOLAR_API_KEY" \
    "$url" || echo "000")
  echo "  -> HTTP $http_code, $(wc -c < "$outfile") bytes"
  sleep 1.3
done

echo "All done."
