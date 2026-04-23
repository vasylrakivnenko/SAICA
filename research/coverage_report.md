# SAICA-KG Coverage & Gap Report

_Generated: 2026-04-23T10:13:35+00:00 (report date: 2026-04-22)_

This report highlights where the SAICA-KG is thin and what to add next. It is produced by `validator/coverage_report.py` and never blocks CI; the companion script `validator/cli.py` handles hard invariants.

## 1. Summary

| Node type | Count |
| --- | --- |
| Tools | 111 |
| FailureModes | 11 |
| Papers | 25 |
| Taxonomies | 6 |
| Crosswalks (bulk) | 6 |
| Facet cells (filled / 36) | 16 / 36 |
| FailureModes with < 3 mitigators | 0 |
| Tools older than 180 days | 4 |

## 2. Facet-cell occupancy (ControlParadigm x TemporalPhase x AutonomyLevel)

Total cells: 4 x 3 x 3 = 36. Empty cells: **20**.

| control_paradigm | temporal_phase | autonomy_level | # tools | tool names |
| --- | --- | --- | --- | --- |
| prevention | pre_generation | fully_autonomous | 8 | AutoGen, Context Hub, CrewAI, LangGraph, agno, letta, safe-rlhf, tree-sitter |
| prevention | pre_generation | graduated_hitl | 14 | Claude Code, Cline, ComfyUI, Continue, Cordum, Cursor, Flowise, Gemini CLI, Sourcegraph Cody, Windsurf, Zed Agent, activepieces, mastra, v0 |
| prevention | pre_generation | full_hitl | 0 | **WARN EMPTY** |
| prevention | in_generation | fully_autonomous | 10 | Govcraft/rust-docs-mcp-server, Guidance, Outlines, PipelineLock, Superagent, bifrost, litellm, llm-guard, manifest, nono |
| prevention | in_generation | graduated_hitl | 1 | CopilotKit |
| prevention | in_generation | full_hitl | 1 | agent-governance-toolkit |
| prevention | post_generation | fully_autonomous | 7 | Agentic Guardrails, Reins, genai-toolbox, mcp, mcp-playwright, mcp-server-browserbase, playwright-mcp |
| prevention | post_generation | graduated_hitl | 3 | browser-use, magic-mcp, skyvern |
| prevention | post_generation | full_hitl | 0 | **WARN EMPTY** |
| detection | pre_generation | fully_autonomous | 3 | Rebuff, Socket, last_layer |
| detection | pre_generation | graduated_hitl | 1 | GitHub Copilot |
| detection | pre_generation | full_hitl | 1 | AI-Infra-Guard |
| detection | in_generation | fully_autonomous | 0 | **WARN EMPTY** |
| detection | in_generation | graduated_hitl | 0 | **WARN EMPTY** |
| detection | in_generation | full_hitl | 0 | **WARN EMPTY** |
| detection | post_generation | fully_autonomous | 14 | Arize Phoenix, Braintrust, DeepTeam, Guardrails AI, Helicone, Instructor, LangKit, LangSmith, Langfuse, NeMo Guardrails, PydanticAI, Semgrep, Smolagents, Snyk |
| detection | post_generation | graduated_hitl | 10 | Dependabot, Renovate, TruLens, agenta, llm-app, pezzo, promptflow, ragflow, uqlm, voltagent |
| detection | post_generation | full_hitl | 29 | AI-Red-Teaming-Playground-Labs, AutoRAG, DeepEval, FuzzyAI, PyRIT, agentic-security, beelzebub, coze-loop, deepteam, docetl, evals, garak, giskard-oss, helm, judgeval, lighteval, lm-evaluation-harness, lmms-eval, lmnr, logfire, mlflow, openlit, opik, phoenix, pr-agent, promptbench, promptfoo, promptmap, ragas |
| correction | pre_generation | fully_autonomous | 0 | **WARN EMPTY** |
| correction | pre_generation | graduated_hitl | 0 | **WARN EMPTY** |
| correction | pre_generation | full_hitl | 0 | **WARN EMPTY** |
| correction | in_generation | fully_autonomous | 0 | **WARN EMPTY** |
| correction | in_generation | graduated_hitl | 0 | **WARN EMPTY** |
| correction | in_generation | full_hitl | 0 | **WARN EMPTY** |
| correction | post_generation | fully_autonomous | 1 | Codex CLI |
| correction | post_generation | graduated_hitl | 1 | Aider |
| correction | post_generation | full_hitl | 0 | **WARN EMPTY** |
| recovery | pre_generation | fully_autonomous | 0 | **WARN EMPTY** |
| recovery | pre_generation | graduated_hitl | 0 | **WARN EMPTY** |
| recovery | pre_generation | full_hitl | 0 | **WARN EMPTY** |
| recovery | in_generation | fully_autonomous | 0 | **WARN EMPTY** |
| recovery | in_generation | graduated_hitl | 0 | **WARN EMPTY** |
| recovery | in_generation | full_hitl | 0 | **WARN EMPTY** |
| recovery | post_generation | fully_autonomous | 7 | Daytona, Devin, E2B, Modal, OpenHands, Replit Agent, SWE-agent |
| recovery | post_generation | graduated_hitl | 0 | **WARN EMPTY** |
| recovery | post_generation | full_hitl | 0 | **WARN EMPTY** |

### Empty cells (prescriptive gaps)

- `prevention` x `pre_generation` x `full_hitl`
- `prevention` x `post_generation` x `full_hitl`
- `detection` x `in_generation` x `fully_autonomous`
- `detection` x `in_generation` x `graduated_hitl`
- `detection` x `in_generation` x `full_hitl`
- `correction` x `pre_generation` x `fully_autonomous`
- `correction` x `pre_generation` x `graduated_hitl`
- `correction` x `pre_generation` x `full_hitl`
- `correction` x `in_generation` x `fully_autonomous`
- `correction` x `in_generation` x `graduated_hitl`
- `correction` x `in_generation` x `full_hitl`
- `correction` x `post_generation` x `full_hitl`
- `recovery` x `pre_generation` x `fully_autonomous`
- `recovery` x `pre_generation` x `graduated_hitl`
- `recovery` x `pre_generation` x `full_hitl`
- `recovery` x `in_generation` x `fully_autonomous`
- `recovery` x `in_generation` x `graduated_hitl`
- `recovery` x `in_generation` x `full_hitl`
- `recovery` x `post_generation` x `graduated_hitl`
- `recovery` x `post_generation` x `full_hitl`

## 3. FailureMode coverage

| failure_mode | # mitigators | flag | # external crosswalks | mitigating tools |
| --- | --- | --- | --- | --- |
| fabrication | 55 |  | 11 | AI-Red-Teaming-Playground-Labs, Agentic Guardrails, Arize Phoenix, AutoRAG, Context Hub, Continue, Cursor, DeepEval, DeepTeam, FuzzyAI, Gemini CLI, GitHub Copilot, Guardrails AI, Guidance, Instructor, NeMo Guardrails, Outlines, PyRIT, PydanticAI, Smolagents, Sourcegraph Cody, TruLens, Windsurf, agenta, agentic-security, coze-loop, deepteam, docetl, evals, garak, giskard-oss, helm, judgeval, lighteval, llm-app, llm-guard, lm-evaluation-harness, lmms-eval, lmnr, logfire, magic-mcp, mlflow, openlit, opik, pezzo, phoenix, pr-agent, promptbench, promptflow, promptfoo, promptmap, ragas, ragflow, uqlm, v0 |
| obsolescence | 7 |  | 8 | Context Hub, Dependabot, Govcraft/rust-docs-mcp-server, Renovate, Sourcegraph Cody, llm-app, magic-mcp |
| dependency_blindness | 4 |  | 2 | Continue, Semgrep, Sourcegraph Cody, tree-sitter |
| logic_error | 41 |  | 26 | Aider, Arize Phoenix, Braintrust, Codex CLI, Daytona, DeepEval, Devin, E2B, Guardrails AI, Guidance, Helicone, Instructor, LangSmith, Langfuse, Modal, OpenHands, Outlines, PydanticAI, Replit Agent, SWE-agent, Smolagents, agenta, docetl, evals, giskard-oss, helm, judgeval, lighteval, lm-evaluation-harness, lmms-eval, lmnr, logfire, mlflow, opik, phoenix, pr-agent, promptbench, promptflow, promptfoo, ragas, uqlm |
| security_vulnerability | 43 |  | 18 | AI-Infra-Guard, AI-Red-Teaming-Playground-Labs, Agentic Guardrails, Daytona, DeepTeam, Dependabot, E2B, FuzzyAI, Guardrails AI, LangKit, Modal, NeMo Guardrails, OpenHands, PipelineLock, PyRIT, Rebuff, Semgrep, Snyk, Superagent, agent-governance-toolkit, agentic-security, beelzebub, bifrost, browser-use, deepteam, garak, genai-toolbox, giskard-oss, helm, last_layer, litellm, llm-guard, mcp, mcp-playwright, mcp-server-browserbase, nono, playwright-mcp, pr-agent, promptbench, promptfoo, promptmap, safe-rlhf, skyvern |
| scope_creep | 69 |  | 17 | AI-Infra-Guard, AI-Red-Teaming-Playground-Labs, Aider, AutoGen, Braintrust, Claude Code, Cline, Codex CLI, ComfyUI, CopilotKit, Cordum, CrewAI, Cursor, Devin, Flowise, Gemini CLI, GitHub Copilot, Guardrails AI, LangGraph, LangSmith, Langfuse, NeMo Guardrails, OpenHands, PyRIT, PydanticAI, Reins, Replit Agent, Windsurf, Zed Agent, activepieces, agent-governance-toolkit, agenta, agentic-security, agno, bifrost, browser-use, coze-loop, deepteam, evals, garak, genai-toolbox, giskard-oss, helm, judgeval, letta, litellm, llm-guard, lmnr, logfire, magic-mcp, manifest, mastra, mcp, mcp-playwright, mcp-server-browserbase, mlflow, nono, openlit, opik, pezzo, phoenix, playwright-mcp, promptflow, promptfoo, promptmap, safe-rlhf, skyvern, v0, voltagent |
| context_pollution | 36 |  | 20 | Aider, Arize Phoenix, AutoGen, AutoRAG, Braintrust, Claude Code, Cline, CopilotKit, CrewAI, Cursor, Flowise, Gemini CLI, Helicone, LangGraph, LangSmith, Langfuse, NeMo Guardrails, TruLens, Windsurf, Zed Agent, activepieces, agno, coze-loop, letta, llm-app, llm-guard, logfire, manifest, mastra, openlit, pezzo, phoenix, ragas, ragflow, safe-rlhf, voltagent |
| supply_chain_attack | 17 |  | 8 | AI-Infra-Guard, Claude Code, Cline, Daytona, DeepTeam, Dependabot, E2B, Modal, OpenHands, PipelineLock, Renovate, Snyk, Socket, activepieces, agent-governance-toolkit, beelzebub, bifrost |

## 4. Taxonomy crosswalk completeness

| taxonomy | # categories | # SAICA modes mapped | # categories covered | # missing | missing category ids |
| --- | --- | --- | --- | --- | --- |
| daplab-9-patterns | 9 | 9 | 9 | 0 | _(all covered)_ |
| mast | 14 | 8 | 10 | 4 | MAST-FM-03, MAST-FM-05, MAST-FM-06, MAST-FM-12 |
| microsoft-airt-2025 | 18 | 6 | 12 | 6 | MS-NS-05, MS-NF-01, MS-NF-02, MS-NF-03, MS-EF-01, MS-EF-04 |
| owasp-agentic-top-10-2026 | 10 | 6 | 9 | 1 | ASI09 |
| shah-2026-agentic-faults | 30 | 9 | 21 | 9 | SHAH-DIM-01, SHAH-DIM-02, SHAH-DIM-03, SHAH-DIM-04, SHAH-DIM-05, SHAH-MAJ-06, SHAH-MAJ-07, SHAH-MAJ-13, ... (+1 more) |
| swiss-cheese-model | 40 | 5 | 5 | 35 | SC-QA-06, SC-QA-07, SC-QA-08, SC-QA-09, SC-QA-10, SC-QA-11, SC-QA-12, SC-QA-13, ... (+27 more) |

## 5. Staleness table

Tools sorted by `last_updated` ascending. Flag = age > 180 days vs 2026-04-22, or `maturity_status: at_risk`.

| tool | last_updated | age_days | maturity_status | flags |
| --- | --- | --- | --- | --- |
| agentic-guardrails | _(none)_ | _n/a_ | experimental |  |
| last-layer | 2024-07-26 | 635 | experimental | STALE |
| rebuff | 2024-08-07 | 623 | experimental | STALE |
| langkit | 2024-11-22 | 516 | experimental | STALE |
| browser-mcp | 2025-04-24 | 363 | stable | STALE |
| rust-docs-mcp-server | 2025-11-24 | 149 | experimental |  |
| safe-rlhf | 2025-11-24 | 149 | experimental |  |
| promptmap | 2025-12-01 | 142 | experimental |  |
| mcp-playwright | 2025-12-13 | 130 | stable |  |
| llm-guard | 2025-12-15 | 128 | experimental |  |
| pathway-llm-app | 2026-01-07 | 105 | stable |  |
| guidance | 2026-01-20 | 92 | stable |  |
| agentic-security | 2026-02-03 | 78 | experimental |  |
| fuzzyai | 2026-02-06 | 75 | experimental |  |
| nemo-guardrails | 2026-02-10 | 71 | stable |  |
| ai-red-teaming-playground-labs | 2026-02-13 | 68 | experimental |  |
| magic-mcp | 2026-02-17 | 64 | experimental |  |
| promptbench | 2026-02-20 | 61 | experimental |  |
| ragas | 2026-02-24 | 57 | stable |  |
| outlines | 2026-03-01 | 52 | stable |  |
| pydantic-ai | 2026-03-15 | 38 | stable |  |
| swe-agent | 2026-03-15 | 38 | stable |  |
| guardrails-ai | 2026-03-20 | 33 | stable |  |
| instructor | 2026-03-25 | 28 | stable |  |
| smolagents | 2026-03-25 | 28 | stable |  |
| docetl | 2026-03-27 | 26 | experimental |  |
| aider | 2026-03-28 | 25 | stable |  |
| autogen | 2026-03-30 | 23 | stable |  |
| mcp-server-browserbase | 2026-03-31 | 22 | experimental |  |
| pezzo | 2026-03-31 | 22 | experimental |  |
| confident-ai-deepteam | 2026-04-01 | 21 | stable |  |
| devin | 2026-04-01 | 21 | stable |  |
| e2b | 2026-04-01 | 21 | stable |  |
| v0 | 2026-04-01 | 21 | stable |  |
| openhands | 2026-04-02 | 20 | stable |  |
| arize-phoenix | 2026-04-05 | 17 | stable |  |
| braintrust | 2026-04-05 | 17 | stable |  |
| cline | 2026-04-05 | 17 | stable |  |
| continue-dev | 2026-04-05 | 17 | stable |  |
| crewai | 2026-04-05 | 17 | stable |  |
| helicone | 2026-04-05 | 17 | stable |  |
| windsurf | 2026-04-05 | 17 | stable |  |
| daytona | 2026-04-08 | 14 | stable |  |
| socket | 2026-04-08 | 14 | stable |  |
| cursor | 2026-04-10 | 12 | stable |  |
| langfuse | 2026-04-10 | 12 | stable |  |
| langgraph | 2026-04-10 | 12 | stable |  |
| langsmith | 2026-04-10 | 12 | stable |  |
| replit-agent | 2026-04-10 | 12 | stable |  |
| sourcegraph-cody | 2026-04-10 | 12 | stable |  |
| tree-sitter | 2026-04-10 | 12 | stable |  |
| zed-agent | 2026-04-10 | 12 | stable |  |
| superagent | 2026-04-11 | 11 | experimental |  |
| letta | 2026-04-12 | 10 | stable |  |
| modal | 2026-04-12 | 10 | stable |  |
| snyk | 2026-04-12 | 10 | stable |  |
| openai-evals | 2026-04-14 | 8 | stable |  |
| codex-cli | 2026-04-15 | 7 | stable |  |
| context-hub | 2026-04-15 | 7 | experimental |  |
| dependabot | 2026-04-15 | 7 | stable |  |
| gemini-cli | 2026-04-15 | 7 | stable |  |
| github-copilot | 2026-04-15 | 7 | stable |  |
| uqlm | 2026-04-16 | 6 | experimental |  |
| lighteval | 2026-04-17 | 5 | experimental |  |
| semgrep | 2026-04-17 | 5 | stable |  |
| renovate | 2026-04-18 | 4 | stable |  |
| openlit | 2026-04-20 | 2 | experimental |  |
| autorag | 2026-04-21 | 1 | experimental |  |
| browser-use | 2026-04-21 | 1 | stable |  |
| claude-code | 2026-04-21 | 1 | stable |  |
| deepteam | 2026-04-21 | 1 | experimental |  |
| garak | 2026-04-21 | 1 | stable |  |
| judgeval | 2026-04-21 | 1 | experimental |  |
| pr-agent | 2026-04-21 | 1 | stable |  |
| promptflow | 2026-04-21 | 1 | stable |  |
| reins | 2026-04-21 | 1 | experimental |  |
| beelzebub | 2026-04-22 | 0 | experimental |  |
| cordum | 2026-04-22 | 0 | experimental |  |
| coze-loop | 2026-04-22 | 0 | stable |  |
| deepeval | 2026-04-22 | 0 | experimental |  |
| lm-evaluation-harness | 2026-04-22 | 0 | stable |  |
| lmnr | 2026-04-22 | 0 | experimental |  |
| playwright-mcp | 2026-04-22 | 0 | stable |  |
| trulens | 2026-04-22 | 0 | experimental |  |
| activepieces | 2026-04-23 | -1 | stable |  |
| agent-governance-toolkit | 2026-04-23 | -1 | experimental |  |
| agenta | 2026-04-23 | -1 | experimental |  |
| agno | 2026-04-23 | -1 | stable |  |
| ai-infra-guard | 2026-04-23 | -1 | experimental |  |
| bifrost | 2026-04-23 | -1 | experimental |  |
| comfyui | 2026-04-23 | -1 | stable |  |
| copilotkit | 2026-04-23 | -1 | stable |  |
| flowise | 2026-04-23 | -1 | stable |  |
| giskard | 2026-04-23 | -1 | stable |  |
| helm | 2026-04-23 | -1 | experimental |  |
| litellm | 2026-04-23 | -1 | stable |  |
| lmms-eval | 2026-04-23 | -1 | experimental |  |
| logfire | 2026-04-23 | -1 | experimental |  |
| manifest | 2026-04-23 | -1 | stable |  |
| mastra | 2026-04-23 | -1 | stable |  |
| mcp-toolbox | 2026-04-23 | -1 | stable |  |
| mlflow | 2026-04-23 | -1 | stable |  |
| nono | 2026-04-23 | -1 | experimental |  |
| opik | 2026-04-23 | -1 | stable |  |
| phoenix | 2026-04-23 | -1 | stable |  |
| pipelock | 2026-04-23 | -1 | experimental |  |
| promptfoo | 2026-04-23 | -1 | stable |  |
| pyrit | 2026-04-23 | -1 | experimental |  |
| ragflow | 2026-04-23 | -1 | stable |  |
| skyvern | 2026-04-23 | -1 | stable |  |
| voltagent | 2026-04-23 | -1 | stable |  |

## 6. Tools with missing metadata

| tool | missing fields |
| --- | --- |
| activepieces | openssf_scorecard_score, cited_in |
| agent-governance-toolkit | openssf_scorecard_score, cited_in |
| agenta | openssf_scorecard_score, cited_in |
| agentic-guardrails | openssf_scorecard_score, cited_in |
| agentic-security | openssf_scorecard_score, cited_in |
| agno | openssf_scorecard_score, cited_in |
| ai-infra-guard | openssf_scorecard_score, cited_in |
| ai-red-teaming-playground-labs | openssf_scorecard_score, cited_in |
| aider | openssf_scorecard_score, cited_in |
| arize-phoenix | openssf_scorecard_score, cited_in |
| autogen | openssf_scorecard_score |
| autorag | openssf_scorecard_score, cited_in |
| beelzebub | openssf_scorecard_score, cited_in |
| bifrost | openssf_scorecard_score, cited_in |
| braintrust | stars, openssf_scorecard_score, cited_in |
| browser-mcp | openssf_scorecard_score, cited_in |
| browser-use | openssf_scorecard_score, cited_in |
| claude-code | stars, openssf_scorecard_score, cited_in |
| cline | openssf_scorecard_score, cited_in |
| codex-cli | openssf_scorecard_score, cited_in |
| comfyui | openssf_scorecard_score, cited_in |
| confident-ai-deepteam | openssf_scorecard_score, cited_in |
| context-hub | openssf_scorecard_score, cited_in |
| continue-dev | openssf_scorecard_score, cited_in |
| copilotkit | openssf_scorecard_score, cited_in |
| cordum | openssf_scorecard_score, cited_in |
| coze-loop | openssf_scorecard_score, cited_in |
| crewai | openssf_scorecard_score, cited_in |
| cursor | stars, openssf_scorecard_score, cited_in |
| daytona | openssf_scorecard_score, cited_in |
| deepeval | openssf_scorecard_score, cited_in |
| deepteam | openssf_scorecard_score, cited_in |
| dependabot | openssf_scorecard_score, cited_in |
| devin | stars, openssf_scorecard_score, cited_in |
| docetl | openssf_scorecard_score, cited_in |
| e2b | openssf_scorecard_score, cited_in |
| flowise | openssf_scorecard_score, cited_in |
| fuzzyai | openssf_scorecard_score, cited_in |
| garak | openssf_scorecard_score, cited_in |
| gemini-cli | openssf_scorecard_score |
| giskard | openssf_scorecard_score, cited_in |
| github-copilot | stars, openssf_scorecard_score, cited_in |
| guardrails-ai | openssf_scorecard_score, cited_in |
| guidance | openssf_scorecard_score, cited_in |
| helicone | openssf_scorecard_score, cited_in |
| helm | openssf_scorecard_score, cited_in |
| instructor | openssf_scorecard_score, cited_in |
| judgeval | openssf_scorecard_score, cited_in |
| langfuse | openssf_scorecard_score, cited_in |
| langgraph | openssf_scorecard_score, cited_in |
| langkit | openssf_scorecard_score, cited_in |
| langsmith | stars, openssf_scorecard_score, cited_in |
| last-layer | openssf_scorecard_score, cited_in |
| letta | openssf_scorecard_score, cited_in |
| lighteval | openssf_scorecard_score, cited_in |
| litellm | openssf_scorecard_score, cited_in |
| llm-guard | openssf_scorecard_score, cited_in |
| lm-evaluation-harness | openssf_scorecard_score, cited_in |
| lmms-eval | openssf_scorecard_score, cited_in |
| lmnr | openssf_scorecard_score, cited_in |
| logfire | openssf_scorecard_score, cited_in |
| magic-mcp | openssf_scorecard_score, cited_in |
| manifest | openssf_scorecard_score, cited_in |
| mastra | openssf_scorecard_score, cited_in |
| mcp-playwright | openssf_scorecard_score, cited_in |
| mcp-server-browserbase | openssf_scorecard_score, cited_in |
| mcp-toolbox | openssf_scorecard_score, cited_in |
| mlflow | openssf_scorecard_score, cited_in |
| modal | stars, openssf_scorecard_score, cited_in |
| nemo-guardrails | openssf_scorecard_score, cited_in |
| nono | openssf_scorecard_score, cited_in |
| openai-evals | openssf_scorecard_score, cited_in |
| openhands | openssf_scorecard_score, cited_in |
| openlit | openssf_scorecard_score, cited_in |
| opik | openssf_scorecard_score, cited_in |
| outlines | openssf_scorecard_score, cited_in |
| pathway-llm-app | openssf_scorecard_score, cited_in |
| pezzo | openssf_scorecard_score, cited_in |
| phoenix | openssf_scorecard_score, cited_in |
| pipelock | openssf_scorecard_score, cited_in |
| playwright-mcp | openssf_scorecard_score, cited_in |
| pr-agent | openssf_scorecard_score, cited_in |
| promptbench | openssf_scorecard_score, cited_in |
| promptflow | openssf_scorecard_score, cited_in |
| promptfoo | openssf_scorecard_score, cited_in |
| promptmap | openssf_scorecard_score, cited_in |
| pydantic-ai | openssf_scorecard_score, cited_in |
| pyrit | openssf_scorecard_score, cited_in |
| ragas | openssf_scorecard_score, cited_in |
| ragflow | openssf_scorecard_score, cited_in |
| rebuff | openssf_scorecard_score, cited_in |
| reins | openssf_scorecard_score, cited_in |
| renovate | openssf_scorecard_score, cited_in |
| replit-agent | stars, openssf_scorecard_score, cited_in |
| rust-docs-mcp-server | openssf_scorecard_score, cited_in |
| safe-rlhf | openssf_scorecard_score, cited_in |
| semgrep | openssf_scorecard_score, cited_in |
| skyvern | openssf_scorecard_score, cited_in |
| smolagents | openssf_scorecard_score, cited_in |
| snyk | openssf_scorecard_score, cited_in |
| socket | stars, openssf_scorecard_score |
| sourcegraph-cody | stars, openssf_scorecard_score, cited_in |
| superagent | openssf_scorecard_score, cited_in |
| swe-agent | openssf_scorecard_score, cited_in |
| tree-sitter | openssf_scorecard_score, cited_in |
| trulens | openssf_scorecard_score, cited_in |
| uqlm | openssf_scorecard_score, cited_in |
| v0 | stars, openssf_scorecard_score, cited_in |
| voltagent | openssf_scorecard_score, cited_in |
| windsurf | stars, openssf_scorecard_score, cited_in |
| zed-agent | openssf_scorecard_score, cited_in |

## 7. Papers the tool description suggests should be cited

_Best-effort keyword matching. Suggestions only; no YAML edits performed._

| tool (cited_in is empty) | suggested papers |
| --- | --- |
| activepieces | wang-2024-llms-meet-library-evolution, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, luo-2025-mcp-universe |
| agent-governance-toolkit | manheim-homewood-2025-control-oversight |
| agenta | wang-2024-llms-meet-library-evolution, lindner-2025-monitoring |
| agentic-guardrails | liu-2024-beyond-functional-correctness, tian-2024-codehalu, zhang-wang-shi-ma-2024-practical-hallucination, lee-2025-hallucination-taxonomy, cihon-stein-2025-autonomy-scoring |
| agno | cemri-2025-mast |
| ai-infra-guard | luo-2025-mcp-universe |
| aider | manheim-homewood-2025-control-oversight, morabito-wu-2025-code-autopilot, shah-2026-characterizing-faults |
| arize-phoenix | liu-2024-beyond-functional-correctness, tian-2024-codehalu, zhang-wang-shi-ma-2024-practical-hallucination, lee-2025-hallucination-taxonomy, lindner-2025-monitoring, cihon-stein-2025-autonomy-scoring, qi-2026-rift |
| autorag | lindner-2025-monitoring |
| beelzebub | lindner-2025-monitoring, xu-2025-ckgfuzzer |
| bifrost | ehsani-2026-where-ai-agents-fail |
| braintrust | lindner-2025-monitoring, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, qi-2026-rift |
| browser-mcp | manheim-homewood-2025-control-oversight, luo-2025-mcp-universe |
| claude-code | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, morabito-wu-2025-code-autopilot |
| cline | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, luo-2025-mcp-universe, morabito-wu-2025-code-autopilot |
| codex-cli | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot, shah-2026-characterizing-faults |
| confident-ai-deepteam | lindner-2025-monitoring, cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| context-hub | liu-2024-beyond-functional-correctness, wang-2024-llms-meet-library-evolution, cihon-stein-2025-autonomy-scoring, morabito-wu-2025-code-autopilot |
| continue-dev | manheim-homewood-2025-control-oversight, luo-2025-mcp-universe |
| copilotkit | manheim-homewood-2025-control-oversight |
| cordum | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, luo-2025-mcp-universe |
| coze-loop | lindner-2025-monitoring |
| crewai | cemri-2025-mast, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring |
| cursor | manheim-homewood-2025-control-oversight |
| daytona | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot |
| deepeval | liu-2024-beyond-functional-correctness, tian-2024-codehalu, zhang-wang-shi-ma-2024-practical-hallucination, lee-2025-hallucination-taxonomy, lindner-2025-monitoring |
| deepteam | navneet-2025-safe-ai |
| dependabot | wang-2024-llms-meet-library-evolution, lindner-2025-monitoring, cihon-stein-2025-autonomy-scoring, shah-2026-characterizing-faults, ehsani-2026-where-ai-agents-fail |
| devin | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot, shah-2026-characterizing-faults |
| e2b | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot |
| fuzzyai | lindner-2025-monitoring, xu-2025-ckgfuzzer |
| giskard | liu-2024-beyond-functional-correctness, tian-2024-codehalu, zhang-wang-shi-ma-2024-practical-hallucination, lee-2025-hallucination-taxonomy, qi-2026-rift |
| github-copilot | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot |
| guardrails-ai | cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| guidance | cemri-2025-mast, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring |
| helicone | lindner-2025-monitoring, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring |
| helm | navneet-2025-safe-ai |
| instructor | cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| judgeval | lindner-2025-monitoring, qi-2026-rift |
| langfuse | wang-2024-llms-meet-library-evolution, lindner-2025-monitoring, cihon-stein-2025-autonomy-scoring, qi-2026-rift |
| langgraph | cemri-2025-mast, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring |
| langkit | lindner-2025-monitoring, navneet-2025-safe-ai, cihon-stein-2025-autonomy-scoring, qi-2026-rift |
| langsmith | wang-2024-llms-meet-library-evolution, lindner-2025-monitoring, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, qi-2026-rift |
| last-layer | navneet-2025-safe-ai, cihon-stein-2025-autonomy-scoring, morabito-wu-2025-code-autopilot |
| letta | manheim-homewood-2025-control-oversight |
| litellm | ehsani-2026-where-ai-agents-fail |
| lmnr | wang-2024-llms-meet-library-evolution, lindner-2025-monitoring |
| logfire | lindner-2025-monitoring |
| magic-mcp | luo-2025-mcp-universe, morabito-wu-2025-code-autopilot |
| manifest | manheim-homewood-2025-control-oversight, ehsani-2026-where-ai-agents-fail |
| mastra | cemri-2025-mast, lindner-2025-monitoring |
| mcp-playwright | luo-2025-mcp-universe |
| mcp-server-browserbase | manheim-homewood-2025-control-oversight, yan-2025-fault-tolerant-sandboxing, luo-2025-mcp-universe |
| mcp-toolbox | navneet-2025-safe-ai, luo-2025-mcp-universe |
| mlflow | lindner-2025-monitoring |
| modal | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing |
| nemo-guardrails | manheim-homewood-2025-control-oversight, navneet-2025-safe-ai, cihon-stein-2025-autonomy-scoring |
| nono | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing |
| openhands | cemri-2025-mast, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot, shah-2026-characterizing-faults |
| openlit | lindner-2025-monitoring, manheim-homewood-2025-control-oversight |
| opik | cemri-2025-mast, lindner-2025-monitoring |
| outlines | cemri-2025-mast, cihon-stein-2025-autonomy-scoring |
| pathway-llm-app | wang-2024-llms-meet-library-evolution, qi-2026-rift, ehsani-2026-where-ai-agents-fail |
| pezzo | wang-2024-llms-meet-library-evolution, lindner-2025-monitoring, manheim-homewood-2025-control-oversight |
| phoenix | lindner-2025-monitoring |
| pipelock | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, luo-2025-mcp-universe |
| playwright-mcp | manheim-homewood-2025-control-oversight, luo-2025-mcp-universe |
| pr-agent | manheim-homewood-2025-control-oversight |
| promptflow | lindner-2025-monitoring |
| pydantic-ai | cemri-2025-mast, lindner-2025-monitoring, cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| pyrit | xu-2025-ckgfuzzer |
| ragflow | liu-2024-beyond-functional-correctness, tian-2024-codehalu, zhang-wang-shi-ma-2024-practical-hallucination, lee-2025-hallucination-taxonomy, lindner-2025-monitoring |
| rebuff | cihon-stein-2025-autonomy-scoring |
| reins | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, morabito-wu-2025-code-autopilot, shah-2026-characterizing-faults |
| renovate | wang-2024-llms-meet-library-evolution |
| replit-agent | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot, shah-2026-characterizing-faults |
| rust-docs-mcp-server | cihon-stein-2025-autonomy-scoring, luo-2025-mcp-universe, shah-2026-characterizing-faults |
| safe-rlhf | manheim-homewood-2025-control-oversight, navneet-2025-safe-ai |
| semgrep | liu-2025-code-copycat, cihon-stein-2025-autonomy-scoring |
| skyvern | manheim-homewood-2025-control-oversight |
| smolagents | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing |
| snyk | spracklen-2024-we-have-a-package, williams-2025-sscs, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| sourcegraph-cody | liu-2024-beyond-functional-correctness, cihon-stein-2025-autonomy-scoring |
| superagent | navneet-2025-safe-ai, cihon-stein-2025-autonomy-scoring |
| swe-agent | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, shah-2026-characterizing-faults |
| tree-sitter | liu-2025-code-copycat, cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| trulens | lindner-2025-monitoring |
| v0 | liu-2024-beyond-functional-correctness, manheim-homewood-2025-control-oversight, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot |
| voltagent | cemri-2025-mast, lindner-2025-monitoring |
| windsurf | manheim-homewood-2025-control-oversight, luo-2025-mcp-universe, shah-2026-characterizing-faults |
| zed-agent | spracklen-2024-we-have-a-package, williams-2025-sscs, manheim-homewood-2025-control-oversight |

## 8. Governance hygiene (Tools by `published_by`)

| org | # tools | share | flag |
| --- | --- | --- | --- |
| <unknown> | 12 | 10.8% |  |
| microsoft | 7 | 6.3% |  |
| arize-ai | 2 | 1.8% |  |
| openai | 2 | 1.8% |  |
| confident-ai | 2 | 1.8% |  |
| github | 2 | 1.8% |  |
| nvidia | 2 | 1.8% |  |
| google | 2 | 1.8% |  |
| langchain-ai | 2 | 1.8% |  |
| huggingface | 2 | 1.8% |  |
| pydantic | 2 | 1.8% |  |
| activepieces | 1 | 0.9% |  |
| agenta-ai | 1 | 0.9% |  |
| agentic-security | 1 | 0.9% |  |
| agno-agi | 1 | 0.9% |  |
| tencent | 1 | 0.9% |  |
| paul-gauthier | 1 | 0.9% |  |
| marker-inc | 1 | 0.9% |  |
| beelzebub-labs | 1 | 0.9% |  |
| maxim-hq | 1 | 0.9% |  |
| braintrust-data | 1 | 0.9% |  |
| browsermcp | 1 | 0.9% |  |
| browser-use | 1 | 0.9% |  |
| anthropic | 1 | 0.9% |  |
| cline | 1 | 0.9% |  |
| comfy | 1 | 0.9% |  |
| deeplearning-ai | 1 | 0.9% |  |
| continuedev | 1 | 0.9% |  |
| copilotkit | 1 | 0.9% |  |
| coze-dev | 1 | 0.9% |  |
| crewai-inc | 1 | 0.9% |  |
| anysphere | 1 | 0.9% |  |
| daytona-io | 1 | 0.9% |  |
| cognition-labs | 1 | 0.9% |  |
| ucb-epic | 1 | 0.9% |  |
| e2b | 1 | 0.9% |  |
| flowise-ai | 1 | 0.9% |  |
| cyberark | 1 | 0.9% |  |
| giskard | 1 | 0.9% |  |
| guardrails-ai | 1 | 0.9% |  |
| guidance-ai | 1 | 0.9% |  |
| helicone | 1 | 0.9% |  |
| stanford-crfm | 1 | 0.9% |  |
| jxnl | 1 | 0.9% |  |
| judgment-labs | 1 | 0.9% |  |
| langfuse | 1 | 0.9% |  |
| letta-ai | 1 | 0.9% |  |
| berri-ai | 1 | 0.9% |  |
| protectai | 1 | 0.9% |  |
| eleutherai | 1 | 0.9% |  |
| evolvinglmms-lab | 1 | 0.9% |  |
| lmnr-ai | 1 | 0.9% |  |
| 21st-dev | 1 | 0.9% |  |
| manifest | 1 | 0.9% |  |
| mastra-ai | 1 | 0.9% |  |
| execute-automation | 1 | 0.9% |  |
| browserbase | 1 | 0.9% |  |
| databricks | 1 | 0.9% |  |
| modal-labs | 1 | 0.9% |  |
| all-hands-ai | 1 | 0.9% |  |
| openlit | 1 | 0.9% |  |
| comet-ml | 1 | 0.9% |  |
| dottxt-ai | 1 | 0.9% |  |
| pathway | 1 | 0.9% |  |
| pezzo-labs | 1 | 0.9% |  |
| qodo | 1 | 0.9% |  |
| promptfoo | 1 | 0.9% |  |
| utkusen | 1 | 0.9% |  |
| exploding-gradients | 1 | 0.9% |  |
| infiniflow | 1 | 0.9% |  |
| mend | 1 | 0.9% |  |
| replit | 1 | 0.9% |  |
| pku-alignment | 1 | 0.9% |  |
| semgrep | 1 | 0.9% |  |
| skyvern-ai | 1 | 0.9% |  |
| snyk | 1 | 0.9% |  |
| socket-dev | 1 | 0.9% |  |
| sourcegraph | 1 | 0.9% |  |
| princeton-nlp | 1 | 0.9% |  |
| tree-sitter | 1 | 0.9% |  |
| cvs-health | 1 | 0.9% |  |
| vercel | 1 | 0.9% |  |
| voltagent | 1 | 0.9% |  |
| codeium | 1 | 0.9% |  |
| zed-industries | 1 | 0.9% |  |

## 9. Top 10 actionable next steps

1. Add Tool for prevention x pre_generation x full_hitl (0 tools in that cell)
2. Add Tool for prevention x post_generation x full_hitl (0 tools in that cell)
3. Add Tool for detection x in_generation x fully_autonomous (0 tools in that cell)
4. Add Tool for detection x in_generation x graduated_hitl (0 tools in that cell)
5. Add Tool for detection x in_generation x full_hitl (0 tools in that cell)
6. Add Tool for correction x pre_generation x fully_autonomous (0 tools in that cell)
7. Add Tool for correction x pre_generation x graduated_hitl (0 tools in that cell)
8. Add Tool for correction x pre_generation x full_hitl (0 tools in that cell)
9. Add Tool for correction x in_generation x fully_autonomous (0 tools in that cell)
10. Add Tool for correction x in_generation x graduated_hitl (0 tools in that cell)
