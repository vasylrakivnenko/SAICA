# SAICA-KG editorial policy

SAICA-KG is the catalog behind SAICA-Bench: failure modes of AI coding
agents, the supervision tools that say they address them, and the papers,
incidents, external taxonomies and recipes around them. This file says
what goes into the catalog and how it is kept. It describes what is done
today, not a plan.

## What the catalog claims, and what it does not

- A failure-mode tag on a tool means the tool's own documentation says it
  addresses that failure. It is a claim, not a measurement.
- Whether a tool catches a failure is measured by SAICA-Bench, for the
  tools and modes it ran. Tools **are** ranked there, by measured J within
  one failure mode. Where a measurement exists, the generated
  recommendations show it, and a tool is not recommended for a mode where
  it measured below J 25%.
- The recommendation lists are otherwise ordered by editorial weights per
  failure mode (`data/failure_mode_priorities.yml`: no empirical
  calibration) and by popularity (mostly GitHub stars). The activity band
  A–F on a tool describes stars, a recent upstream push and integration
  surfaces. None of these is a level of evidence.

## How the content is written

Most files were drafted by an LLM or a coding agent and then edited by the
maintainer; fields were not reviewed one by one. About half of the paper
records were written by a script from Semantic Scholar data. Records say
how they were made where the schema has a field for it (`provenance` on
papers, `review_state` on crosswalks, `kind` on incidents). All six
crosswalks are `llm_drafted_unreviewed`: no person has reviewed a mapping.
The category names of the six external taxonomies were checked against
the published sources on 2026-11-21.

Corrections are welcome and are the normal way the catalog improves; see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## What goes in

A **tool** is included if it:

1. is publicly available (open source, free tier, or a documented
   commercial product);
2. says it addresses at least one of the catalog's failure modes;
3. has one value on each facet (control paradigm, temporal phase, autonomy
   level, implementation). A tool that spans several values gets the one
   for its main use; it is not split into several nodes;
4. links to its repository or documentation. A paper in `cited_in` is
   wanted but not required; most tools have none today.

A **failure mode** needs a definition and at least one source. The 11
modes are overlapping tags: one failure can carry several of them, and the
catalog does not claim that they are mutually exclusive or complete.

An **external taxonomy** is included when it has a named owner and a
published source. Where the source gives its categories no identifiers,
the ids in our file are ours.

An **incident** record must say what kind it is (an event, a study, a
hypothetical case) and must be supported by the source it cites.

## Keeping it current

There is no scheduled review. Tool files carry the dates of their last
checks (`last_reviewed`, `stars_updated_at`, `upstream_pushed_at`); many
were last checked in April 2026. The gate (`validator/cli.py`) checks
structure and cross-references on every change; it does not check that a
description is true.

## Removal

Nodes can be removed: a tool that no longer fits, a duplicate, a record
that turned out to be wrong.

- Every node removed from 2026-11-21 on gets an entry in
  [`data/TOMBSTONES.yml`](data/TOMBSTONES.yml): id, kind, date, reason, and
  a successor if there is one. The manifest step refuses to drop an id
  that has no entry.
- Retracted records are kept, with the reason, under
  [`archive/retracted-incidents/`](archive/retracted-incidents/).
- Removals before that date (75 tools, 6 recipes and 1 paper, counted in
  the review of 2026-11-21) have no tombstone. They are in the git history:
  `git log --diff-filter=D --name-only -- data/`.

## What stays stable

- A node `id` is not reused for a different node.
- The 11 failure-mode ids.
- The catalog carries a version `YYYY.MM` in `data/MANIFEST.json`. There
  are no tagged releases yet, so a past version can only be reached
  through the git history.

Facet values, tags and descriptions change when they are found to be
wrong. Schema fields are added as optional fields; a rename or removal is
announced in the pull request that makes it.

## Who decides

One maintainer (Vasyl Rakivnenko). There is no advisory board and no
formal RFC process. For a structural change (a new failure mode, a new
node type, a schema rename), open an issue first.

## Conflicts of interest

- A contributor who authors, maintains or is employed by the organization
  behind a tool says so in the pull request or issue.
- No vendor decides how its own tool is classified or how its benchmark
  row is produced. A vendor can ask for a correction or a different
  configuration through an issue; the request and the answer are public.
- The benchmark's tool rows were run with settings chosen by this project.
  Tool authors have not reviewed them.

## Transparency

Every change is in the repository history. Results of the benchmark are
versioned ([`bench/CHANGELOG_RESULTS.md`](bench/CHANGELOG_RESULTS.md)).
