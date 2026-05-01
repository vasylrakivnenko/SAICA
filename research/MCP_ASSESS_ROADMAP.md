# SAICA-KG v0.2 — MCP for Agents · Ask SAICA for People · /assess for Quick Audit

**Started:** 2026-04-24
**Owner:** vasyl
**Status:** in-progress
**North star:** practitioner-useful + living project. The paper, if any, is a byproduct of adoption — not the goal.

---

## 1. Vision

SAICA-KG today is a static site + Q&A box. v0.2 turns it into a **live supervision API with two surfaces**:

- **MCP server** for agents (Claude Code first, Cursor / Replit later) — agents call structured tools to look up supervision recommendations, classify a fault they hit, or audit their own repo at session start.
- **Web** for humans — `/ask` (existing chat) and **`/assess` (new)** repo-audit page that takes a GitHub URL and returns a coverage report with concrete gap-filling recommendations.

Both surfaces share a single backend: the existing KG + a new **audit analyzer** (`pipeline/audit/`).

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SAICA-KG v0.2                                │
│                                                                       │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐  │
│  │  MCP server │    │   /ask      │    │  /assess (NEW)          │  │
│  │  (agents)   │    │  (humans)   │    │  (humans)               │  │
│  │             │    │             │    │                         │  │
│  │ saica_lookup│    │  free-form  │    │  GitHub URL → report    │  │
│  │ saica_pre-  │    │  Q&A over   │    │  - coverage heatmap     │  │
│  │   flight    │    │  KG (Kimi)  │    │  - ranked gaps          │  │
│  │ saica_audit_│    │             │    │  - recommendations      │  │
│  │   repo      │    │             │    │  - .md download         │  │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────────────────┘  │
│         │                  │                  │                      │
│         └──────────┬───────┴──────────┬───────┘                      │
│                    ▼                  ▼                              │
│          ┌──────────────────┐  ┌─────────────────────┐               │
│          │ pipeline/audit/  │  │ pipeline/embeddings │               │
│          │ (NEW analyzer)   │  │ pipeline/ask        │               │
│          └─────────┬────────┘  └─────────┬───────────┘               │
│                    └─────────┬───────────┘                           │
│                              ▼                                       │
│                ┌──────────────────────────┐                          │
│                │ data/  (KG: tools,       │                          │
│                │   failure_modes, recipes,│                          │
│                │   crosswalks, papers)    │                          │
│                └──────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘
```

**Key design point:** the audit analyzer is one component used by two callers (`/assess` and `saica_audit_repo`). Same logic, two surfaces.

---

## 3. MCP Server — three tools (MVP)

Module: `pipeline/mcp/server.py`. Library: `mcp.server.fastmcp.FastMCP`. Transport: stdio (Claude Code default), with HTTP option later.

### `saica_lookup(tool_id: str) → ToolRecord`
Structured catalog lookup. Returns full facets, surfaces, composes_with, alternates, KG URL. Deterministic, no LLM call.

### `saica_preflight(action: str, context: str | None, agent_kind: str | None) → PreflightResult`
Pre-action supervision advice. Given a proposed action ("edit src/auth.py", "install left-pad", "run shell command rm -rf X"), KG returns risk failure modes and 2–3 recommended supervisors (with paradigm + surface). Hot path — agents can call dozens of times per task. Uses keyword-rule classification + facet retrieval; no Kimi call in MVP.

### `saica_audit_repo(repo_url: str) → AuditReport`
Same analyzer as the `/assess` page. One call per session, returns coverage grid + ranked gaps + recommendations.

**Tool schemas live in `pipeline/audit/schemas.py`** so /assess and the MCP server share Pydantic types.

---

## 4. /assess page

`site/src/pages/assess.astro`.

**Input:** single text field — `github.com/user/repo` URL. Public repos only for MVP (no OAuth).

**Output (3 sections):**
1. **Coverage heatmap** — same visual as `/tool-coverage` but populated from the user's detected stack (rows = detected supervision tools, columns = 11 FMs, cells = tier 0–3).
2. **Ranked gap list** — for each missing failure mode, severity + 2–3 tailored recommendations (matched to detected language / CI / agent / surface).
3. **Markdown download** — full report as a single `.md` file the user can paste into their team's docs.

Backend: new `POST /assess` endpoint on the existing `pipeline/ask/server.py` FastAPI service. Returns `AuditReport` JSON.

---

## 5. Audit analyzer — `pipeline/audit/`

**Input:** `repo_url`.

**Pipeline:**
1. **Fetch** — shallow `git clone --depth=1` (or GitHub API) into a temp dir.
2. **Detect stack** — language(s), runtime, CI provider, agent(s).
3. **Detect supervision tools** from these signals:
   - Agent configs: `.claude/`, `CLAUDE.md`, `.cursor/`, `.cursorrules`, `.windsurfrules`, `.zed/`, `.aider/` → agent.
   - CI: `.github/workflows/*.yml` (parse for action references: `semgrep/semgrep-action`, `snyk/actions/*`, `dependabot`, `renovatebot`, `pre-commit/action`, `qodo-ai/pr-agent`, `ai-code-review/*`, etc.).
   - Dep files: `pyproject.toml`, `requirements*.txt`, `Pipfile`, `setup.py` → Python supervision libs (`guardrails-ai`, `llm-guard`, `nemo-guardrails`, `instructor`, `pydantic-ai`, `langgraph`, `crewai`, `autogen`, `deepeval`, `ragas`, `garak`, `pyrit`, `promptfoo`).
   - JS dep files: `package.json` → `@instructor-ai/*`, `langfuse`, `helicone`, `litellm`, etc.
   - `.pre-commit-config.yaml` → semgrep/black/etc., and `pre-commit` itself.
   - Eval configs: `promptfooconfig.yaml`, `judgeval/`, `deepeval.yaml`, etc.
   - `Dependabot` config: `.github/dependabot.yml`.
   - `Renovate` config: `renovate.json` or `.github/renovate.json`.
4. **Resolve to KG ids** — each detection → SAICA-KG `tool_id`. Tools not in the KG → flagged separately.
5. **Build coverage grid** — for each (FM, paradigm) cell, sum tiers from contributing tools.
6. **Compute gaps** — FMs with no contributing tool, or paradigms missing for important FMs.
7. **Generate recommendations** — for each gap, query KG for tools that (a) cover the FM, (b) have at least one integration_surface compatible with the detected stack (e.g., `library` if Python, `ci_app` if GitHub Actions). Rank by `tier_sum, stars, breadth`.
8. **Render** — return `AuditReport` Pydantic; `.to_markdown()` for download, JSON for site/MCP.

**No fork, no PR, no OAuth, no write access.** Audit is read-only and stateless.

---

## 6. Hosting

DigitalOcean droplet, single $6–$12 instance. Both `/ask` + MCP HTTP server behind a reverse proxy (Caddy or nginx). Astro static site — Cloudflare Pages or DO App Platform. Cost cap: stay under $20/mo total.

**MVP deploy** is local-first; we'll provision DO once /assess + MCP are working end-to-end on localhost.

---

## 7. Execution plan

### Phase 0 — foundation (today, sequential, ~1 hour)
- [x] Git repo confirmed; survey complete
- [ ] This ROADMAP
- [ ] `pipeline/audit/schemas.py` — shared Pydantic types
- [ ] Empty package skeletons: `pipeline/audit/`, `pipeline/mcp/`

### Phase 1 — parallel build (3 agents, ~2–3 hours wall-clock)
- **Agent A — Audit analyzer** (`pipeline/audit/`)
  - detectors, KG lookup, coverage grid, gap analysis, Markdown renderer
  - end-to-end CLI: `python -m pipeline.audit.cli https://github.com/...`
- **Agent B — MCP server** (`pipeline/mcp/`)
  - `FastMCP` instance with three tools wired to schemas
  - stdio transport works with Claude Code; `python -m pipeline.mcp.server` starts it
  - `mcp_config.example.json` ready to paste into a Claude Code config
- **Agent C — /assess page** (`site/src/pages/assess.astro`)
  - input form + result rendering (heatmap reuse + gap list + Markdown download)
  - new `POST /assess` route on `pipeline/ask/server.py` returning `AuditReport` JSON
  - graceful failure when backend is down (mirrors /ask pattern)

### Phase 2 — integration & smoke test (sequential, ~1 hour)
- Wire MCP `saica_audit_repo` to `pipeline/audit/`
- Wire `/assess` POST endpoint
- End-to-end test on this repo + 2 known repos (e.g. `langfuse/langfuse`, `BerriAI/litellm`)
- Document Claude Code wiring (one paragraph in README)

### Phase 3 — deploy (later, deferred)
- Provision DO droplet, install Python + Caddy
- Bind /ask + /assess + MCP-HTTP to the same FastAPI app
- Astro build → Cloudflare Pages
- DNS + HTTPS

---

## 8. Non-goals for this iteration

Keep scope tight. Out of scope right now:
- OAuth / private GitHub repos (public-URL input only)
- Live agent-loop evaluation (offline correctness only)
- Recipes population (separate workstream — needed eventually but not blocking v0.2)
- Telemetry / analytics for `/assess` usage (add after deploy)
- Auto-update of integration_surfaces from new tool entries (run bulk-annotator manually for now)
- Per-PR / commit-level analysis (whole-repo snapshot only)
- Tools NOT in the KG: flag as "detected but unknown; consider opening a PR to add" — don't try to auto-classify them

---

## 9. Open questions / risks

- **Detection precision.** A false-positive ("you're using guardrails-ai" when they're not) erodes trust fast. Detection must err toward under-claiming with confidence scores surfaced in the report.
- **Rate limits.** GitHub anonymous API = 60 req/hr. Need caching + maybe a token in env for the `/assess` server to avoid throttling under any load.
- **Repo size.** Mono-repos with 10k+ files — shallow clone + selective file fetch only.
- **MCP wiring docs.** Claude Code's MCP config is straightforward but practitioners will hit it cold; need a 5-line copy-pasteable snippet.
- **Stale tool detection rules.** As new supervision tools land in the KG, their detection rules need to land in `pipeline/audit/detectors.py` — ideally generated from the YAML's `repository_url` + a `package_name` field. v0.2 ships hand-written rules; auto-generation is a v0.3 follow-up.

---

## 10. Decision log

- **2026-04-24:** Chose practitioner-utility over paper-novelty as the v0.2 north star.
- **2026-04-24:** MCP brought back from "cut" to "priority #1" — it's the only path to live, in-loop value for agents.
- **2026-04-24:** Audit analyzer is shared between `/assess` (web) and `saica_audit_repo` (MCP) — one component, two surfaces.
- **2026-04-24:** Public-repo URL input for MVP; OAuth deferred.
- **2026-04-24:** Claude Code is the first-class MCP target; Cursor / Replit follow.
- **2026-05-01:** Scope clarification triggered by external Replit-Agent
  feedback ("SAICA isn't a library I'd call at runtime — it's a curated
  dataset best consumed as injected context"). The critique was largely
  correct. Result: (a) demoted `/ask` from headline interface to "browse
  the corpus chat-style"; (b) added `validator/generate_skills.py` →
  `SKILLS.md` as the recommended integration shape; (c) sharpened README +
  MCP README to make the cadence (session-start setup, not per-action
  query) unmissable. Audit + recommend remain the killer one-shot tools.
- **2026-05-01:** v0.3 SAICA Index added (`pipeline/saica_index/` →
  `/leaderboard` page, weekly cron). Two boards: `kg_tools` (auto-derived
  — every supervisor in the KG, audited against itself: "do supervisors
  supervise themselves?") and `popular_oss` (curated list of repos AI
  agents touch a lot — FastAPI, langchain, Astro, etc.). Score formula
  is the *single source of truth* in `pipeline/saica_index/score.py`:
  per-FM coverage tier × paradigm-diversity bonus, weighted by FM
  priority, mapped to A–F. Thresholds biased harsh on purpose so an A
  feels earned (langchain/fastapi land at D today). The Index drives
  external attention without committing us to a hosted backend — the
  page is static, regenerated weekly by GitHub Actions, JSON committed
  into `site/public/`. Hosting + GitHub PR-bot are the next-bigger
  bets, deferred to v0.4.
