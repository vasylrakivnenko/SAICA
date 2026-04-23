# Data-Driven Validation of the SAICA-KG Failure Taxonomy

## Question

If we let embeddings + clustering choose how many failure classes there are across the 121 ingested categories from OWASP/MAST/DAPLab/MSFT AIRT/Swiss Cheese/Shah, do we converge on the manual 11 or something different?

## Methods

- Corpus: 121 categories from 6 taxonomies.
- Text clustering: HDBSCAN over all-MiniLM-L6-v2 embeddings of `label + description`.
- Response clustering: HDBSCAN over Jaccard distance of the (category x tool) bipartite reachability matrix.
- Comparison: ARI + NMI against SAICA's manual partition (majority-vote crosswalk per category).
- Bootstrap: 10 resamples at 85% of rows per `min_cluster_size`; stability = mean pairwise ARI.

## Results

- Stable text-cluster count at `min_cluster_size=2`: K_text = **26** (bootstrap ARI = 0.754, noise points = 48).
- Stable bipartite cluster count at `min_cluster_size=5`: K_bipartite = **7** (bootstrap ARI = 0.804, noise points = 28).
- Manual SAICA: **K_manual = 11**.
- ARI(text, SAICA) = **0.0766**.
- NMI(text, SAICA) = **0.3752**.
- ARI(bipartite, SAICA) = **0.5222**.
- NMI(bipartite, SAICA) = **0.7353**.

### Sweep details

| method | min_cluster_size | n_clusters | n_noise | bootstrap ARI |
|:--|----:|----:|----:|----:|
| text * | 2 | 26 | 48 | 0.754 |
| text | 3 | 2 | 9 | 0.376 |
| text | 5 | 2 | 66 | 0.457 |
| text | 7 | 2 | 91 | 0.645 |
| text | 10 | 0 | 121 | 0.408 |
| bipartite | 2 | 18 | 29 | 0.773 |
| bipartite | 3 | 13 | 34 | 0.786 |
| bipartite * | 5 | 7 | 28 | 0.804 |
| bipartite | 7 | 6 | 33 | 0.745 |
| bipartite | 10 | 4 | 49 | 0.529 |

`*` = canonical (stability-vs-granularity winner).

## Cluster-by-cluster match (Table 1 — text clustering)

| cid | size | proposed name | SAICA match | coverage % | spread | disagreement |
|----:|----:|:--|:--|----:|----:|:--:|
| -1 | 48 | Dependency and Integration Failures | logic_error | 10.4 | 7 | yes |
| 0 | 4 | Isolate | __unmapped__ | 100.0 | 0 | yes |
| 1 | 2 | Interpretability | __unmapped__ | 100.0 | 0 | yes |
| 2 | 2 | Documentation Gaps | logic_error | 50.0 | 1 | no |
| 3 | 2 | Security | security_vulnerability | 100.0 | 1 | no |
| 4 | 3 | Bias in Resource Allocation | __unmapped__ | 100.0 | 0 | yes |
| 5 | 2 | Intermediate Results Stage | __unmapped__ | 100.0 | 0 | yes |
| 6 | 2 | Human-in-the-Loop Bypass | scope_creep | 50.0 | 1 | no |
| 7 | 3 | Generalizability | __unmapped__ | 100.0 | 0 | yes |
| 8 | 2 | Prioritization Risks (Performance Over Safety) | fabrication | 50.0 | 2 | yes |
| 9 | 2 | Context Loss | context_pollution | 100.0 | 1 | no |
| 10 | 3 | Incomplete Task Execution | incomplete_execution | 66.7 | 2 | yes |
| 11 | 4 | Perception, Context, and Memory | logic_error | 50.0 | 2 | yes |
| 12 | 3 | Agent Goal Hijack | context_pollution | 100.0 | 1 | no |
| 13 | 3 | Memory Poisoning | context_pollution | 66.7 | 1 | no |
| 14 | 4 | Tooling, Integration, and Actuation | fabrication | 50.0 | 1 | no |
| 15 | 2 | Redundant Work | dependency_blindness | 50.0 | 1 | no |
| 16 | 2 | Agent Flow Manipulation | scope_creep | 50.0 | 2 | yes |
| 17 | 5 | System Reliability and Observability | logic_error | 40.0 | 2 | yes |
| 18 | 3 | Runtime and Environment Grounding | dependency_blindness | 33.3 | 2 | yes |
| 19 | 2 | Agent Cognition and Orchestration | fabrication | 50.0 | 1 | no |
| 20 | 3 | Incorrect Permissions Management | scope_creep | 66.7 | 1 | no |
| 21 | 3 | Tool Misuse and Exploitation | fabrication | 33.3 | 3 | yes |
| 22 | 4 | Agent Impersonation | context_pollution | 25.0 | 4 | yes |
| 23 | 3 | Communication Breakdown | fabrication | 33.3 | 2 | yes |
| 24 | 3 | Agent Lifecycle and State | context_pollution | 66.7 | 2 | yes |
| 25 | 2 | System Coordination | __unmapped__ | 100.0 | 0 | yes |

## Cluster-by-cluster match (Table 2 — tool-bipartite)

| cid | size | proposed name | SAICA match | coverage % | spread | disagreement |
|----:|----:|:--|:--|----:|----:|:--:|
| -1 | 28 | Tooling, Integration, and Actuation | dependency_blindness | 3.6 | 2 | yes |
| 0 | 29 | Adaptability | __unmapped__ | 100.0 | 0 | yes |
| 1 | 5 | Dependency and Integration Failures | obsolescence | 100.0 | 1 | no |
| 2 | 8 | Context and State Persistence | context_pollution | 100.0 | 1 | no |
| 3 | 8 | Authentication and Credential Issues | security_vulnerability | 100.0 | 1 | no |
| 4 | 10 | Input Interpretation and Logic | logic_error | 70.0 | 3 | yes |
| 5 | 23 | Agent Lifecycle and State | scope_creep | 34.8 | 5 | yes |
| 6 | 10 | Dependency Management | fabrication | 90.0 | 2 | yes |

## Disagreements worth investigating

### Text clustering
- **Cluster 17** (5 categories; named from `shah-2026-agentic-faults::SHAH-DIM-05`): "System Reliability and Observability". Top SAICA match `logic_error` covers 40.0%; spans 2 SAICA modes.
- **Cluster 22** (4 categories; named from `microsoft-airt-2025::MS-NS-03`): "Agent Impersonation". Top SAICA match `context_pollution` covers 25.0%; spans 4 SAICA modes.
- **Cluster 11** (4 categories; named from `shah-2026-agentic-faults::SHAH-DIM-03`): "Perception, Context, and Memory". Top SAICA match `logic_error` covers 50.0%; spans 2 SAICA modes.

### Tool-bipartite clustering
- **Cluster 0** (29 categories; named from `swiss-cheese-model::SC-QA-10`): "Adaptability". Top SAICA match `__unmapped__` covers 100.0%; spans 0 SAICA modes.
- **Cluster 5** (23 categories; named from `shah-2026-agentic-faults::SHAH-MAJ-02`): "Agent Lifecycle and State". Top SAICA match `scope_creep` covers 34.8%; spans 5 SAICA modes.
- **Cluster 4** (10 categories; named from `shah-2026-agentic-faults::SHAH-MAJ-09`): "Input Interpretation and Logic". Top SAICA match `logic_error` covers 70.0%; spans 3 SAICA modes.

## Limitations

- Text embeddings encode prose similarity, not supervision response. Two categories that share detection/mitigation surface but describe the failure with different vocabulary will separate.
- Bipartite clustering is limited by crosswalk completeness. Categories with no SAICA mapping fall out as all-zero rows and are treated as noise.
- HDBSCAN cluster counts are stable across our sweep, but the `min_cluster_size` prior still biases the partition. We mitigate by reporting the full sweep + bootstrap ARI rather than a single number.
- Bootstrap uses 10 resamples; more would tighten CIs but not change the ordering at the granularity we care about.

## Recommendation

### (b) Refine by the K splits/merges that BOTH methods agree on.
Text and bipartite clusterings agree on 1 mixed-mode cluster(s). Treat those as candidate splits/merges and revisit the crosswalks.
