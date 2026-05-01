# SAICA-KG

> A curated knowledge graph of failure modes for AI coding agents and the
> supervision tools that address them.

## What this is

A static, human-reviewed reference: a faceted catalog of ~100 supervision
tools, an 11-mode failure-mode taxonomy with crosswalks to OWASP / MAST /
DAPLab / Microsoft AIRT, an incident corpus, named recipes, and tooling
that turns all of it into a one-shot setup recommendation. It is consumed
as **injected context** at project setup, not as a runtime service queried
per tool action.

## What this is NOT

- Not a runtime service called per-tool-action.
- Not a replacement for an agent's own judgment.
- Not a research database that needs constant querying.
- Not an LLM — it doesn't reason, it indexes and ranks.

## How to use it (in priority order)

### 1. Drop the skill file into your agent's context

`SKILLS.md` is regenerated from the corpus by
`validator/generate_skills.py` and lists the named "what to watch for"
supervision concerns plus the recipes that fix them. Copy it into
`.claude/skills/`, `.cursor/rules/`, `.windsurfrules`, or whichever
skills directory your agent reads. Your agent reads it as plain context
on every session — no service call, no latency.

### 2. Audit your repo's supervision coverage (one-shot)

```bash
python -m pipeline.audit.cli https://github.com/<owner>/<repo>
```

Returns a coverage grid (which of the 11 failure modes your existing
stack already supervises), a ranked gap list, and 2–3 tailored
recommendations per gap matched to your detected language / CI / agent.
Run once at project setup. Re-run when your stack materially changes.

### 3. Get a tailored supervision-tool recommendation (one-shot)

```bash
python -m pipeline.mcp.server   # then call saica_recommend from your agent
```

Or read [`RECOMMENDATIONS.md`](RECOMMENDATIONS.md) /
[`recommendations.json`](recommendations.json) directly — both are
pre-computed and committed. Three tiers: **minimum** (1 tool, fast
onboarding), **optimal** (3 tools, default), **full / MECE** (4–5 tools
that together cover all 11 failure modes).

## What's in the KG

Live counts from [`data/MANIFEST.json`](data/MANIFEST.json) (KG version
2026.05):

- **103** supervision tools, faceted by paradigm × phase × autonomy ×
  surface × failure-mode coverage
- **11** failure modes (`scope_creep`, `fabrication`,
  `security_vulnerability`, `supply_chain_attack`, `logic_error`,
  `cascading_failure`, `context_pollution`, `obsolescence`,
  `test_manipulation`, `dependency_blindness`, `incomplete_execution`)
- **55** papers
- **6** external taxonomies + **6** crosswalks (OWASP Agentic Top 10,
  MAST, DAPLab, Microsoft AIRT, …)
- **18** real-world incidents
- **10** named recipes (e.g. `scope-creep-bounded-autonomous-agent`,
  `fabrication-resistant-python-agent`, `supply-chain-hardened-agent`)

## How the recommender ranks tools

Selection is **likelihood × impact × reliability**. Per-failure-mode
likelihood and impact live in
[`data/failure_mode_priorities.yml`](data/failure_mode_priorities.yml)
(hybrid: KG tool-coverage prior + editorial calibration against Shah
2026 / DAPLab evidence). Reliability is a bounded combiner of log-stars,
github-trending boost, citation count, and maturity, computed in
[`pipeline/shared/priorities.py`](pipeline/shared/priorities.py) and
[`pipeline/shared/trending.py`](pipeline/shared/trending.py). Coding-agent
peers are filtered out so a Cursor user is never told to install Claude
Code, and vice versa.

## How to contribute

Data is YAML under [`data/`](data/) (CC-BY-4.0). Add a tool by writing
`data/tools/<id>.yml`, run `python validator/cli.py` to confirm 0
errors, open a PR. The validator runs in CI. Editorial scope and
inclusion criteria are in [`EDITORIAL_POLICY.md`](EDITORIAL_POLICY.md);
contribution mechanics are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## When this corpus is most useful

- The first 30 minutes of a new agentic-AI project (audit + recommend +
  drop in `SKILLS.md`).
- When you're reading a paper that cites a failure-mode taxonomy and
  want to translate it into a different one (the crosswalks).
- When you want a list of named "what to watch for" supervision concerns
  injected into your agent's context (`SKILLS.md`).

## When it's NOT useful

- As a per-tool-call lookup mid-task. Too slow, wrong shape, and your
  agent already has enough training-level knowledge of the basic
  vocabulary. Use `SKILLS.md` instead.
- As an LLM substitute. SAICA-KG indexes; it doesn't reason.

## SAICA Index — weekly supervision leaderboard

[`/leaderboard`](https://saica-kg.dev/leaderboard) audits a curated
list of repos AI coding agents touch a lot (FastAPI, langchain, Astro,
Pydantic, etc.). PR against
[`data/saica_index/seed_repos.yml`](data/saica_index/seed_repos.yml) to
add one.

Each repo gets a letter grade A–F. The scoring formula lives at
[`pipeline/saica_index/score.py`](pipeline/saica_index/score.py) — per-
failure-mode coverage tier (1 → 0.40, 2 → 0.70, 3 → 1.00) plus a
paradigm-diversity bonus (+0.10 for ≥2 control paradigms), weighted by
FM priority (likelihood × impact). Thresholds biased harsh on purpose
so an A feels earned. Regenerated weekly by
[`.github/workflows/saica-index.yml`](.github/workflows/saica-index.yml).

Run it locally:

```bash
.venv/bin/python -m pipeline.saica_index.runner --limit 5
open http://localhost:4321/leaderboard
```

## Live site

[https://saica-kg.dev](https://saica-kg.dev) (when deployed) — browse
the corpus, run an audit from the web, see the leaderboard, ask the
chat box. The site is a mirror of `data/`, not the source of truth.

## License

- Code: Apache-2.0 ([`LICENSE`](LICENSE))
- Data (everything under `data/`): CC-BY-4.0
  ([`LICENSE-DATA`](LICENSE-DATA))

## Cite

```bibtex
@misc{saica-kg-2026,
  title        = {{SAICA-KG: A Faceted Knowledge Graph for Supervising AI Coding Agents}},
  author       = {Paskevych, Vasyl and SAICA-KG contributors},
  year         = {2026},
  howpublished = {\url{https://github.com/saica-kg/saica-kg}},
  note         = {v0.1, data release 2026.05}
}
```

---

*Acknowledgement: the framing in this README — "curated dataset best
consumed as injected context, not a library called at runtime" —
sharpened in response to external Replit-Agent feedback (2026-05-01).
The critique was largely correct; see
[`research/MCP_ASSESS_ROADMAP.md`](research/MCP_ASSESS_ROADMAP.md) §10.*
