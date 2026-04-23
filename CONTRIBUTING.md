# Contributing to SAICA-KG

SAICA-KG is navigational, not evaluative. Contributions extend the graph with well-grounded nodes and crosswalks; they do not rank or endorse tools.

## What a good contribution looks like

- **A new Tool node.** One YAML file under `data/tools/` that validates against `schema/tool.schema.json`, cites at least one paper or primary source in `cited_in`, and has a clear `inclusion_rationale` explaining which previously-unfilled cell in the SAICA-KG facet grid it occupies.
- **A new FailureMode.** Must have ≥1 citation in `prior_work` and ≥1 detection signal. Propose as an RFC issue first — new modes alter the shape of the graph.
- **A new Taxonomy ingestion.** External taxonomies (OWASP, MAST, etc.) are first-class nodes. Add the taxonomy YAML + a Crosswalk YAML mapping its categories into SAICA-KG facets.
- **A new Crosswalk.** Updates to existing crosswalks should cite the external taxonomy version and note what changed.

## How to contribute

1. Fork and branch.
2. Add or edit YAML files under `data/`.
3. Run `python validator/cli.py`. All errors must be clean; address warnings in your PR description if you cannot.
4. Open a PR with (a) the `inclusion_rationale`, (b) any COI disclosure (see below), (c) the external source URLs.
5. A maintainer reviews within two weeks. Routine additions are typically merged; schema or enum changes follow the RFC process in `EDITORIAL_POLICY.md`.

## Conflict-of-interest disclosure

If you author, maintain, or are employed by the organization behind a Tool you are adding, say so explicitly in the PR description. COI does not disqualify a contribution but must be visible.

## Stability commitments

- Node `id` values never change.
- Enum values for `ControlParadigm`, `TemporalPhase`, `AutonomyLevel` do not change across minor versions.
- `FailureMode` ids present at v1.0 are stable; new modes may be added.
- Schema field renames require an RFC and a deprecation period.

## Licensing

- Code contributions are licensed under Apache-2.0.
- Data contributions (YAML under `data/`) are licensed under CC-BY-4.0.

By opening a PR you agree your contributions are licensed under these terms.
