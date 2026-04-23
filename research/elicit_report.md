# Elicit Systematic Review for SAICA-KG

Run: 2026-04-22. Queries used: 4 / 8 budget. API: `POST https://elicit.com/api/v1/search`, Bearer auth.

## Executive summary (~250 words)

A four-query Elicit sweep over SAICA-KG's motivating questions returned 40 papers, dominated by 2025-26 work directly adjacent to the SAICA-KG thesis. Failure-mode taxonomies for coding agents are a hot, very young literature: five overlapping taxonomies appeared in the last twelve months (Vinay 2025; Zhu 2025 AgentErrorTaxonomy; Liu 2025 SWE-Bench failure study; Shah 2026 agentic-fault taxonomy from 13.6k issues; Microsoft AIRT 2025). None is MECE in the strict-partition sense SAICA-KG proposes; none separates ControlParadigm from TemporalPhase from AutonomyLevel as orthogonal facets. KG-based tool classification exists for ML libraries (MLTaskKG, IEEE TSE 2023), scientific software (Kelley-Garijo 2021), and planning-agent tool retrieval (Bansal 2025), but none targets supervision tools for coding agents. Supervision frameworks (Manheim 2025 oversight-vs-control; Lindner 2025 sync/semi-sync/async monitoring; Cihon 2025 autonomy scoring) supply vocabulary SAICA-KG should adopt but remain conceptual, not cataloged. Faceted classification in SE is well-established (Prieto-Diaz 1987 lineage; Usman 2017 mapping study, 171 cites; Ranganathan revival) but has not been applied to supervision tools for AI coding agents. The gap SAICA-KG fills: a faceted, strictly-partitioned, KG-backed catalog of supervisors that absorbs 2025-26 failure-mode taxonomies as multi-valued FailureMode tags while treating ControlParadigm / TemporalPhase / AutonomyLevel as orthogonal partitions - a combination no paper in the sample does.

## 1. API status

- **Discovery**: `docs.elicit.com` returned 403. Working examples from `github.com/elicit/api-examples` (commit `bf7b5cb`). Base URL `https://elicit.com/api/v1/`, auth `Authorization: Bearer $ELICIT_API_KEY`.
- **Endpoints**: `POST /v1/search` with filters (`typeTags, minYear, maxYear, maxQuartile, pubmedOnly, includeKeywords, excludeKeywords, hasPdf, retracted`); response `{papers:[{elicitId,title,authors,year,abstract,doi,pmid,venue,citedByCount,urls}]}`. Async `POST /v1/reports` + `GET /v1/reports/{id}` (5-15 min polling).
- **Column extraction** (main_claim / method / taxonomy_used / sample_size / relevance) is **not** a separate endpoint; embedded in `/reports`. Fell back to structured synthesis from abstracts.
- **Worked**: all four `/search` calls HTTP 200, 10 papers each, abstracts present for 38/40.
- **Not exercised**: `/reports` (long-running); filtered searches (kept raw per spec).
- **Rate limit / pricing**: undisclosed; docs gated. Next call should capture rate-limit headers.

## 2. Per-question synthesis

### Q1 - Failure-mode taxonomies for AI coding agents / LLM code generation
**Confidence: HIGH.** Ten highly relevant results, almost entirely 2025-26.

1. **Zhu et al. 2025, "Where LLM Agents Fail..."** (arXiv:2509.25370, 22 cites) - **AgentErrorTaxonomy** over memory/reflection/planning/action/system + **AgentErrorBench** dataset. Prime FailureMode seed.
2. **Shah et al. 2026, "Characterizing Faults in Agentic AI"** - 385-fault grounded-theory study, 40 repos, 37 fault types in 13 categories, 12 root causes, 13 symptoms; dev-validated (n=145, 3.97/5). Best empirical grounding.
3. **Liu et al. 2025, "Failures in Automated Issue Solving"** (arXiv:2509.13941) - SWE-Bench-Verified, 150 failures, **3 phases / 9 categories / 25 subcategories**. Matches SAICA-KG's TemporalPhase.
4. **Vinay 2025, "Failure Modes in LLM Systems"** (arXiv:2511.19933) - 15 hidden modes (context-boundary degradation, version drift, cost-driven collapse).
5. **Microsoft AIRT 2025, "Taxonomy of Failure Mode in Agentic AI"** - red-team FMEA; safety vs security, single- vs multi-agent.
6. **Xue-Uddin 2025, "PAGENT"** (arXiv:2506.17772) - 114 unresolved SWE-bench issues, 7 agents, 6-category taxonomy.
7. **Cisco 2025, "Integrated AI Security and Safety Framework"** (arXiv:2512.12921) - unifies MITRE ATLAS / NIST AML / OWASP-LLM / OWASP-Agentic. Crosswalk import.
8. **Navneet-Chandra 2025, "Rethinking Autonomy"** (arXiv:2508.11824) - SAFE-AI; **suggestive/generative/autonomous/destructive** autonomy taxonomy overlaps AutonomyLevel.
9. **Morabito-Wu 2025, "When the Code Autopilot Breaks"** (arXiv:2509.10946) - embedded-ML code gen; silent-fail and compiles-but-breaks modes.
10. **Popchanovska et al. 2026, "Taxonomy of AI Risk Mitigation"** - 9,705 incidents; extends MIT Risk Mitigation Taxonomy with 4 categories.

**Disagreement**: Zhu partitions by module, Liu by phase, Navneet by autonomy intent, Shah by type/symptom/root-cause. **No single taxonomy is MECE**; SAICA-KG's strict-partition claim is defensible.

### Q2 - KGs for tool / library / agent classification and recommendation
**Confidence: MEDIUM-HIGH.**

1. **Liu et al. 2023, "MLTaskKG"** (IEEE TSE, 9 cites) - KG over AI tasks/models/implementations/repos; 92.8% tuple correctness; 47.6% shorter search time. **Closest prior art to SAICA-KG in construction methodology.**
2. **Kelley-Garijo 2021** (Quant. Sci. Stud., 31 cites) - KG from 10k+ scientific-software readmes + browsing layer.
3. **Schindler et al. 2020, "SoftwareKG"** (ESWC, 32 cites) - 133k software mentions from 51k articles; linked to DBpedia / MAKG / Wikidata / Software Ontology.
4. **Bansal et al. 2025** (arXiv:2508.05888) - KG + ego-graph ensembles for tool retrieval; 91.85% vs 89.26% hybrid baseline. **KG-backed tool retrieval beats pure similarity** - supports SAICA-KG's MCP layer.
5. **Ruenin-Choetkiertikul 2024, "TeReKG"** (KBS) - temporal collaborative KG; temporal-facet modeling.

Less direct: Mandal 2024, Mao-Mokhov 2021, Ramazanova 2024.

**Gap**: no entry targets supervision tools for coding agents.

### Q3 - Supervision / monitoring / control of autonomous coding agents
**Confidence: HIGH on vocabulary, MEDIUM on cataloged inventory.**

1. **Manheim-Homewood 2025** (arXiv:2507.03525) - **control = ex-ante/real-time/operational; oversight = ex-post/policy/governance**. Direct vocabulary for TemporalPhase and ControlParadigm.
2. **Lindner et al. 2025** (arXiv:2512.22154) - **sync / semi-sync / async** monitoring protocols; latency/safety tradeoffs.
3. **Cihon-Stein 2025** (arXiv:2502.15212, 11 cites) - static autonomy scoring on **impact + oversight**. Validates AutonomyLevel as statically measurable.
4. **Wang et al. 2025, "Reflection-Driven Control"** (arXiv:2512.21354) - pluggable in-loop reflection module; candidate Tool node.
5. **Wang et al. 2025, "AI Agentic Programming: A Survey"** (arXiv:2508.11126, 17 cites) - taxonomy over planning, context mgmt, tool integration, monitoring.
6. **Bui 2026, "OPENDEV"** - terminal coding agent; dual-agent planner/executor separation; harness-level safety controls as product facet.
7. **Atri 2025, "Trustworthy Agentic AI"** - NIST AI RMF + ISO/IEC 42001 + EU AI Act mapping; policy gate, typed tools, HITL, layered monitors, evidence logs.
8. **Kumar 2025** and **Joshi 2025** - governance catalogs of Credo AI, IBM compliance accelerators, observability platforms.

### Q4 - Faceted / MECE classification for SE tool taxonomies
**Confidence: HIGH on method.** Results skew older - method is settled.

1. **Usman et al. 2017** (Info & Softw Tech, **171 cites**). Canonical taxonomy-construction baseline.
2. **Gujral 2021** - revives Ranganathan's facet/isolate/phase/focus for modern KGs.
3. **Ruble-Sheppard 1987** - foundational faceted SE classification; hybrid boolean+vector retrieval. Prieto-Diaz lineage.
4. **Mendes 2010** and **Brun 2008** - empirical support that faceted beats keyword-only retrieval.
5. **Roongkaew-Prompoon 2013** - SWEBOK as controlled vocabulary spine.
6. **Kaplan-Walter 2021** (EASE) - multi-dim classification over research-object/kind/evidence at statement level; orthogonal-facets pattern.
7. **Pizard-Vallespir 2020** - 3-facet, 60-term SE education taxonomy; empirical construction worth imitating.

**Gap**: none targets AI-coding-agent supervision tools. Method proven on software-reuse catalogs (1987-2010) and SE knowledge (2017-21), but 2025-26 agent-supervision literature has not inherited this discipline.

## 3. Cross-question observations

1. **Temporal phase recurs as a hidden axis.** Liu 2025 (3 phases); Manheim 2025 (ex-ante vs ex-post); Lindner 2025 (sync/semi-sync/async is a latency cut on phase). SAICA-KG's TemporalPhase is convergent with the field.
2. **Autonomy is consistently level-valued, not binary.** Navneet 2025 (suggestive/generative/autonomous/destructive) and Cihon 2025 (impact+oversight scoring) give SAICA-KG AutonomyLevel empirical backing.
3. **ControlParadigm is under-theorized.** Literature mixes policy/governance and operational/control freely; SAICA-KG's strict partition could be a real contribution.
4. **FailureMode needs multi-valued tagging.** Shah 2026's association-rule mining shows failures co-occur (token-mgmt -> auth failure); strict partition would lose signal.
5. **KG tool catalogs exist** for libraries / scientific software / planning-agent tools, but **never for supervisors**. SAICA-KG occupies a clear niche.
6. **Recency signal is strong** - 18/40 papers are 2025, 6/40 are 2026. SAICA-KG enters on rising tide but must version its KG to track fast taxonomy churn.

## 4. Gap analysis - what SAICA-KG can uniquely contribute

1. **First faceted KG catalog of supervision tools for AI coding agents.** 2025-26 taxonomies classify *failures*; governance papers describe *platforms* in prose. No machine-queryable spine exists.
2. **Strict MECE partitions on ControlParadigm / TemporalPhase / AutonomyLevel + multi-valued FailureMode tags** is novel. Every observed taxonomy conflates axes. Defensible on the Usman 2017 / Ranganathan lineage.
3. **Crosswalk-as-a-service via MCP.** MITRE ATLAS, NIST AML, OWASP-LLM/Agentic, EU AI Act refs lack a single queryable mapping; SAICA-KG's MCP endpoint can expose crosswalks as first-class queries.
4. **Continuous taxonomy ingestion.** 2026 papers (Shah, Popchanovska, Joshi) add new fault types monthly. KG absorbs these as FailureMode tag expansions without reshaping partitions.
5. **Autonomy-aware recommendation.** Given Cihon's static autonomy scoring, SAICA-KG can answer "which supervisors fit an agent at AutonomyLevel X in TemporalPhase Y?" - an operation no surveyed paper supports.

## 5. Honest limits - what Elicit could not tell us

- **Product inventory.** Elicit surfaces papers about Credo AI / IBM accelerators but no SKU-level metadata (licensing, language support, supported agent frameworks). Need vendor docs, GitHub metadata, MCP-server registries.
- **MECE-claim validation.** Measuring axis-alignment of the ten Q1 taxonomies against SAICA-KG partitions requires manual full-text review; abstracts are too lossy.
- **Adoption / ground-truth signal.** Whether practitioners use supervision tools along these axes is a survey/interview question, not a paper-search one.
- **Rate-limit / cost envelope.** Docs gated; headers not yet captured. Next call should log them.
- **Column-extraction schema.** Not exercised. A future `/reports` run could populate `main_claim/method/taxonomy_used/sample_size/relevance` for the top ~10 papers at real cost.

## Files

- Raw: `/Users/vasyl/saicakg/research/elicit_raw/Q1.json`, `Q2.json`, `Q3.json`, `Q4.json` (10 papers each).
- Report: `/Users/vasyl/saicakg/research/elicit_report.md`.
- Query budget used: 4 of 8.
