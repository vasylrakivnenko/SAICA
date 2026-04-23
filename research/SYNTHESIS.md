# SAICA-KG — Research Synthesis and Sharpened Angle

*2026-04-22. Synthesizes three parallel research agents: Semantic Scholar (341 papers), Elicit (40 papers across 4 systematic queries), Industry landscape (registries, vendor docs, awesome-lists).*

---

## 1. Verdict

**The gap is real and specifically shaped.** No project combines all four of:
(a) faceted-MECE classification
(b) supervision-tool directory
(c) KG backend
(d) MCP surface

Adjacent work exists in every single one of those four cells, but nobody has the intersection. That intersection *is* SAICA-KG.

Even better news: the 2025-2026 literature has exploded with *convergent* vocabulary for our exact three partition axes, which validates the framing without stealing the slot:

| SAICA-KG axis | External validation |
|---|---|
| **TemporalPhase** | Liu 2025 (3 phases on SWE-Bench-Verified), Manheim-Homewood 2025 (ex-ante / real-time / ex-post), Lindner 2025 (sync / semi-sync / async). |
| **AutonomyLevel** | Navneet-Chandra 2025 (suggestive / generative / autonomous / destructive), Cihon-Stein 2025 (static autonomy scoring on impact + oversight). |
| **ControlParadigm** | *Under-theorized.* Existing literature mixes governance and operational control freely. This is where SAICA-KG's strict partition adds the most. |
| **FailureMode** | Five overlapping taxonomies in 12 months: Zhu 2025 AgentErrorTaxonomy, Shah 2026 (385-fault grounded-theory), Liu 2025 SWE-Bench, Microsoft AIRT 2025, Vinay 2025. All conflate axes; none is MECE in the strict sense. |

---

## 2. The sharpened pitch

**"The OWASP/ATT&CK for AI-coding-agent supervision."**

SAICA-KG is the live crosswalk that:
- **Absorbs** existing failure-mode taxonomies (OWASP Agentic Top 10 2026, MAST's 14 modes, DAPLab's 9 patterns, Microsoft AIRT 2025, Swiss Cheese Model, Shah 2026) as multi-valued `FailureMode` tags.
- **Adds** orthogonal strict partitions (ControlParadigm × TemporalPhase × AutonomyLevel) that existing taxonomies lack.
- **Serves** the whole graph over MCP so that coding agents query it at runtime.
- **Lets an agent ask** things like: *"Which supervisors cover OWASP ASI04 at post-generation in graduated-HITL mode?"* and get a grounded, versioned, cited answer.

The reframe: SAICA-KG doesn't compete with OWASP / MAST / DAPLab / Microsoft — it **unifies and indexes** them. That's a much stronger position than "another taxonomy."

---

## 3. Three novelty slots, ranked by defensibility

1. **Crosswalk-as-MCP-service** (strongest). Verifiable artifact, absent from the 341-paper + 40-paper corpus, bridges supervision-taxonomy + MCP literatures. Microsoft AGT, AWS Agent Registry, Zep/Graphiti all occupy *parts* of this but none serves a curated supervision-tools taxonomy over MCP.
2. **ControlParadigm as a strict partition** (newly upgraded by research). Prior work has TemporalPhase and AutonomyLevel; ControlParadigm (prevention/detection/correction/recovery) as a formal strict partition is genuinely untrodden in the surveyed literature.
3. **Reinvention-as-failure-class** (novel in print). Liu 2025 "Code Copycat" studies intra-generation repetition, not cross-codebase reimplementation. DAPLab's 9 patterns don't include it. Defensible if paired with a small empirical prevalence study.
4. **Honest-MECE faceting** (methodology, not lead claim). Well-grounded in Usman 2017 (171 cites), Prieto-Diaz 1987, Ranganathan revival (Gujral 2021). Weakest stand-alone but *enables* 1-3. Frame it as "the methodology that makes the crosswalk work."

---

## 4. What to build v0.1 — revised architecture

### Additions to the original spec

- **`Taxonomy` node type** — first-class nodes for OWASP Agentic Top 10, MAST, DAPLab 9, Microsoft AIRT 2025, Swiss Cheese Model, Shah 2026. Each node has: owner, version, URL, last_updated, category list, license.
- **`Crosswalk` edge type** — maps `SAICA-KG FailureMode` ↔ `Taxonomy.category`. Bidirectional, versioned, with authoring confidence.
- **`belongs_to_taxonomy`** edge from external FailureMode-equivalents to a Taxonomy node.

### Trimmed from the spec

- **MCP surface: 3 tools, not 8.**
  1. `search_supervision_tools(facets)` — faceted filter
  2. `explain_failure_mode_crosswalk(mode_id)` — SAICA-KG definition + all crosswalks to external taxonomies + detection signals + mitigating tools
  3. `get_kg_snapshot(version?)` — full graph JSON at a pinned version (supports citation-durability)
- **Drop Benchmark node type from v0.1** (defer to v0.2 until citation policy is set).
- **Drop `recommend_for_context` free-text endpoint** until a ranking function is defined.

### Empirical back-test (paper's experimental section)

Take Shah 2026's 385-fault corpus (grounded theory, 40 repos) or Liu 2025's SWE-Bench-Verified 150-failure corpus. Classify each fault using SAICA-KG facets with a second coder. Report Cohen's kappa. Show that SAICA-KG enables queries ("which supervisor at which phase could have prevented this?") that flat taxonomies do not support. This is what neutralizes the "just Ranganathan rebadged" reviewer attack.

### Optional rename: "Reinvention" → "Dependency Blindness"

"Reinvention" is evocative but overloaded (Liu 2025 "Code Copycat" is adjacent but different). **"Dependency Blindness"** names the specific failure — the agent fails to see code that already exists in declared dependencies or stdlib — and is a cleaner flag to plant. Not locked; defer to you.

---

## 5. Seed corpus v0.1 (adjusted)

- **Tools (25):** per original spec.
- **FailureModes (8):** per original spec, but each carries explicit crosswalks to external taxonomies.
- **Papers (23):** must-cite list from S2 synthesis — Liu 2024 TSE, Tian 2024 CodeHalu, Zhang-Wang-Shi-Ma 2024, Lee 2025, Jiang 2024 (837 cit umbrella), Spracklen 2024, Williams 2025, Liu 2025 Code Copycat, Ehsani 2026, Wang 2024 ICSE, Misra 2025 GitChameleon, Xu 2025 CKGFuzzer, Farshidi 2025, Luo 2025 MCP-Universe, Fan 2025 MCPToolBench++, Yan 2025, Kumar 2026 AgentForge, Kang 2025 AutoCodeSherpa, Piao 2025 AgentBay, Qi 2026 RIFT, Zhu 2025, Shah 2026, Manheim 2025, Lindner 2025, Cihon 2025, Navneet 2025, Usman 2017 (methodology), MLTaskKG Liu 2023.
- **Taxonomies (6):** OWASP Agentic Top 10 2026, MAST (Cemri 2025), DAPLab 9 Patterns, Microsoft AIRT 2025, Swiss Cheese Model, Shah 2026.
- **Crosswalks:** OWASP↔SAICA, MAST↔SAICA, DAPLab↔SAICA, MSFT↔SAICA, Swiss↔SAICA.
- **Recipes (5):** per original spec.
- **Incidents (~10):** seeded from Spracklen slopsquatting cases + a handful of GitHub-issue-sourced examples.

---

## 6. Distribution plan (from landscape agent)

**Tier 1 (week of arXiv post):**
- Latent Space (swyx) — pitch a "MECE for supervision tools" episode
- Simon Willison's Weblog — link + 2-paragraph writeup
- Hamel Husain (eval newsletter, 25k subs; Maven cohort 4.5k alumni)
- Show HN
- MCP Discord + Anthropic Discord announce channel
- PulseMCP featured listing

**Tier 2:**
- AI Engineer World's Fair 2026 (Jun 29–Jul 2, SF) — lightning talk submission
- MLOps Community Slack (#agents, #evals)
- OWASP Gen AI Security Project mailing list — propose crosswalk collaboration
- Vanishing Gradients podcast

**Tier 3:**
- FAccT / LLM4Code workshop submission
- arXiv preprint first, then workshop

---

## 7. Co-author / endorser shortlist

**Top 3 to approach:**
1. **Reya Vir** (Columbia DAPLab) — author of "9 Critical Failure Patterns"; closest content overlap; natural co-author for reinvention-as-failure-class and the empirical back-test.
2. **Hamel Husain** (Parlance Labs) — distribution + eval-community legitimacy; could be an advisor/endorser rather than co-author.
3. **Ram Shankar Siva Kumar** (Microsoft AI Red Team) — lead on MSFT AIRT taxonomy; natural crosswalk partner.

**Secondary endorsers:** Shreya Shankar (UC Berkeley, Evals book), Ziyang Luo (Salesforce, MCP-Universe), Chong Wang (NTU/SMU, obsolescence), Laurie Williams (NC State, supply-chain survey), Paul Groth (U Amsterdam, KG+LLM senior).

---

## 8. Timeline (realistic)

| Week | Deliverable |
|---|---|
| **1** | JSON schemas + validator + 10 tools + 4 failure modes + 2 taxonomies (OWASP, MAST) + crosswalks + GitHub repo initialized + .env loaded + gitignored |
| **2** | MCP skeleton (3 tools) + full seed corpus (25 tools, 8 modes, 5 taxonomies, ~40 papers) + static site bootstrap (Astro) + llms.txt |
| **3** | Empirical back-test (classify Shah 2026 385-fault corpus with SAICA-KG facets + Cohen's kappa) + paper draft §1–§3 |
| **4** | Paper draft complete + arXiv submission + DOI (Zenodo) + website deploy |
| **Month 2** | Launch (HN, Latent Space, newsletters) + workshop submission (LLM4Code or AIES) + co-author outreach |

---

## 9. Three calls I need a nod on before I go deep

1. **Reposition to "crosswalk-first" framing?** i.e., lead the paper with "SAICA-KG unifies existing taxonomies via honest-MECE facets served over MCP" rather than "SAICA-KG is a new taxonomy." This changes the paper thesis and the README pitch.
2. **Add `Taxonomy` + `Crosswalk` as first-class node/edge types?** Affects schemas and data dir layout.
3. **Rename "Reinvention" → "Dependency Blindness" (or something cleaner)?** Or keep Reinvention and just tighten the definition to distinguish from Liu 2025 Code Copycat?

I'll continue on the unambiguous foundation work (JSON schemas, enum definitions, validator skeleton) while you consider these.
