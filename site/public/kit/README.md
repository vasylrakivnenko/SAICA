# SAICA supervision kit

Drop-in files that make every commit in a repository get checked by the
supervision tools you installed from a SAICA-KG coverage level
(`minimum` / `optimal` / `full`), log what each check caught, and
visualise it over time.

Your coding agent copies these files into your repo and adapts them;
the copied setup prompt on `/tool-coverage` walks it through the steps.

| File | Installed at | Purpose |
|---|---|---|
| `saica_check.py` | `.saica/saica_check.py` | Check runner (Python 3.9+, stdlib only). |
| `checks.example.json` | `.saica/checks.json` | Which tool runs which command for which failure modes. **Adapt this.** |
| `hooks/pre-commit` | `.git/hooks/pre-commit` (via `install-hooks`) | Runs checks, blocks the commit on a blocking failure. |
| `hooks/post-commit` | `.git/hooks/post-commit` (via `install-hooks`) | Stamps the results with the new commit sha. |
| `saica-ci.yml` | `.github/workflows/saica-ci.yml` | Same checks on every push (backstop for `--no-verify`). |
| `dashboard.html` | `.saica/dashboard.template.html` | Offline dashboard: commits × failure modes. |
| `selftest.py` | `.saica/selftest.py` | End-to-end proof that the wiring works. |

Commit `.saica/saica_check.py`, `.saica/checks.json`, `.saica/selftest.py`,
`.saica/dashboard.template.html`. Gitignore `.saica/events.jsonl`,
`.saica/pending.jsonl`, `.saica/dashboard.html`.

---

## Contract (v1)

Everything below is the stable interface between the runner, the hooks,
CI, the self-test and the dashboard.

### The 11 failure modes

`scope_creep`, `fabrication`, `security_vulnerability`,
`supply_chain_attack`, `logic_error`, `cascading_failure`,
`context_pollution`, `obsolescence`, `test_manipulation`,
`dependency_blindness`, `incomplete_execution`.

### `.saica/checks.json`

```json
{
  "version": 1,
  "kit": "optimal",
  "builtin": { "enabled": true, "blocking": false },
  "tools": [
    {
      "id": "semgrep",
      "failure_modes": ["security_vulnerability"],
      "runs_per_commit": true,
      "command": "semgrep scan --config auto --error --quiet {files}",
      "blocking": true,
      "timeout_s": 300
    },
    {
      "id": "sentrux",
      "failure_modes": ["cascading_failure", "dependency_blindness"],
      "runs_per_commit": true,
      "command": "sentrux gate",
      "blocking": false,
      "metric": { "name": "quality", "regex": "quality[^0-9]*([0-9]+(?:\\.[0-9]+)?)" }
    },
    {
      "id": "activepieces",
      "failure_modes": ["context_pollution", "scope_creep", "supply_chain_attack"],
      "runs_per_commit": false,
      "note": "Workflow platform; not a per-commit check."
    }
  ]
}
```

- `command` runs through the shell. Pre-commit runs tools in a temporary
  checkout of the staged files; unstaged changes and untracked dependencies
  are not included. Configure tools to be available on `PATH`. The runner
  reads the original checkout's `checks.json`, so use a trusted configuration.
  CI runs commands against the checked-out commit.
  On POSIX, `{files}` expands to the shell-quoted list of changed files.
  An empty list is recorded as `skipped`; native Windows reports an error
  for commands using `{files}`.
- Exit code `0` → `pass`; non-zero → `caught`; command not found
  (exit 127) or timeout → `error`.
- `metric.regex` is applied to stdout+stderr; group 1 is parsed as a float.
- `runs_per_commit: false` tools are recorded but never executed.
- `blocking: true` + `caught` → pre-commit exits non-zero (commit blocked).
  `error` never blocks.

### Built-in checks (`builtin.enabled`)

Cheap, language-agnostic diff heuristics so every repo gets signal on
day one. Tool ids are prefixed `saica:`.

| tool_id | failure_mode | Signal on added lines of the diff |
|---|---|---|
| `saica:stub-markers` | `incomplete_execution` | new `TODO`, `FIXME`, `XXX`, `NotImplementedError`, `raise NotImplemented`, body-only `pass` / `...` |
| `saica:test-weakening` | `test_manipulation` | in test files: removed assertions > added assertions, or new `skip` / `xfail` / `.skip(` / `it.only`-style markers |
| `saica:phantom-import` | `fabrication` | new Python / JS imports of a top-level package that is not stdlib, not a local module, and not declared in `requirements*.txt` / `pyproject.toml` / `package.json` |

### `.saica/events.jsonl` (one JSON object per line)

```json
{
  "v": 1,
  "ts": "2026-11-19T10:02:11Z",
  "commit": "3f2a9c1e…",
  "commit_ts": "2026-11-19T10:02:09Z",
  "subject": "Add retry to fetcher",
  "agent": "claude",
  "kit": "optimal",
  "source": "pre-commit",
  "tool_id": "semgrep",
  "failure_mode": "security_vulnerability",
  "outcome": "caught",
  "blocking": true,
  "detail": "src/fetch.py:42 python.lang.security.audit.eval-detected",
  "metric": null,
  "metric_name": null
}
```

- One event per (commit, tool, failure_mode). A tool covering three
  failure modes emits three events with the same outcome.
- `outcome` ∈ `pass` | `caught` | `error` | `skipped` | `not_runnable` |
  `not_covered`.
  - `not_runnable`: tool has `runs_per_commit: false`.
  - `not_covered`: one event per failure mode that **no** configured tool
    or built-in covers (`tool_id: null`). This is what makes gaps
    visible without the dashboard reading `checks.json`.
- `commit`: full sha; `"staged"` while pending (pre-commit, before
  `stamp`). Pending results are stamped only if the checked tree and base
  match the new commit. An amend that changes the expected parent is not
  stamped; use `run --commit HEAD` from a clean checkout to check the
  amended commit explicitly.
- `agent`: detected from the commit author / `Co-Authored-By` trailers:
  `claude`, `copilot`, `cursor`, `devin`, `codex`, `aider`, other bots
  → `"bot"`, otherwise `null` (human).
- `source` ∈ `pre-commit` | `ci` | `replay` | `manual`.
- `detail` ≤ 500 chars. No author names or emails are recorded.
- `metric` / `metric_name`: from the tool's `metric` config, else null.

### Runner CLI

```bash
python .saica/saica_check.py run --staged            # pre-commit: writes .saica/pending.jsonl, exit 1 if a blocking check caught
python .saica/saica_check.py stamp                   # post-commit: pending → events.jsonl with HEAD sha
python .saica/saica_check.py run --commit <sha> --source ci   # CI / manual: writes events.jsonl directly
python .saica/saica_check.py replay --last 30        # built-ins over history (tools only with --with-tools)
python .saica/saica_check.py dashboard               # writes .saica/dashboard.html with events embedded
python .saica/saica_check.py install-hooks           # installs hooks/pre-commit + post-commit into .git/hooks
```

`install-hooks` refuses to overwrite a custom existing hook unless
`--force`, which saves the old hook to a new backup. If the repo uses the
`pre-commit` framework, configure local entries for both stages with
`pass_filenames: false`. The install self-test uses PyYAML when verifying
framework configuration; the runner and direct Git hooks do not require it.

### Dashboard embedding

`dashboard.html` contains

```html
<script id="saica-events" type="application/json">[]</script>
```

`saica_check.py dashboard` replaces the `[]` with the JSON array of
events (with `</` escaped) and writes `.saica/dashboard.html`. When the
embedded array is empty the page tries `fetch("events.jsonl")` and
offers a file picker / drag-and-drop for a `.jsonl` file.
