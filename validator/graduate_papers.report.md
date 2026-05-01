# graduate_papers report

- Mode: write
- Limit: 30
- Sources: s2, elicit, candidates
- Candidates loaded: 384
- Eligible after topic filter & dedup: 191
- Accepted: 30
- Skipped (duplicate): 13
- Skipped (schema-invalid): 0

## Accepted papers

| id | year | citations | score | source | failure_modes |
| --- | --- | --- | --- | --- | --- |
| `liu-2025-empirical-study-failures-automated` | 2025 | 5 | 21 | `elicit:Q1` | — |
| `wang-2025-ai-agentic-programming-survey` | 2025 | 17 | 19 | `elicit:Q3` | logic_error |
| `zhang-2025-mcp-security-bench-msb` | 2025 | 10 | 16 | `s2:mcp-evaluation` | security_vulnerability |
| `fan-2025-mcptoolbench-large-scale-ai` | 2025 | 23 | 15 | `s2:mcp-evaluation` | context_pollution |
| `xing-2025-mcp-guard-multi-stage` | 2025 | 10 | 15 | `s2:mcp-evaluation` | security_vulnerability |
| `krishna-2025-importing-phantoms-measuring-llm` | 2025 | 7 | 15 | `s2:package-hallucination-slopsquatting` | supply_chain_attack, fabrication, security_vulnerability |
| `zhang-2025-semanticforge-repository-level-code` | 2025 | 6 | 15 | `s2:code-gen-hallucination-classification` | fabrication |
| `qiu-2026-prbench-end-end-paper` | 2026 | 0 | 15 | `s2:sandboxed-execution-ai-code-agent` | fabrication, logic_error |
| `gao-2026-skillreducer-optimizing-llm-agent` | 2026 | 0 | 15 | `s2:self-debug-reflexion-coding-agent` | logic_error, context_pollution |
| `atri-2025-trustworthy-agentic-ai-balancing` | 2025 | 0 | 15 | `elicit:Q3` | — |
| `krishnan-2025-advancing-multi-agent-systems` | 2025 | 46 | 14 | `s2:mcp-evaluation` | — |
| `piao-2025-agentbay-hybrid-interaction-sandbox` | 2025 | 1 | 14 | `s2:hitl-code-generation` | incomplete_execution |
| `li-2026-security-considerations-artificial-intelligence` | 2026 | 0 | 14 | `s2:sandboxed-execution-ai-code-agent` | security_vulnerability, cascading_failure |
| `haque-2025-secure-suspect-investigating-package` | 2025 | 0 | 14 | `s2:package-hallucination-slopsquatting` | fabrication, supply_chain_attack, dependency_blindness, security_vulnerability |
| `he-2025-automatic-red-teaming-llm` | 2025 | 10 | 13 | `s2:mcp-evaluation` | security_vulnerability, supply_chain_attack |
| `liu-2026-packmonitor-enabling-zero-package` | 2026 | 0 | 13 | `s2:package-hallucination-slopsquatting` | fabrication, dependency_blindness, supply_chain_attack |
| `kota-2025-zero-trust-security-frameworks` | 2025 | 0 | 13 | `s2:mcp-evaluation` | — |
| `li-2025-glue-code-protocols-critical` | 2025 | 13 | 12 | `s2:sandboxed-execution-ai-code-agent` | logic_error, security_vulnerability |
| `ashrafi-2025-enhancing-llm-code-generation` | 2025 | 12 | 12 | `s2:sandboxed-execution-ai-code-agent` | logic_error |
| `gu-2025-retrieve-effective-retrieval-augmented` | 2025 | 11 | 12 | `s2:retrieval-augmented-code-generation` | context_pollution |
| `bhattarai-2025-arcs-agentic-retrieval-augmented` | 2025 | 7 | 12 | `s2:retrieval-augmented-code-generation` | fabrication |
| `liu-2025-code-copycat-conundrum-demystifying` | 2025 | 5 | 12 | `s2:llm-code-failure-taxonomy` | — |
| `horikawa-2025-agentic-refactoring-empirical-study` | 2025 | 5 | 12 | `s2:supervising-ai-coding-agents` | — |
| `santos-2025-decoding-configuration-ai-coding` | 2025 | 5 | 12 | `s2:supervising-ai-coding-agents` | — |
| `li-2025-netmcp-network-aware-model` | 2025 | 4 | 12 | `s2:mcp-evaluation` | — |
| `song-2025-help-hurdle-rethinking-model` | 2025 | 3 | 12 | `s2:mcp-evaluation` | — |
| `twist-2025-library-hallucinations-llms-risk` | 2025 | 2 | 12 | `s2:package-hallucination-slopsquatting` | security_vulnerability, supply_chain_attack, fabrication |
| `ni-2025-viscoder2-building-multi-language` | 2025 | 2 | 12 | `s2:self-debug-reflexion-coding-agent` | logic_error |
| `zhao-2025-hfuzzer-testing-large-language` | 2025 | 1 | 12 | `s2:package-hallucination-slopsquatting` | supply_chain_attack, fabrication, security_vulnerability |
| `bulut-2026-avda-autonomous-vibe-detection` | 2026 | 0 | 12 | `s2:code-reinvention-duplicate-detection-llm` | — |

## Top 20 skipped duplicates

- **Rethinking Autonomy: Preventing Failures in AI-Driven Software Engineering** (2025) — arxiv_id=2508.11824 — score=23
- **Hallucination by Code Generation LLMs: Taxonomy, Benchmarks, Mitigation, and Challenges** (2025) — arxiv_id=2504.20799 — score=15
- **Where Do AI Coding Agents Fail? An Empirical Study of Failed Agentic Pull Requests in GitHub** (2026) — arxiv_id=2601.15195 — score=15
- **Beyond Functional Correctness: Exploring Hallucinations in LLM-Generated Code** (2024) — title=beyond-functional-correctness-exploring-hallucinations-llm-generated-code — score=14
- **LLM Hallucinations in Practical Code Generation: Phenomena, Mechanism, and Mitigation** (2024) — arxiv_id=2409.20550 — score=14
- **MCP-Universe: Benchmarking Large Language Models with Real-World Model Context Protocol Servers** (2025) — arxiv_id=2508.14704 — score=14
- **A Survey on Large Language Models for Code Generation** (2024) — arxiv_id=2406.00515 — score=13
- **We Have a Package for You! A Comprehensive Analysis of Package Hallucinations by Code Generating LLMs** (2024) — title=have-package-you-comprehensive-analysis-package-hallucinations-code-generating-llms — score=13
- **Measuring AI agent autonomy: Towards a scalable approach with code inspection** (2025) — arxiv_id=2502.15212 — score=13
- **PAGENT: Learning to Patch Software Engineering Agents** (2025) — arxiv_id=2506.17772 — score=13
- **Fault-Tolerant Sandboxing for AI Coding Agents: A Transactional Approach to Safe Autonomous Execution** (2025) — arxiv_id=2512.12806 — score=13
- **RIFT: A RubrIc Failure Mode Taxonomy and Automated Diagnostics** (2026) — arxiv_id=2604.01375 — score=13
- **Where LLM Agents Fail and How They can Learn From Failures** (2025) — arxiv_id=2509.25370 — score=12

## Schema-invalid candidates

_None._
