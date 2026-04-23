# SAICA-KG Editorial Policy

SAICA-KG is a living reference for supervising AI coding agents. It exists to be cited. That requires governance that is credible, transparent, and resistant to capture by any single vendor.

## Scope

In-scope: supervision tools, supervision techniques, papers, benchmarks, external taxonomies, documented incidents, and composition recipes relevant to the governance of AI coding agents.

Out-of-scope (v0.1): ranking tools, evaluating tool quality on benchmarks we did not run ourselves, endorsement of specific vendors, subjective "best practice" guidance.

## Inclusion criteria

A **Tool** is included if it:
1. Is publicly available (OSS, free tier, or documented commercial API).
2. Addresses at least one failure mode in the SAICA-KG FailureMode set.
3. Fits exactly one cell on each of ControlParadigm, TemporalPhase, and AutonomyLevel (MECE axes) — tools that legitimately span modes must be split into multiple Tool nodes.
4. Cites at least one primary source (paper, documentation, or credible write-up).

A **FailureMode** is included if it:
1. Has at least one citation in the peer-reviewed or credible gray literature.
2. Is distinguishable in the field from existing modes (not a rename).

A **Taxonomy** is ingested if it:
1. Has a named owner (organization or working group).
2. Publishes a stable identifier for each category.
3. Is in active use by a community beyond its authors.

## Review cadence

- **30-day review** for frontier coding agents (`maturity_status: experimental`).
- **180-day review** for stable runtime infrastructure.
- **365-day review** for academic techniques / stable tools.
- Nodes past their review window are auto-flagged `at_risk`.

## Maintainer model

v0.1 — single maintainer-in-chief (Vasyl), plus an advisory board of 3–5 invited reviewers from distinct organizations (target: academic + vendor + community).

v1.0 target — maintainer rotation every 12 months among advisory-board members; a recorded tie-break rule for disputed merges; public logs of merge decisions.

## Conflict-of-interest rules

- Contributors authoring or employed by the organization behind a tool disclose in the PR.
- Maintainers with a COI on a PR recuse from the merge decision and note the recusal in the merge commit.
- No vendor has editorial control over categories that classify their own tools.

## Stability commitments

Citation durability requires stable identifiers. We commit to:

- Node `id` values are immutable once merged.
- Partition enum values (`ControlParadigm`, `TemporalPhase`, `AutonomyLevel`, `MaturityStatus`) do not change across minor versions.
- `FailureMode` ids present at v1.0 are stable; new modes may be added in minor releases.
- Schema field renames require an RFC issue, a 30-day comment period, and a deprecation overlap of at least one minor version.
- The KG is versioned `YYYY.MM` (e.g., `2026.04`). Agents should be able to query pinned versions.

## RFC process

Structural changes (new node type, new partition value, schema field rename or removal, change to enum semantics) require an RFC issue with:
- Motivation
- Proposed change
- Alternatives considered
- Migration plan for existing data

30-day public comment. Merge requires two maintainer approvals + no unresolved objections from the advisory board.

## Removal and deprecation

Nodes are never silently deleted. A removed Tool keeps its node with `maturity_status: abandoned` and, where possible, a `supersedes` pointer to its successor. This preserves citation stability.

## Transparency

All merges are public. Decisions on disputed PRs are recorded in the PR thread. The advisory-board roster is public.
