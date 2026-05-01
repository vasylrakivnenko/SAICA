# SAICA-KG promptfoo evals

Behavioural CI gate for SAICA-KG itself — we install what we recommend.
The KG entry that motivated this lives at
[`data/tools/promptfoo.yml`](../data/tools/promptfoo.yml); the runner
config is in [`promptfooconfig.yaml`](../promptfooconfig.yaml) at the
repo root, and the GitHub Actions workflow is in
[`.github/workflows/promptfoo.yml`](../.github/workflows/promptfoo.yml).

## What this checks

Three test groups, each backed by a YAML file in this directory:

1. **`static_invariants.yaml` — no-fabrication invariants** over
   [`recommendations.json`](../recommendations.json):
   - Every `tool_id` referenced in any tier resolves to an actual
     `data/tools/<id>.yml`.
   - Every `failure_mode` is one of the 11 canonical SAICA ids.
   - The `blocklist` (e.g. `comfyui`) is honoured — no blocklisted id
     ever appears as a recommended tool.
   - For each agent in `by_agent`, the recommended supervisors never
     include a peer coding agent (no telling a Cursor user to install
     Cline). This is the MECE/crosswalk-honesty invariant.

2. **`recommendations_quality.yaml` — coverage guarantees**:
   - The `optimal` tier for `claude-code` covers ≥ 8 of 11 failure modes.
   - Every `full` tier (agnostic and per-agent) reports
     `coverage_complete: true`.
   - Every `minimum` tier returns exactly one tool.

3. **`ask_probe.yaml` — live `/ask` backend probe** (gated):
   - "What tool prevents scope_creep in a Python pipeline using GitHub
     Actions?" — answer must mention at least one of `semgrep`,
     `promptfoo`, `langgraph`, `guardrails-ai` and may not bracket-cite
     any unknown id.
   - "What's the difference between fabrication and obsolescence?" —
     answer must mention both ids and must not fabricate a third FM.

   **These tests are skipped (pass with `reason: "skipped: ASK_API
   unset"`) when the `ASK_API` env var is empty**, so the default CI
   run stays green without a running backend or a Kimi key.

Helpers live in `_assertions.py` and use stdlib only — no extra Python
deps in CI.

## Run locally

From the repo root:

```bash
# Static invariants + coverage checks (no network, no Kimi key needed):
npx --yes promptfoo@latest eval --no-cache --max-concurrency 4

# View results in promptfoo's local web UI:
npx --yes promptfoo@latest view
```

If you have promptfoo installed globally (`npm install -g promptfoo`),
drop the `--yes` and the version pin:

```bash
promptfoo eval --no-cache
```

## Wire the live `/ask` probe

In one terminal, start the backend (uses your existing `.venv`):

```bash
.venv/bin/python -m pipeline.ask.server
```

In another terminal, point promptfoo at it:

```bash
ASK_API=http://localhost:4322/ask \
    npx --yes promptfoo@latest eval --no-cache
```

The two `ask_probe` tests will now actually POST to the backend, parse
the JSON response, and assert on `answer` content.

## Running a single group

promptfoo doesn't filter on `metadata.tags` from the CLI directly, but
you can point at a single tests file via a one-off override config or by
swapping the `tests:` list in `promptfooconfig.yaml` while iterating
locally. For most edits it's faster to comment out the other two
`file://evals/...yaml` lines temporarily.
