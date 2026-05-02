# SAICA-KG — Supervision recommendations

> Read once at project setup. Don't poll this file per-task.
> For per-action agent guidance, see `SKILLS.md` (drop into your
> `.claude/skills/`, `.cursor/rules/`, or equivalent skills directory).

Pre-computed from the KG. Regenerate with `python -m validator.generate_recommendations`.
Last regenerated: 2026-05-01 from KG version 2026.05.

> 🔥 marks repos currently on github.com/trending. Trending tools win ties
> against non-trending peers with up to ~+30% more raw stars (boost = 1.43×; see
> `pipeline/shared/trending.py`).

This regeneration saw **39** trending repositories in `data/trending.json`.

---

## Quickstart — pick by which agent you use

If you already use one of these coding agents, install the supervisors below for full 11-failure-mode coverage. None of these are competing coding agents — they all *compose with* the agent you have.

### If you use **Aider**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **Claude Code**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **Cline**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **Codex CLI**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **Continue.dev**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **Cursor**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **Devin**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **Gemini CLI**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **GitHub Copilot**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **OpenHands**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **Replit Agent**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **Sourcegraph Cody**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **SWE-agent**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **v0**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **Windsurf**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

### If you use **Zed Agent**

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

---

## Agnostic baseline (no specific coding agent)

If you don't use one of the listed coding agents — or you're evaluating supervisors without a fixed asker — these are the three tiers without a peer-coding-agent filter. The blocklist still applies.

**Minimum (1 tool — best starter)** — 1 tool covers 5 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 5 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

---

## Quickstart — pick by failure mode

Top 3 supervisors per failure mode (agnostic; pick the row whose paradigm and surfaces fit your workflow).

### Fabrication

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [mypy](data/tools/mypy.yml) | detection | post_generation | cli, ci_app, ide_plugin | 18,000 |  | Static type checker for Python. Catches mismatched types before runti… |
| [Pyright](data/tools/pyright.yml) | detection | post_generation | cli, ci_app, ide_plugin | 14,000 |  | Microsoft's fast static type checker for Python. |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  | Open-source RAG engine based on deep document understanding. |

### Obsolescence

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  | Ready-to-run cloud templates for RAG, AI pipelines, and enterprise se… |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  | Highly configurable multi-platform dependency update bot. |
| [Context Hub](data/tools/context-hub.yml) | prevention | pre_generation | mcp_server, cli | 13,025 |  | Up-to-date, curated API docs for coding agents. |

### Dependency blindness

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  | Incremental parser toolkit that powers structural code analysis and s… |
| [Semgrep](data/tools/semgrep.yml) | detection | post_generation | cli, ci_app, library | 14,901 |  | Fast, rule-based static analysis with a pattern syntax that mirrors s… |
| [pre-commit](data/tools/pre-commit.yml) | prevention | post_generation | cli, ci_app | — |  | Multi-language framework that runs configurable hooks before commits… |

### Logic error

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  | Extremely fast Python linter and formatter, written in Rust. |
| [ESLint](data/tools/eslint.yml) | detection | post_generation | cli, ci_app, ide_plugin | 25,000 |  | Pluggable JavaScript/TypeScript linter and code-quality enforcer. |
| [mypy](data/tools/mypy.yml) | detection | post_generation | cli, ci_app, ide_plugin | 18,000 |  | Static type checker for Python. Catches mismatched types before runti… |

### Security vulnerability

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [ESLint](data/tools/eslint.yml) | detection | post_generation | cli, ci_app, ide_plugin | 25,000 |  | Pluggable JavaScript/TypeScript linter and code-quality enforcer. |
| [Bandit](data/tools/bandit.yml) | detection | post_generation | cli, ci_app | 6,000 |  | Security linter for Python. Catches common code-level vulnerabilities. |
| [Snyk](data/tools/snyk.yml) | detection | post_generation | cli, ci_app | 5,506 |  | Vulnerability scanning for code, dependencies, containers, and IaC. |

### Scope creep

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [Prettier](data/tools/prettier.yml) | prevention | post_generation | cli, ci_app, ide_plugin | 50,000 |  | Opinionated code formatter for JS/TS/CSS/HTML. Ends style debates. |
| [Black](data/tools/black.yml) | prevention | post_generation | cli, ci_app, ide_plugin | 39,000 |  | Opinionated Python code formatter. Removes style argument from PR rev… |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  | Graph-structured state machines for stateful multi-agent orchestratio… |

### Context pollution

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  | Graph-structured state machines for stateful multi-agent orchestratio… |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  | Open-source RAG engine based on deep document understanding. |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  | Ready-to-run cloud templates for RAG, AI pipelines, and enterprise se… |

### Supply chain attack

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [DeepTeam](data/tools/confident-ai-deepteam.yml) | detection | post_generation | library, cli | 1,566 |  | Open-source LLM red-teaming framework from Confident AI with 40+ atta… |
| [Socket](data/tools/socket.yml) | detection | pre_generation | ci_app, cli, library | — |  | Dependency supply-chain scanner that inspects packages before install. |
| [activepieces](data/tools/activepieces.yml) | prevention | pre_generation | web_app, http_service | 21,825 |  | AI agents, MCPs, and AI workflow automation — open-source Zapier alte… |

### Cascading failure

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [manifest](data/tools/manifest.yml) | prevention | in_generation | library | 5,555 |  | Smart model routing for personal AI agents. |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  | Full-lifecycle AI agent management platform with debugging, evaluatio… |
| [bifrost](data/tools/bifrost.yml) | prevention | in_generation | proxy_gateway, http_service | 4,209 |  | Fastest enterprise AI gateway with adaptive load balancing, failover,… |

### Incomplete execution

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [pytest](data/tools/pytest.yml) | detection | post_generation | cli, ci_app, ide_plugin | 12,000 |  | Python test framework — discipline gate for "done means tests pass." |
| [opik](data/tools/opik.yml) | detection | post_generation | http_service, library | 18,988 |  | Debug, evaluate, and monitor LLM applications, RAG systems, and agent… |
| [voltagent](data/tools/voltagent.yml) | detection | post_generation | library | 8,416 |  | TypeScript-native AI agent engineering platform with built-in observa… |

### Test manipulation

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [pytest](data/tools/pytest.yml) | detection | post_generation | cli, ci_app, ide_plugin | 12,000 |  | Python test framework — discipline gate for "done means tests pass." |
| [Coverage.py](data/tools/coverage-py.yml) | detection | post_generation | cli, ci_app, library | 3,000 |  | Code coverage measurement for Python. Detects test-manipulation by su… |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  | Test prompts, agents, and RAGs — red-teaming, pentesting, and vulnera… |

---

## Methodology

Selection is by **likelihood × impact × reliability**. Per-FM likelihood and impact live in `data/failure_mode_priorities.yml` (hybrid: KG tool-coverage prior + editorial calibration against Shah 2026 / DAPLab evidence). Reliability is a bounded combiner of log-stars, github-trending bump, citation count, and maturity.

Three tiers per asker:

- **Minimum (1 tool)** — single tool maximising Σ priority(fm) over its addressed FMs × its reliability.
- **Optimal (3 tools)** — greedy weighted set cover capped at 3.
- **Full / MECE** — greedy weighted set cover until every FM is covered (no pad). Typically 4-5 tools.

Coding-agent peers are filtered out per asker (the user has a coding agent already; we recommend supervisors, not peers).
The blocklist (currently: `comfyui`) excludes tools whose role is too ambiguous.

Priority order (likelihood × impact, descending):

| Failure mode | priority |
| --- | ---: |
| `scope_creep` | 1.70 |
| `fabrication` | 1.40 |
| `security_vulnerability` | 1.35 |
| `supply_chain_attack` | 0.60 |
| `logic_error` | 0.55 |
| `cascading_failure` | 0.50 |
| `context_pollution` | 0.45 |
| `obsolescence` | 0.35 |
| `test_manipulation` | 0.30 |
| `dependency_blindness` | 0.20 |
| `incomplete_execution` | 0.15 |

This file is regenerated from `data/tools/*.yml` and `data/failure_mode_priorities.yml` by `validator/generate_recommendations.py`.
