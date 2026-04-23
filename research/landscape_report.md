# SAICA-KG Landscape Report

*Prepared 2026-04-22. Scope: is there already a KG-backed, MCP-served, honest-MECE faceted classification of supervision tools for AI coding agents?*

---

## 1. Map of the space

### A. MCP / agent-tool registries

| Name | URL | What it does | Run by | Last signal |
|---|---|---|---|---|
| Official MCP Registry | https://registry.modelcontextprotocol.io | Canonical metadata registry for MCP servers; OpenAPI spec other registries can implement. ~2,000+ servers as of Mar 2026. | Anthropic + GitHub + Microsoft + PulseMCP, donated to Agentic AI Foundation | Active (Mar 2026) |
| awesome-mcp-servers (punkpeye) | https://github.com/punkpeye/awesome-mcp-servers | Largest community-curated list; 85.4k stars, 5,926 commits, 1,534 contributors. Categorized by functional domain (browser, DB, security, etc.), **not** by supervisory role. | Frank Fiegel (founder of Glama) | Active |
| awesome-mcp-servers (wong2) | https://github.com/wong2/awesome-mcp-servers | Second large curated list | wong2 | Active |
| PulseMCP | https://www.pulsemcp.com | 11,840+ hand-reviewed servers; editorial | Orlie + team | Daily |
| Glama | https://glama.ai | 21,000+ servers, visual previews | Frank Fiegel | Daily |
| Smithery | https://smithery.ai | 7,000+ servers, one-click install, hosted remote servers | Smithery | Active |
| mcp.so / mcpservers.org | https://mcp.so | Open directory, community-contributed | Community | Active |
| MCP Gateway Registry | https://github.com/agentic-community/mcp-gateway-registry | Enterprise MCP gateway + registry with OAuth, discovery, governance | Agentic Community | 2026 |
| AWS Agent Registry (AgentCore) | Bedrock AgentCore | Centralized catalog of agents, tools, MCP servers, skills | AWS | Preview Apr 2026 |
| ToolHive Registry | https://docs.stacklok.com/toolhive | Publish/manage agent skills with namespace isolation | Stacklok | Apr 2026 |
| AgentRegistry | https://github.com/agentregistry-dev/agentregistry | Curated registry for MCP servers + SKILL.md bundles with quality scores | agentregistry-dev | 2026 |
| Knowledge Graph Memory MCP (Anthropic) | https://www.pulsemcp.com/servers/modelcontextprotocol-memory | Reference MCP server that persists entities/relations as agent memory — *not* a classification KG | Anthropic | Active |
| Zep / Graphiti Knowledge Graph MCP | https://help.getzep.com/graphiti/getting-started/mcp-server | Serves a temporal KG over MCP for agent memory | Zep | 2026 |
| Pangea MCP Guardrails | https://pangea.cloud | Proxy that wraps MCP servers with guardrails (prompt-injection, DLP) | Pangea | 2026 |

**Finding:** none of the general registries classify servers by the supervisory role they play. Existing "KG over MCP" work (Zep, Graphiti, Anthropic Memory) serves *runtime agent memory*, not a taxonomy of tools.

### B. Awesome-lists and directories for coding agents / guardrails

- **VoltAgent/awesome-agent-skills** (https://github.com/VoltAgent/awesome-agent-skills) — 1000+ skills for Claude Code / Cursor / Codex / Gemini CLI. Active.
- **VoltAgent/awesome-ai-agent-papers** — 2026 research papers on agents, memory, evaluation, workflows. Active.
- **Shubhamsaboo/awesome-llm-apps** — 100+ RAG + agent apps.
- **caramaschiHG/awesome-ai-agents-2026** — 300+ frameworks & tools, monthly updates; includes EU AI Act compliance section.
- **Prat011/awesome-llm-skills** — Skills for Claude Code / Codex / Gemini CLI.
- **Vvkmnn/awesome-ai-eval** — Curated eval tooling.
- **guardrails-ai/guardrails** and **NVIDIA-NeMo/Guardrails** — Implementation libraries, not directories.
- **LangChain tool registry** — https://docs.langchain.com/oss/python/langchain/guardrails — framework-specific integrations list, no cross-framework taxonomy.

No list positions itself as a *MECE taxonomy* of supervision tools.

### C. Vendor supervision / governance docs

- **Anthropic Claude Code Skills + Skills docs** — progressive-disclosure skills framework, "hundreds in production at Anthropic"; Opus 4.7 adds cybersecurity auto-safeguards via hierarchical summarization.
- **OpenAI Agents SDK** — https://openai.github.io/openai-agents-python/ — supervisor-subagent delegation pattern documented.
- **Google ADK v1.0** — Python/Go/Java/TypeScript, native A2A, supervisor pattern.
- **Microsoft Agent Governance Toolkit** — https://github.com/microsoft/agent-governance-toolkit — runtime security, policy enforcement, zero-trust identity, sandboxing; covers 10/10 OWASP Agentic Top 10; integrates ADK, OpenAI Agents SDK, LangGraph, CrewAI, AutoGen, LlamaIndex. Released **Apr 2, 2026** — freshest vendor-neutral governance layer.
- **AutoGen / Semantic Kernel** — both now have AGT integration.

### D. Evaluation / observability platforms

LangSmith, Langfuse (acquired by ClickHouse early 2026), Braintrust, Arize Phoenix (OpenTelemetry standards), Helicone, HumanLoop, PromptLayer, Confident AI (DeepTeam for red-teaming), Maxim, Splunk AI Agent Monitoring (GA Q1 2026), Grafana 13 AI-app observability. **None of these publish a schema of failure-mode categories as a public classification artifact** — they expose evaluator primitives (LLM-as-judge, deterministic, statistical, human) and let users author their own taxonomies.

### E. Academic / research taxonomies already public

- **Microsoft AI Red Team — Taxonomy of Failure Modes in Agentic AI Systems** (Apr 2025 whitepaper). Novel vs existing split; goal misalignment, boundary violations, memory poisoning, etc. PDF on microsoft.com.
- **OWASP Top 10 for Agentic Applications 2026** (Dec 2025) — ASI01 Goal Hijack through ASI10 Rogue Agents. The most visible formal taxonomy.
- **MAST: Multi-Agent System Failure Taxonomy** (Cemri et al., arXiv:2503.13657, 2025) — 14 failure modes / 3 clusters from 1,600 annotated traces across 7 MAS frameworks.
- **Characterizing Faults in Agentic AI** (arXiv:2603.06847, 2026) — 37 fault categories / 13 major / 5 high-level dimensions.
- **9 Critical Failure Patterns of Coding Agents** — Reya Vir, Columbia DAPLab, Jan 8 2026. Distilled from 15+ apps / 5 SOTA agents (Claude, Cline, Cursor, v0, Replit). **Closest in spirit to SAICA-KG's classification goal**; no KG or MCP behind it.
- **Swiss Cheese Model for AI Safety** (arXiv:2408.02205) — multi-layered runtime guardrails taxonomy, SLR-derived quality attributes + design options.
- **Partnership on AI — Real-Time Failure Detection in AI Agents** (Sep 2025).
- **SCRIBE** (ICLR 2025 workshop, Building Trust) — skill-conditioned RL for tool-using agents with skill-prototype reward modeling.

### F. Recent (2025-2026) launches

- **MCP Dev Summit 2026** — AAIF established, 2026 roadmap on auth, observability, HTTP scaling.
- **Microsoft AGT** — Apr 2 2026 OSS launch.
- **AWS Agent Registry** — Apr 2026 preview.
- **Splunk AI Agent Monitoring** — Q1 2026 GA.
- **Grafana 13 + MCP AI agent** — GrafanaCON 2026.
- **Anthropic Opus 4.7** — Apr 21 2026, cybersecurity guardrails + auto-mode.
- **ClickHouse acquires Langfuse** — early 2026.
- **Hamel Husain + Shreya Shankar** — O'Reilly *Evals for AI Engineers* book + 4,500-alum Maven cohort refreshed Aug 2026.

---

## 2. Direct competitors or overlaps

No project I could find does all three: **KG-backed + MCP-served + honest-MECE classification of supervision tools for coding agents**. Closest overlaps, ranked:

1. **Microsoft Agent Governance Toolkit** (Apr 2026) — *governance runtime*, not a taxonomy/KG. Overlaps on "which supervisory controls exist"; does not enumerate the *landscape* of third-party tools by facet.
2. **OWASP Agentic Top 10 2026** — *risk taxonomy*, not a tool directory. SAICA-KG could ingest this as one facet.
3. **Microsoft Failure Modes whitepaper** + **MAST** + **DAPLab 9 patterns** — failure taxonomies with no registry or KG mapping failures to supervising tools.
4. **AWS Agent Registry / AgentRegistry / ToolHive / MCP Gateway Registry** — centralize discovery of agents/skills/MCP servers; *flat metadata*, not faceted by supervisory role.
5. **punkpeye/awesome-mcp-servers** — categorized by *functional domain* only.
6. **Zep/Graphiti Knowledge Graph MCP** and **Anthropic Memory MCP** — serve KGs over MCP, but for *agent runtime memory*, not classification.

**Gap confirmed.** Nobody is intersecting (supervision tool landscape) × (faceted MECE classification) × (KG serialization) × (MCP surface).

---

## 3. Novel vs duplicative assessment

| SAICA-KG contribution | Verdict | Overlap |
|---|---|---|
| **Honest-MECE faceting of supervision tools** | **Novel.** MECE + faceted is a well-known information-science pattern (Hedden, Sanity.io guides) but has not been applied to the supervision-tool space. Adjacent but non-overlapping: OWASP ASI01-10 and MAST (risk/failure facets, not tool facets); Swiss Cheese Model (guardrail-layer facets, no directory). | OWASP 2026, MAST, Swiss Cheese |
| **Reinvention-as-failure-class** | **Novel in print** as far as I can find. DAPLab's "9 failure patterns" names code-level pathologies but not ecosystem-level reinvention. Microsoft/MAST focus on runtime failure modes. A reinvention facet is defensible as a new lens. | None direct |
| **KG-as-MCP for classification metadata** | **Partially duplicative at the mechanism level, novel at the content level.** Anthropic's Knowledge Graph Memory MCP, Zep/Graphiti, and the Actian data-catalog-over-MCP pattern all serve KGs via MCP — but for runtime memory or enterprise data catalogs. Serving a *curated supervision-tools taxonomy* over MCP is new. | Anthropic KG Memory MCP, Zep, Graphiti, Actian |

---

## 4. Distribution channels (10)

1. **Latent Space** (swyx + Alessio) — AI Engineer newsletter + podcast, 10M+ readers/listeners. Pitch as an episode: "MECE for supervision tools."
2. **Hamel Husain's blog + Maven cohort** (hamel.dev; 25k newsletter; 4.5k course alumni) — directly overlapping audience of eval/supervision practitioners.
3. **Simon Willison's Weblog** (simonwillison.net) — post a TIL; he regularly curates MCP + agent tooling.
4. **AI Engineer World's Fair 2026** (Jun 29–Jul 2 SF) + **AI Engineer Europe** — Evals & Observability track; submit lightning talk or expo.
5. **MLOps Community Slack** (85k members) — #llm-in-production, #agents, #evals channels.
6. **r/LocalLLaMA + r/LLMDevs + Hacker News Show HN** — release the KG + MCP server as an OSS Show HN.
7. **Model Context Protocol Discord + Anthropic Discord** — the MCP spec community is where the official registry conversation happens.
8. **Vanishing Gradients podcast** (Hugo Bowne-Anderson) — guests regularly discuss agent supervision.
9. **OWASP Gen AI Security Project mailing list** — OWASP Agentic Top 10 working group is actively looking for mappings between risks and mitigations/tools.
10. **PulseMCP weekly digest + Glama/Smithery featured listings** — submit SAICA-KG as a featured MCP server; PulseMCP's hand-reviewed queue gives editorial lift.

Bonus: **LangChain blog**, **ZenML newsletter** (Newsletter #11 already focuses on GenAI + MLOps), **DataTalks.Club Slack**, **TWIML Community**.

---

## 5. Potential collaborators / endorsers (8–10)

| Person | Why | Reach |
|---|---|---|
| **Hamel Husain** | Runs #1 evals course; obsessed with honest evaluation schemas; personally writes long FAQs about failure modes. | @hamelhusain on X; hamel@parlance-labs.com; hamel.dev |
| **Shreya Shankar** (UC Berkeley) | Co-author *Evals for AI Engineers*; academic credibility on classification schemas. | sh-reya.com; @sh_reya |
| **Simon Willison** | Prolific MCP + agent tooling curator; a link from him is distribution on its own. | simonwillison.net; @simonw |
| **swyx (Shawn Wang)** | Latent Space; gatekeeper of the AI-engineer narrative. | @swyx; latent.space |
| **Reya Vir** (Columbia DAPLab) | Author of "9 Failure Patterns"; natural academic partner for reinvention-as-failure-class. | daplab.cs.columbia.edu |
| **Frank Fiegel (punkpeye)** | Runs Glama + awesome-mcp-servers; can add a "supervision" category or feature SAICA-KG. | @punkpeye on GitHub/X |
| **Ram Shankar Siva Kumar** (Microsoft AI Red Team) | Lead author of MS failure-modes taxonomy; would endorse cross-walking with SAICA-KG. | LinkedIn; microsoft.com |
| **Sandy Dunn / Rock Lambros** (OWASP Agentic Top 10 co-leads) | Official taxonomy owners; natural crosswalk partners. | genai.owasp.org |
| **Harrison Chase** (LangChain) | LangChain has a guardrails doc but no taxonomy; possible tool-registry alignment. | @hwchase17 |
| **Jerry Liu** (LlamaIndex) | Publicly acknowledges MCP + agent-SDK disruption; looking for new framings. | @jerryjliu0 |

---

## 6. Competitive positioning recommendation

Pitch SAICA-KG as **"the OWASP/ATT&CK for AI-coding-agent supervision"** — the honest MECE map that governance toolkits (Microsoft AGT), risk frameworks (OWASP Agentic Top 10), and tool registries (Official MCP Registry, AWS Agent Registry) all need but none provide. Lead with the *crosswalk* story: SAICA-KG ingests OWASP ASI01-10, MAST's 14 modes, DAPLab's 9 patterns, and Microsoft's failure taxonomy, then maps each to the *tools that actually supervise them* — served live over MCP so any coding agent can ask "which supervisor covers goal-hijack for a Claude Code subagent?" and get a grounded answer. The novelty is the *intersection* (taxonomy × directory × KG × MCP) plus the reinvention-as-failure-class lens, not any single axis.

---

## Sources

- https://registry.modelcontextprotocol.io
- https://modelcontextprotocol.io/registry/about
- https://github.com/punkpeye/awesome-mcp-servers
- https://www.pulsemcp.com
- https://glama.ai
- https://smithery.ai
- https://mcp.so
- https://github.com/agentic-community/mcp-gateway-registry
- https://aws.amazon.com/about-aws/whats-new/2026/04/aws-agent-registry-in-agentcore-preview/
- https://docs.stacklok.com/toolhive/updates/2026/04/06/updates
- https://github.com/agentregistry-dev/agentregistry
- https://help.getzep.com/graphiti/getting-started/mcp-server
- https://github.com/shaneholloman/mcp-knowledge-graph
- https://pangea.cloud/blog/secure-mcp-servers-with-ai-guardrails/
- https://github.com/microsoft/agent-governance-toolkit
- https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit-open-source-runtime-security-for-ai-agents/
- https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
- https://www.microsoft.com/en-us/security/blog/2025/04/24/new-whitepaper-outlines-the-taxonomy-of-failure-modes-in-ai-agents/
- https://arxiv.org/abs/2503.13657
- https://arxiv.org/html/2603.06847v1
- https://daplab.cs.columbia.edu/general/2026/01/08/9-critical-failure-patterns-of-coding-agents.html
- https://arxiv.org/html/2408.02205v3
- https://github.com/VoltAgent/awesome-agent-skills
- https://github.com/VoltAgent/awesome-ai-agent-papers
- https://github.com/caramaschiHG/awesome-ai-agents-2026
- https://github.com/Vvkmnn/awesome-ai-eval
- https://github.com/NVIDIA-NeMo/Guardrails
- https://github.com/guardrails-ai/guardrails
- https://www.latent.space
- https://hamel.dev/blog/posts/evals-faq/
- https://maven.com/parlance-labs/evals
- https://www.sh-reya.com
- https://simonwillison.net/tags/hamel-husain/
- https://www.ai.engineer/worldsfair
- https://mlops.community
- https://www.braintrust.dev/articles/best-llm-tracing-tools-2026
- https://openai.github.io/openai-agents-python/
- https://www.anthropic.com/news/donating-the-model-context-protocol-and-establishing-of-the-agentic-ai-foundation
- https://www.anthropic.com/news/building-safeguards-for-claude
