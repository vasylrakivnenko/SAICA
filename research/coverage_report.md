# SAICA-KG Coverage & Gap Report

_Generated: 2026-04-23T09:29:35+00:00 (report date: 2026-04-22)_

This report highlights where the SAICA-KG is thin and what to add next. It is produced by `validator/coverage_report.py` and never blocks CI; the companion script `validator/cli.py` handles hard invariants.

## 1. Summary

| Node type | Count |
| --- | --- |
| Tools | 52 |
| FailureModes | 11 |
| Papers | 25 |
| Taxonomies | 6 |
| Crosswalks (bulk) | 6 |
| Facet cells (filled / 36) | 12 / 36 |
| FailureModes with < 3 mitigators | 0 |
| Tools older than 180 days | 3 |

## 2. Facet-cell occupancy (ControlParadigm x TemporalPhase x AutonomyLevel)

Total cells: 4 x 3 x 3 = 36. Empty cells: **24**.

| control_paradigm | temporal_phase | autonomy_level | # tools | tool names |
| --- | --- | --- | --- | --- |
| prevention | pre_generation | fully_autonomous | 5 | AutoGen, Context Hub, CrewAI, LangGraph, tree-sitter |
| prevention | pre_generation | graduated_hitl | 10 | Claude Code, Cline, Continue, Cordum, Cursor, Gemini CLI, Sourcegraph Cody, Windsurf, Zed Agent, v0 |
| prevention | pre_generation | full_hitl | 0 | **WARN EMPTY** |
| prevention | in_generation | fully_autonomous | 5 | Guidance, Outlines, PipelineLock, Superagent, nono |
| prevention | in_generation | graduated_hitl | 0 | **WARN EMPTY** |
| prevention | in_generation | full_hitl | 0 | **WARN EMPTY** |
| prevention | post_generation | fully_autonomous | 1 | Agentic Guardrails |
| prevention | post_generation | graduated_hitl | 0 | **WARN EMPTY** |
| prevention | post_generation | full_hitl | 0 | **WARN EMPTY** |
| detection | pre_generation | fully_autonomous | 3 | Rebuff, Socket, last_layer |
| detection | pre_generation | graduated_hitl | 1 | GitHub Copilot |
| detection | pre_generation | full_hitl | 0 | **WARN EMPTY** |
| detection | in_generation | fully_autonomous | 0 | **WARN EMPTY** |
| detection | in_generation | graduated_hitl | 0 | **WARN EMPTY** |
| detection | in_generation | full_hitl | 0 | **WARN EMPTY** |
| detection | post_generation | fully_autonomous | 14 | Arize Phoenix, Braintrust, DeepTeam, Guardrails AI, Helicone, Instructor, LangKit, LangSmith, Langfuse, NeMo Guardrails, PydanticAI, Semgrep, Smolagents, Snyk |
| detection | post_generation | graduated_hitl | 3 | Dependabot, Renovate, TruLens |
| detection | post_generation | full_hitl | 1 | DeepEval |
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
- `prevention` x `in_generation` x `graduated_hitl`
- `prevention` x `in_generation` x `full_hitl`
- `prevention` x `post_generation` x `graduated_hitl`
- `prevention` x `post_generation` x `full_hitl`
- `detection` x `pre_generation` x `full_hitl`
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
| fabrication | 20 |  | 11 | Agentic Guardrails, Arize Phoenix, Context Hub, Continue, Cursor, DeepEval, DeepTeam, Gemini CLI, GitHub Copilot, Guardrails AI, Guidance, Instructor, NeMo Guardrails, Outlines, PydanticAI, Smolagents, Sourcegraph Cody, TruLens, Windsurf, v0 |
| obsolescence | 4 |  | 8 | Context Hub, Dependabot, Renovate, Sourcegraph Cody |
| dependency_blindness | 4 |  | 2 | Continue, Semgrep, Sourcegraph Cody, tree-sitter |
| logic_error | 21 |  | 26 | Aider, Arize Phoenix, Braintrust, Codex CLI, Daytona, DeepEval, Devin, E2B, Guardrails AI, Guidance, Helicone, Instructor, LangSmith, Langfuse, Modal, OpenHands, Outlines, PydanticAI, Replit Agent, SWE-agent, Smolagents |
| security_vulnerability | 17 |  | 18 | Agentic Guardrails, Daytona, DeepTeam, Dependabot, E2B, Guardrails AI, LangKit, Modal, NeMo Guardrails, OpenHands, PipelineLock, Rebuff, Semgrep, Snyk, Superagent, last_layer, nono |
| scope_creep | 24 |  | 17 | Aider, AutoGen, Braintrust, Claude Code, Cline, Codex CLI, Cordum, CrewAI, Cursor, Devin, Gemini CLI, GitHub Copilot, Guardrails AI, LangGraph, LangSmith, Langfuse, NeMo Guardrails, OpenHands, PydanticAI, Replit Agent, Windsurf, Zed Agent, nono, v0 |
| context_pollution | 17 |  | 20 | Aider, Arize Phoenix, AutoGen, Braintrust, Claude Code, Cline, CrewAI, Cursor, Gemini CLI, Helicone, LangGraph, LangSmith, Langfuse, NeMo Guardrails, TruLens, Windsurf, Zed Agent |
| supply_chain_attack | 12 |  | 8 | Claude Code, Cline, Daytona, DeepTeam, Dependabot, E2B, Modal, OpenHands, PipelineLock, Renovate, Snyk, Socket |

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
| guidance | 2026-01-20 | 92 | stable |  |
| nemo-guardrails | 2026-02-10 | 71 | stable |  |
| outlines | 2026-03-01 | 52 | stable |  |
| pydantic-ai | 2026-03-15 | 38 | stable |  |
| swe-agent | 2026-03-15 | 38 | stable |  |
| guardrails-ai | 2026-03-20 | 33 | stable |  |
| instructor | 2026-03-25 | 28 | stable |  |
| smolagents | 2026-03-25 | 28 | stable |  |
| aider | 2026-03-28 | 25 | stable |  |
| autogen | 2026-03-30 | 23 | stable |  |
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
| modal | 2026-04-12 | 10 | stable |  |
| snyk | 2026-04-12 | 10 | stable |  |
| codex-cli | 2026-04-15 | 7 | stable |  |
| context-hub | 2026-04-15 | 7 | experimental |  |
| dependabot | 2026-04-15 | 7 | stable |  |
| gemini-cli | 2026-04-15 | 7 | stable |  |
| github-copilot | 2026-04-15 | 7 | stable |  |
| semgrep | 2026-04-17 | 5 | stable |  |
| renovate | 2026-04-18 | 4 | stable |  |
| claude-code | 2026-04-21 | 1 | stable |  |
| cordum | 2026-04-22 | 0 | experimental |  |
| deepeval | 2026-04-22 | 0 | experimental |  |
| trulens | 2026-04-22 | 0 | experimental |  |
| nono | 2026-04-23 | -1 | experimental |  |
| pipelock | 2026-04-23 | -1 | experimental |  |

## 6. Tools with missing metadata

| tool | missing fields |
| --- | --- |
| agentic-guardrails | openssf_scorecard_score, cited_in |
| aider | openssf_scorecard_score, cited_in |
| arize-phoenix | openssf_scorecard_score, cited_in |
| autogen | openssf_scorecard_score |
| braintrust | stars, openssf_scorecard_score, cited_in |
| claude-code | stars, openssf_scorecard_score, cited_in |
| cline | openssf_scorecard_score, cited_in |
| codex-cli | openssf_scorecard_score, cited_in |
| confident-ai-deepteam | openssf_scorecard_score, cited_in |
| context-hub | openssf_scorecard_score, cited_in |
| continue-dev | openssf_scorecard_score, cited_in |
| cordum | openssf_scorecard_score, cited_in |
| crewai | openssf_scorecard_score, cited_in |
| cursor | stars, openssf_scorecard_score, cited_in |
| daytona | openssf_scorecard_score, cited_in |
| deepeval | openssf_scorecard_score, cited_in |
| dependabot | openssf_scorecard_score, cited_in |
| devin | stars, openssf_scorecard_score, cited_in |
| e2b | openssf_scorecard_score, cited_in |
| gemini-cli | openssf_scorecard_score |
| github-copilot | stars, openssf_scorecard_score, cited_in |
| guardrails-ai | openssf_scorecard_score, cited_in |
| guidance | openssf_scorecard_score, cited_in |
| helicone | openssf_scorecard_score, cited_in |
| instructor | openssf_scorecard_score, cited_in |
| langfuse | openssf_scorecard_score, cited_in |
| langgraph | openssf_scorecard_score, cited_in |
| langkit | openssf_scorecard_score, cited_in |
| langsmith | stars, openssf_scorecard_score, cited_in |
| last-layer | openssf_scorecard_score, cited_in |
| modal | stars, openssf_scorecard_score, cited_in |
| nemo-guardrails | openssf_scorecard_score, cited_in |
| nono | openssf_scorecard_score, cited_in |
| openhands | openssf_scorecard_score, cited_in |
| outlines | openssf_scorecard_score, cited_in |
| pipelock | openssf_scorecard_score, cited_in |
| pydantic-ai | openssf_scorecard_score, cited_in |
| rebuff | openssf_scorecard_score, cited_in |
| renovate | openssf_scorecard_score, cited_in |
| replit-agent | stars, openssf_scorecard_score, cited_in |
| semgrep | openssf_scorecard_score, cited_in |
| smolagents | openssf_scorecard_score, cited_in |
| snyk | openssf_scorecard_score, cited_in |
| socket | stars, openssf_scorecard_score |
| sourcegraph-cody | stars, openssf_scorecard_score, cited_in |
| superagent | openssf_scorecard_score, cited_in |
| swe-agent | openssf_scorecard_score, cited_in |
| tree-sitter | openssf_scorecard_score, cited_in |
| trulens | openssf_scorecard_score, cited_in |
| v0 | stars, openssf_scorecard_score, cited_in |
| windsurf | stars, openssf_scorecard_score, cited_in |
| zed-agent | openssf_scorecard_score, cited_in |

## 7. Papers the tool description suggests should be cited

_Best-effort keyword matching. Suggestions only; no YAML edits performed._

| tool (cited_in is empty) | suggested papers |
| --- | --- |
| agentic-guardrails | liu-2024-beyond-functional-correctness, tian-2024-codehalu, zhang-wang-shi-ma-2024-practical-hallucination, lee-2025-hallucination-taxonomy, cihon-stein-2025-autonomy-scoring |
| aider | manheim-homewood-2025-control-oversight, morabito-wu-2025-code-autopilot, shah-2026-characterizing-faults |
| arize-phoenix | liu-2024-beyond-functional-correctness, tian-2024-codehalu, zhang-wang-shi-ma-2024-practical-hallucination, lee-2025-hallucination-taxonomy, lindner-2025-monitoring, cihon-stein-2025-autonomy-scoring, qi-2026-rift |
| braintrust | lindner-2025-monitoring, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, qi-2026-rift |
| claude-code | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, morabito-wu-2025-code-autopilot |
| cline | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, luo-2025-mcp-universe, morabito-wu-2025-code-autopilot |
| codex-cli | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot, shah-2026-characterizing-faults |
| confident-ai-deepteam | lindner-2025-monitoring, cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| context-hub | liu-2024-beyond-functional-correctness, wang-2024-llms-meet-library-evolution, cihon-stein-2025-autonomy-scoring, morabito-wu-2025-code-autopilot |
| continue-dev | manheim-homewood-2025-control-oversight, luo-2025-mcp-universe |
| cordum | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, luo-2025-mcp-universe |
| crewai | cemri-2025-mast, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring |
| cursor | manheim-homewood-2025-control-oversight |
| daytona | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot |
| deepeval | liu-2024-beyond-functional-correctness, tian-2024-codehalu, zhang-wang-shi-ma-2024-practical-hallucination, lee-2025-hallucination-taxonomy, lindner-2025-monitoring |
| dependabot | wang-2024-llms-meet-library-evolution, lindner-2025-monitoring, cihon-stein-2025-autonomy-scoring, shah-2026-characterizing-faults, ehsani-2026-where-ai-agents-fail |
| devin | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot, shah-2026-characterizing-faults |
| e2b | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot |
| github-copilot | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot |
| guardrails-ai | cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| guidance | cemri-2025-mast, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring |
| helicone | lindner-2025-monitoring, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring |
| instructor | cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| langfuse | wang-2024-llms-meet-library-evolution, lindner-2025-monitoring, cihon-stein-2025-autonomy-scoring, qi-2026-rift |
| langgraph | cemri-2025-mast, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring |
| langkit | lindner-2025-monitoring, navneet-2025-safe-ai, cihon-stein-2025-autonomy-scoring, qi-2026-rift |
| langsmith | wang-2024-llms-meet-library-evolution, lindner-2025-monitoring, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, qi-2026-rift |
| last-layer | navneet-2025-safe-ai, cihon-stein-2025-autonomy-scoring, morabito-wu-2025-code-autopilot |
| modal | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing |
| nemo-guardrails | manheim-homewood-2025-control-oversight, navneet-2025-safe-ai, cihon-stein-2025-autonomy-scoring |
| nono | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing |
| openhands | cemri-2025-mast, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot, shah-2026-characterizing-faults |
| outlines | cemri-2025-mast, cihon-stein-2025-autonomy-scoring |
| pipelock | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, luo-2025-mcp-universe |
| pydantic-ai | cemri-2025-mast, lindner-2025-monitoring, cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| rebuff | cihon-stein-2025-autonomy-scoring |
| renovate | wang-2024-llms-meet-library-evolution |
| replit-agent | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot, shah-2026-characterizing-faults |
| semgrep | liu-2025-code-copycat, cihon-stein-2025-autonomy-scoring |
| smolagents | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing |
| snyk | spracklen-2024-we-have-a-package, williams-2025-sscs, manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| sourcegraph-cody | liu-2024-beyond-functional-correctness, cihon-stein-2025-autonomy-scoring |
| superagent | navneet-2025-safe-ai, cihon-stein-2025-autonomy-scoring |
| swe-agent | manheim-homewood-2025-control-oversight, cihon-stein-2025-autonomy-scoring, yan-2025-fault-tolerant-sandboxing, shah-2026-characterizing-faults |
| tree-sitter | liu-2025-code-copycat, cihon-stein-2025-autonomy-scoring, ehsani-2026-where-ai-agents-fail |
| trulens | lindner-2025-monitoring |
| v0 | liu-2024-beyond-functional-correctness, manheim-homewood-2025-control-oversight, yan-2025-fault-tolerant-sandboxing, morabito-wu-2025-code-autopilot |
| windsurf | manheim-homewood-2025-control-oversight, luo-2025-mcp-universe, shah-2026-characterizing-faults |
| zed-agent | spracklen-2024-we-have-a-package, williams-2025-sscs, manheim-homewood-2025-control-oversight |

## 8. Governance hygiene (Tools by `published_by`)

| org | # tools | share | flag |
| --- | --- | --- | --- |
| <unknown> | 10 | 19.2% |  |
| github | 2 | 3.8% |  |
| langchain-ai | 2 | 3.8% |  |
| paul-gauthier | 1 | 1.9% |  |
| arize-ai | 1 | 1.9% |  |
| microsoft | 1 | 1.9% |  |
| braintrust-data | 1 | 1.9% |  |
| anthropic | 1 | 1.9% |  |
| cline | 1 | 1.9% |  |
| openai | 1 | 1.9% |  |
| confident-ai | 1 | 1.9% |  |
| deeplearning-ai | 1 | 1.9% |  |
| continuedev | 1 | 1.9% |  |
| crewai-inc | 1 | 1.9% |  |
| anysphere | 1 | 1.9% |  |
| daytona-io | 1 | 1.9% |  |
| cognition-labs | 1 | 1.9% |  |
| e2b | 1 | 1.9% |  |
| google | 1 | 1.9% |  |
| guardrails-ai | 1 | 1.9% |  |
| guidance-ai | 1 | 1.9% |  |
| helicone | 1 | 1.9% |  |
| jxnl | 1 | 1.9% |  |
| langfuse | 1 | 1.9% |  |
| modal-labs | 1 | 1.9% |  |
| nvidia | 1 | 1.9% |  |
| all-hands-ai | 1 | 1.9% |  |
| dottxt-ai | 1 | 1.9% |  |
| pydantic | 1 | 1.9% |  |
| mend | 1 | 1.9% |  |
| replit | 1 | 1.9% |  |
| semgrep | 1 | 1.9% |  |
| huggingface | 1 | 1.9% |  |
| snyk | 1 | 1.9% |  |
| socket-dev | 1 | 1.9% |  |
| sourcegraph | 1 | 1.9% |  |
| princeton-nlp | 1 | 1.9% |  |
| tree-sitter | 1 | 1.9% |  |
| vercel | 1 | 1.9% |  |
| codeium | 1 | 1.9% |  |
| zed-industries | 1 | 1.9% |  |

## 9. Top 10 actionable next steps

1. Add Tool for prevention x pre_generation x full_hitl (0 tools in that cell)
2. Add Tool for prevention x in_generation x graduated_hitl (0 tools in that cell)
3. Add Tool for prevention x in_generation x full_hitl (0 tools in that cell)
4. Add Tool for prevention x post_generation x graduated_hitl (0 tools in that cell)
5. Add Tool for prevention x post_generation x full_hitl (0 tools in that cell)
6. Add Tool for detection x pre_generation x full_hitl (0 tools in that cell)
7. Add Tool for detection x in_generation x fully_autonomous (0 tools in that cell)
8. Add Tool for detection x in_generation x graduated_hitl (0 tools in that cell)
9. Add Tool for detection x in_generation x full_hitl (0 tools in that cell)
10. Add Tool for correction x pre_generation x fully_autonomous (0 tools in that cell)
