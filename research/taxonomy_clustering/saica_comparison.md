# SAICA-vs-Algorithmic Cluster Comparison

- Manual SAICA FailureModes: **11**
- Text-embedding clusters: **26** (ARI vs SAICA: 0.0766, NMI: 0.3752)
- Tool-bipartite clusters: **7** (ARI vs SAICA: 0.5222, NMI: 0.7353)

## Text-embedding clusters

| cid | size | proposed name | top SAICA mode | coverage % | spread | disagreement |
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

## Tool-bipartite clusters

| cid | size | proposed name | top SAICA mode | coverage % | spread | disagreement |
|----:|----:|:--|:--|----:|----:|:--:|
| -1 | 28 | Tooling, Integration, and Actuation | dependency_blindness | 3.6 | 2 | yes |
| 0 | 29 | Adaptability | __unmapped__ | 100.0 | 0 | yes |
| 1 | 5 | Dependency and Integration Failures | obsolescence | 100.0 | 1 | no |
| 2 | 8 | Context and State Persistence | context_pollution | 100.0 | 1 | no |
| 3 | 8 | Authentication and Credential Issues | security_vulnerability | 100.0 | 1 | no |
| 4 | 10 | Input Interpretation and Logic | logic_error | 70.0 | 3 | yes |
| 5 | 23 | Agent Lifecycle and State | scope_creep | 34.8 | 5 | yes |
| 6 | 10 | Dependency Management | fabrication | 90.0 | 2 | yes |
