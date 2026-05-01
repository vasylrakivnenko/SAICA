# SAICA-KG — Supervision recommendations

Pre-computed from the KG. Regenerate with `python -m validator.generate_recommendations`.
Last regenerated: 2026-04-30 from KG version 2026.04.

> 🔥 marks repos currently on github.com/trending. Trending tools win ties
> against non-trending peers with up to ~+30% more raw stars (boost = 1.43×; see
> `pipeline/shared/trending.py`).

This regeneration saw **39** trending repositories in `data/trending.json`.

---

## Quickstart — pick by which agent you use

If you already use one of these coding agents, install the supervisors below for full 11-failure-mode coverage. None of these are competing coding agents — they all *compose with* the agent you have.

### If you use **Aider**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **Claude Code**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **Cline**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **Codex CLI**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **Continue.dev**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **Cursor**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **Devin**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **Gemini CLI**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **GitHub Copilot**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **OpenHands**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **Replit Agent**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **Sourcegraph Cody**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **SWE-agent**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **v0**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **Windsurf**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

### If you use **Zed Agent**

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [tree-sitter](data/tools/tree-sitter.yml) | prevention | pre_generation | library | 24,948 |  |

Depth pad (additional supervisors for redundancy / observability):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [llm-app](data/tools/pathway-llm-app.yml) | detection | post_generation | library, http_service | 59,931 |  |
| [AutoGen](data/tools/autogen.yml) | prevention | pre_generation | library | 57,354 |  |
| [Flowise](data/tools/flowise.yml) | prevention | pre_generation | web_app, http_service | 52,185 |  |
| [CrewAI](data/tools/crewai.yml) | prevention | pre_generation | library | 49,633 |  |

---

## Agnostic baseline (no specific coding agent)

If you don't use one of the listed coding agents — or you're evaluating supervisors without a fixed asker — this is the unfiltered full-suite view. The blocklist still applies.

Specialists (4 tools cover all 11 failure modes):

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  |
| [Renovate](data/tools/renovate.yml) | detection | post_generation | ci_app, cli | 21,353 |  |
| [Continue](data/tools/continue-dev.yml) | prevention | pre_generation | ide_plugin, library | 32,739 |  |

Depth pad:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending |
| --- | --- | --- | --- | ---: | :---: |
| [Zed Agent](data/tools/zed-agent.yml) | prevention | pre_generation | desktop_app | 79,584 | 🔥 |
| [Codex CLI](data/tools/codex-cli.yml) | correction | post_generation | cli | 77,172 | 🔥 |
| [Gemini CLI](data/tools/gemini-cli.yml) | prevention | pre_generation | cli | 102,183 |  |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  |
| [ragflow](data/tools/ragflow.yml) | detection | post_generation | http_service, library | 78,820 |  |
| [Daytona](data/tools/daytona.yml) | recovery | post_generation | cli, http_service | 72,378 |  |
| [OpenHands](data/tools/openhands.yml) | recovery | post_generation | cli, library | 71,851 |  |

---

## Quickstart — pick by failure mode

Top 3 supervisors per failure mode (agnostic; pick the row whose paradigm and surfaces fit your workflow).

### Fabrication

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [v0](data/tools/v0.yml) | prevention | pre_generation | web_app | — |  | Vercel's generative-UI coding agent for React and Next.js web interfa… |
| [Sourcegraph Cody](data/tools/sourcegraph-cody.yml) | prevention | pre_generation | ide_plugin, cli | — |  | Codebase-indexed coding assistant that grounds generation in reposito… |
| [Gemini CLI](data/tools/gemini-cli.yml) | prevention | pre_generation | cli | 102,183 |  | Google's official terminal coding agent built on Gemini with MCP and… |

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
| [Sourcegraph Cody](data/tools/sourcegraph-cody.yml) | prevention | pre_generation | ide_plugin, cli | — |  | Codebase-indexed coding assistant that grounds generation in reposito… |

### Logic error

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [LangSmith](data/tools/langsmith.yml) | detection | post_generation | http_service, library | — |  | Hosted LLM observability, tracing, and evaluation platform. |
| [Smolagents](data/tools/smolagents.yml) | detection | post_generation | library | 26,835 |  | Minimalist code-agent library that expresses actions as executed Pyth… |
| [Langfuse](data/tools/langfuse.yml) | detection | post_generation | http_service, library | 25,839 |  | Open-source LLM engineering platform for tracing, evals, and prompt m… |

### Security vulnerability

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [Snyk](data/tools/snyk.yml) | detection | post_generation | cli, ci_app | 5,506 |  | Vulnerability scanning for code, dependencies, containers, and IaC. |
| [DeepTeam](data/tools/confident-ai-deepteam.yml) | detection | post_generation | library, cli | 1,566 |  | Open-source LLM red-teaming framework from Confident AI with 40+ atta… |
| [browser-use](data/tools/browser-use.yml) | prevention | post_generation | library, web_app | 89,651 |  | Make websites accessible for AI agents. |

### Scope creep

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  | Graph-structured state machines for stateful multi-agent orchestratio… |
| [LangSmith](data/tools/langsmith.yml) | detection | post_generation | http_service, library | — |  | Hosted LLM observability, tracing, and evaluation platform. |
| [Zed Agent](data/tools/zed-agent.yml) | prevention | pre_generation | desktop_app | 79,584 | 🔥 | Built-in agentic coding mode inside the Zed editor with rules.md and… |

### Context pollution

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 30,108 |  | Graph-structured state machines for stateful multi-agent orchestratio… |
| [Zed Agent](data/tools/zed-agent.yml) | prevention | pre_generation | desktop_app | 79,584 | 🔥 | Built-in agentic coding mode inside the Zed editor with rules.md and… |
| [Gemini CLI](data/tools/gemini-cli.yml) | prevention | pre_generation | cli | 102,183 |  | Google's official terminal coding agent built on Gemini with MCP and… |

### Supply chain attack

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [DeepTeam](data/tools/confident-ai-deepteam.yml) | detection | post_generation | library, cli | 1,566 |  | Open-source LLM red-teaming framework from Confident AI with 40+ atta… |
| [Socket](data/tools/socket.yml) | detection | pre_generation | ci_app, cli, library | — |  | Dependency supply-chain scanner that inspects packages before install. |
| [Cline](data/tools/cline.yml) | prevention | pre_generation | ide_plugin | 60,646 |  | VS Code extension coding agent with per-action approval and auto-appr… |

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
| [opik](data/tools/opik.yml) | detection | post_generation | http_service, library | 18,988 |  | Debug, evaluate, and monitor LLM applications, RAG systems, and agent… |
| [voltagent](data/tools/voltagent.yml) | detection | post_generation | library | 8,416 |  | TypeScript-native AI agent engineering platform with built-in observa… |
| [coze-loop](data/tools/coze-loop.yml) | detection | post_generation | web_app, http_service | 5,427 |  | Full-lifecycle AI agent management platform with debugging, evaluatio… |

### Test manipulation

Top 3 supervisors:

| Tool | Paradigm | Phase | Surfaces | Stars | Trending | Why |
| --- | --- | --- | --- | ---: | :---: | --- |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 20,465 |  | Test prompts, agents, and RAGs — red-teaming, pentesting, and vulnera… |
| [giskard-oss](data/tools/giskard.yml) | detection | post_generation | library, cli, ci_app | 5,295 |  | Open-source evaluation and testing library for LLM agents and ML mode… |
| [judgeval](data/tools/judgeval.yml) | detection | post_generation | library, cli | 1,024 |  | The open source post-building layer for agents: evals, traces, and re… |

---

## Methodology

- Coverage = the tool's `addresses_failure_modes` declares the FM.
- Greedy set cover prefers tools that cover the most still-uncovered FMs; tiebreak by trending-boosted star count, then breadth.
- Coding-agent peers are filtered out per asker (the user has a coding agent already; we recommend supervisors, not peers).
- The blocklist (currently: `comfyui`) excludes tools whose role is too ambiguous.

This file is regenerated from `data/tools/*.yml` by `validator/generate_recommendations.py`.
