# Embedding drift report — 2026-04-23

Each row below is a tool whose text embedding sits far from the centroid of its labeled `(control_paradigm, temporal_phase, autonomy_level)` cell. High distance is a **signal for human review**, not a verdict — embeddings are noisy and tool descriptions vary in verbosity.

| # | tool | current cell | distance | nearest alt cell | alt distance |
|---|------|--------------|---------:|------------------|-------------:|
| 1 | `pydantic-ai` | `detection × post_generation × fully_autonomous` | 0.3462 | `prevention × in_generation × fully_autonomous` | 0.3817 |
| 2 | `confident-ai-deepteam` | `detection × post_generation × fully_autonomous` | 0.3449 | `detection × pre_generation × fully_autonomous` | 0.3576 |
| 3 | `smolagents` | `detection × post_generation × fully_autonomous` | 0.3385 | `prevention × pre_generation × graduated_hitl` | 0.3638 |
| 4 | `instructor` | `detection × post_generation × fully_autonomous` | 0.3339 | `prevention × in_generation × fully_autonomous` | 0.4452 |
| 5 | `semgrep` | `detection × post_generation × fully_autonomous` | 0.3149 | `prevention × pre_generation × graduated_hitl` | 0.4120 |
| 6 | `tree-sitter` | `prevention × pre_generation × fully_autonomous` | 0.3139 | `detection × post_generation × fully_autonomous` | 0.3528 |
| 7 | `snyk` | `detection × post_generation × fully_autonomous` | 0.3094 | `detection × pre_generation × fully_autonomous` | 0.3252 |
| 8 | `helicone` | `detection × post_generation × fully_autonomous` | 0.3084 | `detection × post_generation × graduated_hitl` | 0.4259 |
| 9 | `outlines` | `prevention × in_generation × fully_autonomous` | 0.2932 | `detection × post_generation × fully_autonomous` | 0.3304 |
| 10 | `v0` | `prevention × pre_generation × graduated_hitl` | 0.2881 | `prevention × pre_generation × fully_autonomous` | 0.3753 |
| 11 | `langkit` | `detection × post_generation × fully_autonomous` | 0.2863 | `detection × pre_generation × fully_autonomous` | 0.4222 |
| 12 | `trulens` | `detection × post_generation × graduated_hitl` | 0.2687 | `detection × post_generation × fully_autonomous` | 0.2790 |
| 13 | `guidance` | `prevention × in_generation × fully_autonomous` | 0.2642 | `detection × post_generation × fully_autonomous` | 0.3873 |
| 14 | `socket` | `detection × pre_generation × fully_autonomous` | 0.2600 | `detection × post_generation × fully_autonomous` | 0.3544 |
| 15 | `guardrails-ai` | `detection × post_generation × fully_autonomous` | 0.2597 | `prevention × in_generation × fully_autonomous` | 0.2456 |
| 16 | `context-hub` | `prevention × pre_generation × fully_autonomous` | 0.2520 | `prevention × pre_generation × graduated_hitl` | 0.3336 |
| 17 | `nono` | `prevention × in_generation × fully_autonomous` | 0.2509 | `recovery × post_generation × fully_autonomous` | 0.2281 |
| 18 | `sourcegraph-cody` | `prevention × pre_generation × graduated_hitl` | 0.2419 | `prevention × pre_generation × fully_autonomous` | 0.3069 |
| 19 | `nemo-guardrails` | `detection × post_generation × fully_autonomous` | 0.2416 | `prevention × in_generation × fully_autonomous` | 0.3153 |
| 20 | `cordum` | `prevention × pre_generation × graduated_hitl` | 0.2409 | `prevention × pre_generation × fully_autonomous` | 0.3420 |

## Detail

### 1. `pydantic-ai`

- **current cell**: `detection × post_generation × fully_autonomous`
- **distance from own centroid**: 0.3462
- **nearest alternative cell**: `prevention × in_generation × fully_autonomous` (distance 0.3817)
- **top-3 embedding-similar tools**: `instructor` (0.760), `guardrails-ai` (0.655), `outlines` (0.612)

### 2. `confident-ai-deepteam`

- **current cell**: `detection × post_generation × fully_autonomous`
- **distance from own centroid**: 0.3449
- **nearest alternative cell**: `detection × pre_generation × fully_autonomous` (distance 0.3576)
- **top-3 embedding-similar tools**: `rebuff` (0.617), `deepeval` (0.591), `daytona` (0.587)

### 3. `smolagents`

- **current cell**: `detection × post_generation × fully_autonomous`
- **distance from own centroid**: 0.3385
- **nearest alternative cell**: `prevention × pre_generation × graduated_hitl` (distance 0.3638)
- **top-3 embedding-similar tools**: `crewai` (0.588), `replit-agent` (0.575), `swe-agent` (0.565)

### 4. `instructor`

- **current cell**: `detection × post_generation × fully_autonomous`
- **distance from own centroid**: 0.3339
- **nearest alternative cell**: `prevention × in_generation × fully_autonomous` (distance 0.4452)
- **top-3 embedding-similar tools**: `pydantic-ai` (0.760), `outlines` (0.708), `guardrails-ai` (0.667)

### 5. `semgrep`

- **current cell**: `detection × post_generation × fully_autonomous`
- **distance from own centroid**: 0.3149
- **nearest alternative cell**: `prevention × pre_generation × graduated_hitl` (distance 0.4120)
- **top-3 embedding-similar tools**: `tree-sitter` (0.731), `sourcegraph-cody` (0.590), `cursor` (0.565)

### 6. `tree-sitter`

- **current cell**: `prevention × pre_generation × fully_autonomous`
- **distance from own centroid**: 0.3139
- **nearest alternative cell**: `detection × post_generation × fully_autonomous` (distance 0.3528)
- **top-3 embedding-similar tools**: `semgrep` (0.731), `sourcegraph-cody` (0.647), `cursor` (0.582)

### 7. `snyk`

- **current cell**: `detection × post_generation × fully_autonomous`
- **distance from own centroid**: 0.3094
- **nearest alternative cell**: `detection × pre_generation × fully_autonomous` (distance 0.3252)
- **top-3 embedding-similar tools**: `socket` (0.697), `langfuse` (0.586), `dependabot` (0.571)

### 8. `helicone`

- **current cell**: `detection × post_generation × fully_autonomous`
- **distance from own centroid**: 0.3084
- **nearest alternative cell**: `detection × post_generation × graduated_hitl` (distance 0.4259)
- **top-3 embedding-similar tools**: `langfuse` (0.699), `braintrust` (0.599), `arize-phoenix` (0.585)

### 9. `outlines`

- **current cell**: `prevention × in_generation × fully_autonomous`
- **distance from own centroid**: 0.2932
- **nearest alternative cell**: `detection × post_generation × fully_autonomous` (distance 0.3304)
- **top-3 embedding-similar tools**: `guidance` (0.727), `guardrails-ai` (0.712), `instructor` (0.708)

### 10. `v0`

- **current cell**: `prevention × pre_generation × graduated_hitl`
- **distance from own centroid**: 0.2881
- **nearest alternative cell**: `prevention × pre_generation × fully_autonomous` (distance 0.3753)
- **top-3 embedding-similar tools**: `cursor` (0.610), `zed-agent` (0.592), `sourcegraph-cody` (0.540)

### 11. `langkit`

- **current cell**: `detection × post_generation × fully_autonomous`
- **distance from own centroid**: 0.2863
- **nearest alternative cell**: `detection × pre_generation × fully_autonomous` (distance 0.4222)
- **top-3 embedding-similar tools**: `langfuse` (0.671), `langsmith` (0.632), `arize-phoenix` (0.617)

### 12. `trulens`

- **current cell**: `detection × post_generation × graduated_hitl`
- **distance from own centroid**: 0.2687
- **nearest alternative cell**: `detection × post_generation × fully_autonomous` (distance 0.2790)
- **top-3 embedding-similar tools**: `deepeval` (0.708), `langsmith` (0.676), `arize-phoenix` (0.656)

### 13. `guidance`

- **current cell**: `prevention × in_generation × fully_autonomous`
- **distance from own centroid**: 0.2642
- **nearest alternative cell**: `detection × post_generation × fully_autonomous` (distance 0.3873)
- **top-3 embedding-similar tools**: `outlines` (0.727), `guardrails-ai` (0.622), `instructor` (0.611)

### 14. `socket`

- **current cell**: `detection × pre_generation × fully_autonomous`
- **distance from own centroid**: 0.2600
- **nearest alternative cell**: `detection × post_generation × fully_autonomous` (distance 0.3544)
- **top-3 embedding-similar tools**: `snyk` (0.697), `dependabot` (0.600), `pipelock` (0.553)

### 15. `guardrails-ai`

- **current cell**: `detection × post_generation × fully_autonomous`
- **distance from own centroid**: 0.2597
- **nearest alternative cell**: `prevention × in_generation × fully_autonomous` (distance 0.2456)
- **top-3 embedding-similar tools**: `outlines` (0.712), `instructor` (0.667), `pydantic-ai` (0.655)

### 16. `context-hub`

- **current cell**: `prevention × pre_generation × fully_autonomous`
- **distance from own centroid**: 0.2520
- **nearest alternative cell**: `prevention × pre_generation × graduated_hitl` (distance 0.3336)
- **top-3 embedding-similar tools**: `sourcegraph-cody` (0.649), `cursor` (0.620), `continue-dev` (0.547)

### 17. `nono`

- **current cell**: `prevention × in_generation × fully_autonomous`
- **distance from own centroid**: 0.2509
- **nearest alternative cell**: `recovery × post_generation × fully_autonomous` (distance 0.2281)
- **top-3 embedding-similar tools**: `modal` (0.755), `daytona` (0.752), `openhands` (0.707)

### 18. `sourcegraph-cody`

- **current cell**: `prevention × pre_generation × graduated_hitl`
- **distance from own centroid**: 0.2419
- **nearest alternative cell**: `prevention × pre_generation × fully_autonomous` (distance 0.3069)
- **top-3 embedding-similar tools**: `windsurf` (0.661), `continue-dev` (0.654), `context-hub` (0.649)

### 19. `nemo-guardrails`

- **current cell**: `detection × post_generation × fully_autonomous`
- **distance from own centroid**: 0.2416
- **nearest alternative cell**: `prevention × in_generation × fully_autonomous` (distance 0.3153)
- **top-3 embedding-similar tools**: `langfuse` (0.642), `guardrails-ai` (0.605), `arize-phoenix` (0.605)

### 20. `cordum`

- **current cell**: `prevention × pre_generation × graduated_hitl`
- **distance from own centroid**: 0.2409
- **nearest alternative cell**: `prevention × pre_generation × fully_autonomous` (distance 0.3420)
- **top-3 embedding-similar tools**: `cline` (0.641), `swe-agent` (0.629), `crewai` (0.627)
