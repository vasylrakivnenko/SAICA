# SAICA-Bench

> Can Language Models catch coding agents' failures? A benchmark of the
> tools and models that supervise AI coding agents, plus SAICA-KG, the
> knowledge graph of failure modes and supervision tools behind it.

**Website: [saica.ai](https://saica.ai)** ·
[Leaderboard](https://saica.ai/) ·
[Findings](https://saica.ai/findings/) ·
[Benchmark](https://saica.ai/benchmark/) ·
[Failure modes](https://saica.ai/failure-modes/) ·
[Tools](https://saica.ai/tools/) ·
[Results JSON](https://saica.ai/bench/results.json)

SAICA-Bench measures how well supervision tools and language models catch
the typical failures of AI coding agents. Each sample is a task plus what
an agent produced for it (a patch, a function or a whole session),
labelled bad if it contains the failure and clean if it does not. Labels
come from public datasets confirmed by execution or expert review
(Delulu, Patronus TRACE, SusVibes, Collu-Bench, SWE-rebench-OpenHands
trajectories) or from matched pairs that differ only in the failure.
Every reviewer sees the same samples without the labels: free programs
(type checkers, linters, simple rules), AI code reviewers and evaluation
frameworks (PR-Agent, promptfoo, giskard, DeepEval, Opik, Arize Phoenix,
uqlm), and plain language models asked directly with one fixed prompt.
The score is **J = TPR − FPR**: the share of bad samples a reviewer flags
minus the share of clean samples it flags (0% = chance, 100% = perfect),
reported with the cost per 1,000 reviews.

## Current results

Best reviewer per failure mode, results of 2026-11-20 (source:
[`site/public/bench/results.json`](site/public/bench/results.json); the
[leaderboard](https://saica.ai/) has every tool, confidence intervals and
cost). "Best tool" excludes plain models and our own baseline rules.

| Failure mode | Bad / clean samples | Best reviewer | J | Best tool | J |
|---|---|---|---|---|---|
| [Fabrication](https://saica.ai/failure-modes/fabrication/) | 348 / 288 | deepseek-v4.1-flash, asked directly | +94% | pyright | +85% |
| [Test manipulation](https://saica.ai/failure-modes/test-manipulation/) | 56 / 249 | minimax-m3, asked directly | +91% | giskard Conformity check | +89% |
| [Security vulnerability](https://saica.ai/failure-modes/security-vulnerability/) | 1,243 / 459 | gpt-oss-20b (self-hosted), asked directly | +8% | giskard Conformity check | +6% |
| [Logic error](https://saica.ai/failure-modes/logic-error/) | 1,536 / 904 | mimo-v2.6-flash, asked directly | +74% | uqlm CodeGenUQ | +59% |
| [Incomplete execution](https://saica.ai/failure-modes/incomplete-execution/) | 600 / 600 | gpt-6-luna, asked directly | +19% | PR-Agent review + TODO scan | +7% |
| [Scope creep](https://saica.ai/failure-modes/scope-creep/) | 175 / 175 | mimo-v2.6-flash, asked directly | +95% | none measured yet | |
| [Obsolescence](https://saica.ai/failure-modes/obsolescence/) | 155 / 155 | gpt-6-luna, asked directly | +90% | pyright (latest libraries) | +57% |
| [Supply-chain attack](https://saica.ai/failure-modes/supply-chain-attack/) | 148 / 148 | typosquat-name rule (baseline) | +84% | none measured yet | |
| [Dependency blindness](https://saica.ai/failure-modes/dependency-blindness/) | 50 / 50 | gpt-6-luna, asked directly | +90% | none measured yet | |

What the grid says (more on the [findings](https://saica.ai/findings/) page):

- A cheap model asked directly is the best reviewer in 8 of 9 modes; on
  supply chain a typosquat rule wins.
- Security vulnerability and incomplete execution are unsolved: no model,
  program or judge we ran reaches J 25% there.
- Free programs pay off where the failure is a checkable fact (pyright on
  fabrication and obsolescence). Wrapping a model in a review tool did not
  help: PR-Agent on deepseek-v4-flash scores below deepseek-v4-flash asked
  directly in 4 of 4 modes.

Read before citing: J compares tools within a mode. Datasets were built
differently (real agent runs, execution-checked model code, synthetic
injections, hand-built pairs), so J across modes only roughly reflects
difficulty; each mode's setup and caveats are on the
[benchmark](https://saica.ai/benchmark/) page. Cascading failure and
context pollution are not benchmarked yet (no dataset with confirmed
labels). Each mode's harness, data notes and scores live under
[`bench/<mode>/`](bench/); `python bench/build_report.py` rebuilds
`results.json` from them.

## SAICA-KG: the knowledge graph behind the benchmark

> A curated knowledge graph of failure modes for AI coding agents and the
> supervision tools that address them.

### What this is

A static, human-reviewed reference: a faceted catalog of supervision
tools, an 11-mode failure-mode taxonomy with crosswalks to OWASP / MAST /
DAPLab / Microsoft AIRT, an incident corpus, named recipes, and tooling
that turns all of it into a one-shot setup recommendation. It is consumed
as **injected context** at project setup, not as a runtime service queried
per tool action. SAICA-Bench takes its failure modes and its tool list
from it.

### What this is NOT

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

For a kit built from measured results instead of catalog tags, use
[saica.ai/tool-coverage](https://saica.ai/tool-coverage/).

## What's in the KG

Live counts from [`data/MANIFEST.json`](data/MANIFEST.json) (KG version
2026.11):

- **49** supervision tools, faceted by paradigm × phase × autonomy ×
  surface × failure-mode coverage
- **11** failure modes (`scope_creep`, `fabrication`,
  `security_vulnerability`, `supply_chain_attack`, `logic_error`,
  `cascading_failure`, `context_pollution`, `obsolescence`,
  `test_manipulation`, `dependency_blindness`, `incomplete_execution`)
- **55** papers
- **6** external taxonomies + **6** crosswalks (OWASP Agentic Top 10,
  MAST, DAPLab, Microsoft AIRT, …)
- **18** real-world incidents
- **4** named recipes (e.g. `fabrication-resistant-python-agent`,
  `supply-chain-hardened-agent`, `test-manipulation-resistant-flow`)

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
To propose a tool for the benchmark, or report a wrong number,
[open an issue](https://github.com/vasylrakivnenko/SAICA/issues).

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

## SAICA Index — weekly repo supervision grades

An earlier ranking, kept at
[saica.ai/leaderboard](https://saica.ai/leaderboard/) (the main
leaderboard is now the SAICA-Bench results at [saica.ai](https://saica.ai/)),
audits a curated list of repos AI coding agents touch a lot (FastAPI,
langchain, Astro, Pydantic, etc.). PR against
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

## Install in your AI coding agent

The `saica-supervise` skill ships at two install paths so it works
with both [Claude Code](https://docs.claude.com/en/docs/claude-code)
plugins and the open agent-skills CLI ([`vercel-labs/skills`](https://github.com/vercel-labs/skills),
which targets Replit Agent, Cursor, Codex, OpenCode, and 50+ others).
Both copies are generated from `SKILLS.md` by
`validator/generate_skills.py`, so they never drift.

### Claude Code (plugin)

Run both inside the Claude Code REPL:

```
/plugin marketplace add vasylrakivnenko/SAICA
/plugin install saica-supervise@saica-kg
```

Or sideload during development:

```bash
claude --plugin-dir ./plugin
```

See [`plugin/README.md`](plugin/README.md) for prerequisites and how
the skill stays in sync with `SKILLS.md`.

### Replit Agent / Cursor / Codex / OpenCode / others (`npx skills`)

```bash
npx skills add vasylrakivnenko/SAICA
```

Installs `skills/saica-supervise/SKILL.md` into whichever agent
directory the CLI detects (`.claude/skills/`, `.agents/skills/`,
`.cursor/rules/`, etc.). Scope flags: `-g` for global,
`-a <agent>` to target a specific agent.

**On Replit:** run the command in the **Shell** tab (not the Agent
chat). Confirm with `y` when `npx` asks to fetch the `skills` package.

## Live site

[https://saica.ai](https://saica.ai): the SAICA-Bench leaderboard,
findings, benchmark method, one page per failure mode, the tool catalog
and the knowledge-graph explorer. The site is built from `data/` and
`bench/` results; those stay the source of truth. Machine-readable:
[`/bench/results.json`](https://saica.ai/bench/results.json),
[`/api/v1/snapshot.json`](https://saica.ai/api/v1/snapshot.json),
[`/llms.txt`](https://saica.ai/llms.txt).

## License

- Code: Apache-2.0 ([`LICENSE`](LICENSE))
- Data (everything under `data/`, and the benchmark results):
  [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)

## Cite

See [`CITATION.cff`](CITATION.cff) (GitHub's "Cite this repository"
button reads it), or:

```bibtex
@misc{saica-bench-2026,
  title        = {{SAICA-Bench: Can Language Models Catch Coding Agents' Failures?}},
  author       = {Rakivnenko, Vasyl},
  year         = {2026},
  howpublished = {\url{https://saica.ai}},
  note         = {Code and data: \url{https://github.com/vasylrakivnenko/SAICA}. Results of 2026-11-20}
}
```

---

*Acknowledgement: the framing of SAICA-KG as a "curated dataset best
consumed as injected context, not a library called at runtime" sharpened
in response to external Replit-Agent feedback (2026-05-01). The critique
was largely correct; see
[`research/MCP_ASSESS_ROADMAP.md`](research/MCP_ASSESS_ROADMAP.md) §10.*
