# SAICA-KG

**Supervising AI Coding Agents — Knowledge Graph**

A living, faceted, queryable knowledge graph for the governance of agentic AI coding tools. Paper + GitHub + website.

SAICA-KG absorbs existing failure-mode taxonomies for AI coding agents (OWASP Agentic Top 10, MAST, DAPLab 9, Microsoft AIRT) as multi-valued tags, then adds orthogonal **strict partitions** — ControlParadigm × TemporalPhase × AutonomyLevel — that no single existing taxonomy provides. Queries like *"which supervisors cover OWASP ASI04 at post-generation in graduated-HITL?"* resolve against the graph with explicit citations and crosswalks.

Navigational, not evaluative.

## Status

v0.1 in development. Not yet published.

- [Editorial policy](EDITORIAL_POLICY.md)
- [Contributing](CONTRIBUTING.md)
- Research synthesis: `research/SYNTHESIS.md`

## Repository layout

```
saica-kg/
├── README.md
├── EDITORIAL_POLICY.md
├── CONTRIBUTING.md
├── LICENSE            # Apache-2.0 for code
├── LICENSE-DATA       # CC-BY-4.0 for KG data
├── schema/            # JSON Schemas + enum definitions
├── data/
│   ├── tools/         # Supervision tool nodes
│   ├── failure_modes/ # Supervision-addressable failure classes
│   ├── papers/        # Academic references
│   ├── taxonomies/    # External taxonomies (OWASP, MAST, DAPLab, MSFT...)
│   ├── crosswalks/    # SAICA-KG ↔ external taxonomy mappings
│   ├── incidents/     # Documented failure events
│   ├── organizations/
│   ├── recipes/       # Composition patterns
│   └── techniques/
├── validator/         # Schema + invariant enforcement
└── site/              # Static site (website + JSON API)
```

## Using the KG

Three ways to consume SAICA-KG:

1. **Browse** — the static site at `saica-kg.dev` (coming) renders one page per Tool, FailureMode, Taxonomy, and Recipe, with facet-filtered search.
2. **Programmatic** — the site exposes JSON endpoints (`/api/v1/tools.json`, `/api/v1/failure_modes/<id>.json`, `/api/v1/snapshot.json`) for agents and analysis scripts.
3. **Source** — clone the repo and read the YAML directly. Data under `data/` is CC-BY-4.0.

## License

- Code: Apache-2.0
- Data (KG contents): CC-BY-4.0

## Citation

*Coming with v0.1 arXiv submission.*
