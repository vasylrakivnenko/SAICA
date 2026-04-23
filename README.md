# SAICA-KG

**Supervising AI Coding Agents — Knowledge Graph**

A living, faceted, queryable knowledge graph for the governance of agentic AI coding tools. Paper + GitHub + website + MCP server.

SAICA-KG absorbs existing failure-mode taxonomies for AI coding agents (OWASP Agentic Top 10, MAST, DAPLab 9, Microsoft AIRT) as multi-valued tags, then adds orthogonal **strict partitions** — ControlParadigm × TemporalPhase × AutonomyLevel — that no single existing taxonomy provides. The whole graph is served over MCP so a coding agent can ask *"which supervisors cover OWASP ASI04 at post-generation in graduated-HITL?"* and get a grounded, versioned, cited answer.

Navigational, not evaluative.

## Status

v0.1 in development. Not yet published.

- [Design spec](DESIGN.md) *(coming)*
- [Editorial policy](EDITORIAL_POLICY.md) *(coming)*
- Research synthesis: `research/SYNTHESIS.md`

## Repository layout

```
saica-kg/
├── README.md
├── DESIGN.md
├── EDITORIAL_POLICY.md
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
├── mcp_server/        # Agent-facing MCP tools
└── site/              # Static site generator
```

## License

- Code: Apache-2.0
- Data (KG contents): CC-BY-4.0

## Citation

*Coming with v0.1 arXiv submission.*
