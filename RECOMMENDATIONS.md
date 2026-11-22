# SAICA-KG — Tool suggestions from the catalogue

> These lists come from the catalogue's **tags**: what each tool's own
> documentation says it addresses. A tag is a claim, not a measurement.
> Where SAICA-Bench measured a tool on a failure mode, the J is shown,
> and a tool is never listed for a mode where it measured below J 25%.
> For picks built from measured results only, use https://saica.ai/tool-coverage/.

Pre-computed. Regenerate with `python -m validator.generate_recommendations`.
Generated from KG version 2026.11 (manifest of 2026-11-22); benchmark results of 2026-11-22.

---

## Three stacks by tag coverage

Tools are picked for how many weighted failure modes their tags name, times their popularity. See Method at the end.

**One tool (`minimum`)** — 1 tool. Its tags name 4 of 11 failure modes; none of these tool-mode pairs was measured by SAICA-Bench. A tag is the tool's own claim.

| Tool | Paradigm | Phase | Surfaces | Stars | Tagged for | Measured |
| --- | --- | --- | --- | ---: | --- | --- |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 6,590 | `security_vulnerability`, `scope_creep`, `supply_chain_attack`, `cascading_failure` | — |

**Three tools (`optimal`)** — 3 tools. Their tags name 8 of 11 failure modes; none of these tool-mode pairs was measured by SAICA-Bench. A tag is the tool's own claim.

| Tool | Paradigm | Phase | Surfaces | Stars | Tagged for | Measured |
| --- | --- | --- | --- | ---: | --- | --- |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 6,590 | `security_vulnerability`, `scope_creep`, `supply_chain_attack`, `cascading_failure` | — |
| [ESLint](data/tools/eslint.yml) | detection | post_generation | cli, ci_app, ide_plugin | 27,642 | `logic_error`, `security_vulnerability`, `fabrication`, `incomplete_execution` | — |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 45,236 | `scope_creep`, `context_pollution` | — |

**Widest reach of tags with the fewest tools (`full`)** — 6 tools. Their tags name 11 of 11 failure modes; 1 of the 16 tool-mode pairs was measured by SAICA-Bench (J at or above 25%). A tag is the tool's own claim.

| Tool | Paradigm | Phase | Surfaces | Stars | Tagged for | Measured |
| --- | --- | --- | --- | ---: | --- | --- |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | prevention | in_generation | library, cli | 6,590 | `security_vulnerability`, `scope_creep`, `supply_chain_attack`, `cascading_failure` | — |
| [ESLint](data/tools/eslint.yml) | detection | post_generation | cli, ci_app, ide_plugin | 27,642 | `logic_error`, `security_vulnerability`, `fabrication`, `incomplete_execution` | — |
| [LangGraph](data/tools/langgraph.yml) | prevention | pre_generation | library | 45,236 | `scope_creep`, `context_pollution` | — |
| [Context7](data/tools/context7.yml) | prevention | pre_generation | mcp_server, cli | 65,244 | `fabrication`, `obsolescence` | — |
| [promptfoo](data/tools/promptfoo.yml) | detection | post_generation | cli, library, ci_app | 27,525 | `scope_creep`, `test_manipulation`, `supply_chain_attack` | test_manipulation J +86% |
| [sentrux](data/tools/sentrux.yml) | detection | post_generation | cli, mcp_server, library | 3,344 | `dependency_blindness` | — |

## By coding agent

The picks are the same for all 16 coding agents the recommender knows by name (Cursor, Claude Code, Codex CLI and others): no coding agent is in the catalogue, so there is nothing to filter out for any of them.

---

## By failure mode

Up to 3 tools per failure mode. Measured tools first; a row that says "tag only" has not been tested on this mode.

### Fabrication

| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |
| --- | --- | --- | --- | --- | ---: | --- |
| [Pyright](data/tools/pyright.yml) | measured J +85% | detection | post_generation | cli, ci_app, ide_plugin | 15,755 | Microsoft's fast static type checker for Python. |
| [mypy](data/tools/mypy.yml) | measured J +77% | detection | post_generation | cli, ci_app, ide_plugin | 20,734 | Static type checker for Python. Catches mismatched types before runti… |
| [Ruff](data/tools/ruff.yml) | measured J +54% | detection | post_generation | cli, ci_app, ide_plugin | 51,351 | Extremely fast Python linter and formatter, written in Rust. |

### Obsolescence

| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |
| --- | --- | --- | --- | --- | ---: | --- |
| [Pyright](data/tools/pyright.yml) | measured J +57% | detection | post_generation | cli, ci_app, ide_plugin | 15,755 | Microsoft's fast static type checker for Python. |
| [Renovate](data/tools/renovate.yml) | tag only, not measured | detection | post_generation | ci_app, cli | 23,220 | Highly configurable multi-platform dependency update bot. |
| [Context Hub](data/tools/context-hub.yml) | tag only, not measured | prevention | pre_generation | mcp_server, cli | 13,993 | Up-to-date, curated API docs for coding agents. |

### Dependency blindness

| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |
| --- | --- | --- | --- | --- | ---: | --- |
| [sentrux](data/tools/sentrux.yml) | tag only, not measured | detection | post_generation | cli, mcp_server, library | 3,344 | Real-time architectural sensor that scores codebase modularity, acycl… |

### Logic error

| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |
| --- | --- | --- | --- | --- | ---: | --- |
| [pr-agent](data/tools/pr-agent.yml) | measured J +53% | detection | post_generation | ci_app, cli | 16,537 | AI-powered tool for automated pull-request analysis, feedback, and su… |
| [uqlm](data/tools/uqlm.yml) | measured J +52% | detection | post_generation | library | 1,215 | Uncertainty Quantification for Language Models. |
| [ESLint](data/tools/eslint.yml) | tag only, not measured | detection | post_generation | cli, ci_app, ide_plugin | 27,642 | Pluggable JavaScript/TypeScript linter and code-quality enforcer. |

### Security vulnerability

| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |
| --- | --- | --- | --- | --- | ---: | --- |
| [Ruff](data/tools/ruff.yml) | tag only, not measured | detection | post_generation | cli, ci_app, ide_plugin | 51,351 | Extremely fast Python linter and formatter, written in Rust. |
| [ESLint](data/tools/eslint.yml) | tag only, not measured | detection | post_generation | cli, ci_app, ide_plugin | 27,642 | Pluggable JavaScript/TypeScript linter and code-quality enforcer. |
| [Snyk](data/tools/snyk.yml) | tag only, not measured | detection | post_generation | cli, ci_app | 5,716 | Vulnerability scanning for code, dependencies, containers, and IaC. |

### Scope creep

| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |
| --- | --- | --- | --- | --- | ---: | --- |
| [LangGraph](data/tools/langgraph.yml) | tag only, not measured | prevention | pre_generation | library | 45,236 | Graph-structured state machines for stateful multi-agent orchestratio… |
| [letta](data/tools/letta.yml) | tag only, not measured | prevention | pre_generation | library, http_service | 25,510 | Stateful agents framework with memory, reasoning, and context managem… |
| [browser-use](data/tools/browser-use.yml) | tag only, not measured | prevention | post_generation | library, web_app | 121,683 | Make websites accessible for AI agents. |

### Context pollution

| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |
| --- | --- | --- | --- | --- | ---: | --- |
| [LangGraph](data/tools/langgraph.yml) | tag only, not measured | prevention | pre_generation | library | 45,236 | Graph-structured state machines for stateful multi-agent orchestratio… |
| [mastra](data/tools/mastra.yml) | tag only, not measured | prevention | pre_generation | library | 29,724 | The TypeScript AI agent framework — assistants, RAG, observability; s… |
| [mlflow](data/tools/mlflow.yml) | tag only, not measured | detection | post_generation | http_service, library, cli | 28,924 | Open-source platform for the machine learning lifecycle — experiments… |

### Supply chain attack

| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |
| --- | --- | --- | --- | --- | ---: | --- |
| [Semgrep](data/tools/semgrep.yml) | tag only, not measured | detection | post_generation | cli, ci_app, library | 17,880 | Fast, rule-based static analysis with a pattern syntax that mirrors s… |
| [Socket](data/tools/socket.yml) | tag only, not measured | detection | pre_generation | ci_app, cli, library | — | Dependency supply-chain scanner that inspects packages before install. |
| [promptfoo](data/tools/promptfoo.yml) | tag only, not measured | detection | post_generation | cli, library, ci_app | 27,525 | Test prompts, agents, and RAGs — red-teaming, pentesting, and vulnera… |

### Cascading failure

| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |
| --- | --- | --- | --- | --- | ---: | --- |
| [agent-governance-toolkit](data/tools/agent-governance-toolkit.yml) | tag only, not measured | prevention | in_generation | library, cli | 6,590 | AI Agent Governance Toolkit — policy enforcement, zero-trust identity… |

### Incomplete execution

| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |
| --- | --- | --- | --- | --- | ---: | --- |
| [ESLint](data/tools/eslint.yml) | tag only, not measured | detection | post_generation | cli, ci_app, ide_plugin | 27,642 | Pluggable JavaScript/TypeScript linter and code-quality enforcer. |
| [TruLens](data/tools/trulens.yml) | tag only, not measured | detection | post_generation | library | 3,665 | Evaluation and Tracking for LLM Experiments and AI Agents |

### Test manipulation

| Tool | Evidence for this mode | Paradigm | Phase | Surfaces | Stars | What it is |
| --- | --- | --- | --- | --- | ---: | --- |
| [promptfoo](data/tools/promptfoo.yml) | measured J +86% | detection | post_generation | cli, library, ci_app | 27,525 | Test prompts, agents, and RAGs — red-teaming, pentesting, and vulnera… |

---

## Tagged, measured, not listed

These tools are tagged for the mode in the catalogue, but SAICA-Bench measured them below J 25% on it (or their repository is archived), so no list in this file names them for that mode.

| Tool | Failure mode | Why not listed |
| --- | --- | --- |
| [arize-phoenix](data/tools/arize-phoenix.yml) | `incomplete_execution` | measured J +6.6% |
| [autogen](data/tools/autogen.yml) | `scope_creep` | upstream repository is archived |
| [bandit](data/tools/bandit.yml) | `security_vulnerability` | measured J +1.3% |
| [daytona](data/tools/daytona.yml) | `supply_chain_attack` | upstream repository is archived |
| [daytona](data/tools/daytona.yml) | `security_vulnerability` | upstream repository is archived |
| [daytona](data/tools/daytona.yml) | `scope_creep` | upstream repository is archived |
| [deepeval](data/tools/deepeval.yml) | `incomplete_execution` | measured J +0.9% |
| [flowise](data/tools/flowise.yml) | `scope_creep` | upstream repository is archived |
| [llm-guard](data/tools/llm-guard.yml) | `security_vulnerability` | upstream repository is archived |
| [llm-guard](data/tools/llm-guard.yml) | `fabrication` | upstream repository is archived |
| [mypy](data/tools/mypy.yml) | `obsolescence` | measured J +14% |
| [opik](data/tools/opik.yml) | `incomplete_execution` | measured J +3.6% |
| [pr-agent](data/tools/pr-agent.yml) | `incomplete_execution` | measured J +15% |
| [pr-agent](data/tools/pr-agent.yml) | `security_vulnerability` | measured J +0.1% |
| [promptfoo](data/tools/promptfoo.yml) | `security_vulnerability` | measured J +1.8% |
| [pyright](data/tools/pyright.yml) | `logic_error` | measured J +0.3% |
| [ruff](data/tools/ruff.yml) | `incomplete_execution` | measured J +0.5% |
| [ruff](data/tools/ruff.yml) | `logic_error` | measured J -3.1% |
| [ruff](data/tools/ruff.yml) | `obsolescence` | measured J +7.7% |
| [semgrep](data/tools/semgrep.yml) | `security_vulnerability` | measured J +2.5% |

---

## Method

Each failure mode has a weight (likelihood × impact) in `data/failure_mode_priorities.yml`, which describes its own numbers as: "editorial weights, no empirical calibration". They were set by hand; no likelihood comes from a count of real failures.

Each tool has a **popularity** score: log10(GitHub stars + 1) plus an adjustment for the curated `maturity_status` (stable +0.5, experimental +0.2, at_risk -0.3, deprecated -1.0, abandoned -2.0). It says how widely a tool is used, not how well it works.
Star counts in the tool files date from 2026-11-21 to 2026-11-21.

The three stacks:

- **`minimum`** — the one tool with the largest sum of weights over its tagged modes × (1 + popularity).
- **`optimal`** — three tools picked one after another by the same score, each time counting only modes not yet reached.
- **`full`** — the same greedy pick, continued until no eligible tool adds a mode.

Per failure mode: tools with a measured J at or above the floor come first, highest J first. Then tools with a tag only, in the recommender's order: prevention and detection before correction and recovery, then tools whose rationale text names the mode, then stars.

Measured results: `site/public/bench/results.json`, generated 2026-11-22; 11 catalogue tools have at least one measured row; floor J 25%.

Never listed, whatever their tags: `comfyui` (role too unclear to suggest).

Weight per failure mode (likelihood × impact, descending):

| Failure mode | weight |
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

This file is regenerated from `data/tools/*.yml`, `data/failure_mode_priorities.yml` and the benchmark results by `validator/generate_recommendations.py`.
