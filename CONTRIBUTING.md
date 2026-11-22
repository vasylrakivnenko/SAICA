# Contributing to SAICA-Bench and SAICA-KG

SAICA-Bench is the benchmark; SAICA-KG is its catalog. The benchmark ranks
reviewers (tools and models) by a measured score, J = TPR − FPR, within one
failure mode. The catalog lists tools and what they say they address; a tag
in the catalog is a claim, not a measurement.

You can contribute to either. The rules for what belongs in the catalog are
in [`EDITORIAL_POLICY.md`](EDITORIAL_POLICY.md).

## Set up

Python 3.12 or newer. From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements/dev.txt -c requirements/constraints.txt
```

The catalog gate alone needs less:
`.venv/bin/pip install -r requirements/kg.txt -c requirements/constraints.txt`.
The other commands (tests, the site, the generated files) are in the
"Development" section of [`README.md`](README.md).

## Catalog contributions (`data/`)

- **A new tool.** One file `data/tools/<id>.yml` that passes the gate. Say
  where the facts come from: a `documentation_url` or a `repository_url` at
  least, and a paper in `cited_in` if one exists (most tools in the catalog
  have none today, and the gate only warns about it). Tag a failure mode
  only if the tool's own documentation says it addresses it.
- **A correction.** Wrong facet, dead link, tool archived upstream, a tag
  the tool does not support: change the file and give the source in the
  pull request.
- **A removal.** Delete the file and add an entry for the id to
  [`data/TOMBSTONES.yml`](data/TOMBSTONES.yml) (id, kind, date, reason,
  successor if there is one). The manifest step refuses to drop an id that
  has no tombstone.
- **A new failure mode, taxonomy or crosswalk.** Open an issue first; these
  change the shape of the catalog. A crosswalk must name the version of the
  external taxonomy it maps and use the category names the source uses.
  State how the mapping was made (`review_state`).

Steps:

1. Fork and branch.
2. Add or edit YAML files under `data/`.
3. Run `.venv/bin/python validator/cli.py` until it reports 0 errors. Explain
   in the pull request any warning you could not remove. Useful options:
   `--data-dir`, `--manifest`, `--arxiv --offline` (paper titles and first
   authors against the tracked arXiv records), `--links` (needs network).
4. Regenerate the files built from `data/`, in this order, and commit them
   with your change:

   ```bash
   .venv/bin/python -m validator.generate_schemas
   .venv/bin/python -m validator.generate_manifest
   .venv/bin/python -m validator.generate_maturity
   .venv/bin/python -m validator.generate_recommendations
   .venv/bin/python -m validator.generate_skills
   ```

5. Open a pull request with the sources you used and any conflict of
   interest (see below).

## Benchmark contributions

- **A wrong number, or a run of your tool you do not recognise.** Open an
  issue. Say which row of which failure mode, and what you expected. Tool
  rows were produced with settings chosen by this project; if your tool
  should be configured differently, say how.
- **A tool to benchmark.** Open an issue with the tool, the failure mode it
  is built for, and how to run it without an account if that is possible.
- **Code under `bench/`.** Scoring lives in `bench/common.py`; every
  mode's `score.py` uses it. Run `.venv/bin/python -m pytest bench/tests -q`
  and `.venv/bin/python bench/build_report.py --check` before a pull
  request. Published results are versioned: a change that moves a number
  needs a new version and a line in
  [`bench/CHANGELOG_RESULTS.md`](bench/CHANGELOG_RESULTS.md).

The datasets and the raw model answers are not in git, so a change to
sample building or to a runner cannot be re-run from a clone today. Say so
in the pull request and the maintainer will run it.

## Review

There is one maintainer. Pull requests and issues are answered as time allows;
no response time is promised. There is no advisory board and no
formal RFC process.

For an optional Claude edit and independent Codex review, see the
[on-demand patch review runbook](scripts/review/README.md). It keeps tests,
integration, commits, pushes, and publishing under supervisor control.

## Conflict-of-interest disclosure

If you author, maintain, or are employed by the organization behind a tool
you are adding or whose benchmark row you want changed, say so in the pull
request or issue. It does not disqualify a contribution but must be visible.

## What stays stable

- A node `id` is not reused for a different node. A removed id stays listed
  in `data/TOMBSTONES.yml` (from 2026-11-21 on; earlier removals are in the
  git history only).
- The 11 failure-mode ids.
- Published benchmark results are versioned and a frozen copy of each
  version is kept under `bench/report/versions/`.

Fields, facet values and tags can change when they are found to be wrong.

## Licensing

- Code contributions: Apache-2.0.
- Data contributions (YAML under `data/`): CC-BY-4.0. Do not paste text
  from a source whose licence does not allow that; quote briefly, name the
  source, or paraphrase. See [`LICENSE-DATA`](LICENSE-DATA).

By opening a pull request you agree that your contribution is licensed
under these terms.
