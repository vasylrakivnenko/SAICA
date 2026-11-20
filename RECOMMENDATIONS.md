# SAICA-KG — Supervision recommendations

> Read once at project setup. Don't poll this file per-task.
> For per-action agent guidance, see `SKILLS.md` (drop into your
> `.claude/skills/`, `.cursor/rules/`, or equivalent skills directory).

Pre-computed from the KG. Regenerate with `python -m validator.generate_recommendations`.
Last regenerated: 2026-11-20 from KG version 2026.11.

> 🔥 marks repos currently on github.com/trending. Trending tools win ties
> against non-trending peers with up to ~+30% more raw stars (boost = 1.43×; see
> `pipeline/shared/trending.py`).

This regeneration saw **39** trending repositories in `data/trending.json`.

---

## Quickstart — pick by which agent you use

If you already use one of these coding agents, install the supervisors below for full 11-failure-mode coverage. None of these are competing coding agents — they all *compose with* the agent you have.

### If you use **Aider**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **Claude Code**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **Cline**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **Codex CLI**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **Continue.dev**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **Cursor**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **Devin**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **Gemini CLI**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **GitHub Copilot**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **OpenHands**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **Replit Agent**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **Sourcegraph Cody**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **SWE-agent**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **v0**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **Windsurf**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

### If you use **Zed Agent**

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

---

## Agnostic baseline (no specific coding agent)

If you don't use one of the listed coding agents — or you're evaluating supervisors without a fixed asker — these are the three tiers without a peer-coding-agent filter. The blocklist still applies.

**Minimum (1 tool — best starter)** — 1 tool covers 3 of 11 failure modes (highest-priority single pick).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |

**Optimal (3 tools — best responsible kit)** — 3 tools cover 8 of 11 failure modes (weighted set cover, capped at 3).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |

**Full / MECE (minimum tools to cover all 11 failure modes)** — 6 tools cover 11 of 11 failure modes (minimum weighted set cover).

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  |

---

## Quickstart — pick by failure mode

Top 3 supervisors per failure mode (agnostic; pick the row whose paradigm and surfaces fit your workflow).

### Fabrication

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [mypy](data/tools/mypy.yml) | detection | post_generation | cli, ci_app, ide_plugin | 18,000 |  | Static type checker for Python. Catches mismatched types before runti… |
| [Pyright](data/tools/pyright.yml) | detection | post_generation | cli, ci_app, ide_plugin | 14,000 |  | Microsoft's fast static type checker for Python. |
| [Context7](data/tools/context7.yml) | prevention | pre_generation | mcp_server, cli | 54,254 |  | Up-to-date, version-pinned library documentation for coding agents —… |

### Obsolescence

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  | Highly configurable multi-platform dependency update bot. |
| [Context Hub](data/tools/context-hub.yml) | prevention | pre_generation | mcp_server, cli | 13,025 |  | Up-to-date, curated API docs for coding agents. |
| [Dependabot](data/tools/dependabot.yml) | detection | post_generation | ci_app | 5,546 |  | Automated dependency-update PRs that flag outdated and vulnerable pac… |

### Dependency blindness

Top 1 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 1,975 |  | Real-time architectural sensor that scores codebase modularity, acycl… |

### Logic error

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  | Extremely fast Python linter and formatter, written in Rust. |
| [ESLint](data/tools/eslint.yml) | detection | post_generation | cli, ci_app, ide_plugin | 25,000 |  | Pluggable JavaScript/TypeScript linter and code-quality enforcer. |
| [Pyright](data/tools/pyright.yml) | detection | post_generation | cli, ci_app, ide_plugin | 14,000 |  | Microsoft's fast static type checker for Python. |

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
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  | Graph-structured state machines for stateful multi-agent orchestratio… |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  | Make websites accessible for AI agents. |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  | Multi-agent conversation framework with programmable group chats. |

### Context pollution

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  | Graph-structured state machines for stateful multi-agent orchestratio… |
| [mlflow](data/tools/mlflow.yml) | detection | post_generation | http_service, library, cli | 25,505 |  | Open-source platform for the machine learning lifecycle — experiments… |
| [mastra](data/tools/mastra.yml) | prevention | pre_generation | library | 23,247 |  | The TypeScript AI agent framework — assistants, RAG, observability; s… |

### Supply chain attack

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [Socket](data/tools/socket.yml) | detection | pre_generation | ci_app, cli, library | — |  | Dependency supply-chain scanner that inspects packages before install. |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  | Highly configurable multi-platform dependency update bot. |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  | Test prompts, agents, and RAGs — red-teaming, pentesting, and vulnera… |

### Cascading failure

Top 1 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 1,177 |  | AI Agent Governance Toolkit — policy enforcement, zero-trust identity… |

### Incomplete execution

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [Ruff](data/tools/ruff.yml) | detection | post_generation | cli, ci_app, ide_plugin | 30,000 |  | Extremely fast Python linter and formatter, written in Rust. |
| [ESLint](data/tools/eslint.yml) | detection | post_generation | cli, ci_app, ide_plugin | 25,000 |  | Pluggable JavaScript/TypeScript linter and code-quality enforcer. |
| [opik](data/tools/opik.yml) | detection | post_generation | http_service, library | 18,988 |  | Debug, evaluate, and monitor LLM applications, RAG systems, and agent… |

### Test manipulation

Top 1 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
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
