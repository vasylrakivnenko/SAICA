# SAICA supervision kit

Drop-in files that make every commit in a repository get checked by the
supervision tools and LLM reviewers you picked in the kit builder at
<https://saica.ai/tool-coverage>, log what each check caught, and
visualise it over time.

Your coding agent copies these files into your repo and adapts them;
the setup prompt copied from <https://saica.ai/tool-coverage> walks it
through the steps.

| File | Installed at | Purpose |
|---|---|---|
| `saica_check.py` | `.saica/saica_check.py` | Check runner (Python 3.9+, stdlib only). |
| `checks.example.json` | `.saica/checks.json` | Which tool runs which command for which failure modes. **Adapt this.** |
| `hooks/pre-commit` | `.git/hooks/pre-commit` (via `install-hooks`) | Runs checks, blocks the commit on a blocking failure. |
| `hooks/post-commit` | `.git/hooks/post-commit` (via `install-hooks`) | Stamps the results with the new commit sha. |
| `saica-ci.yml` | `.github/workflows/saica-ci.yml` | Same checks on every push (backstop for `--no-verify`). |
| `dashboard.html` | `.saica/dashboard.template.html` | Offline dashboard: commits × failure modes. |
| `selftest.py` | `.saica/selftest.py` | End-to-end proof that the wiring works. |
| `saica_llm_review.py` | `.saica/saica_llm_review.py` | Optional: runs a benchmarked LLM reviewer as a check (see [LLM reviewer checks](#llm-reviewer-checks)). |
| `prompts/<mode>.md` | `.saica/prompts/<mode>.md` | Optional: the SAICA-Bench reviewer prompts. |

Commit `.saica/saica_check.py`, `.saica/checks.json`, `.saica/selftest.py`,
`.saica/dashboard.template.html` (plus `.saica/saica_llm_review.py` and
`.saica/prompts/` if you use LLM reviewers). Gitignore `.saica/events.jsonl`,
`.saica/pending.jsonl`, `.saica/dashboard.html`, `.saica/task.md`.

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
  "kit": "custom",
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
      "failure_modes": ["dependency_blindness"],
      "runs_per_commit": true,
      "command": "sentrux gate",
      "blocking": false,
      "metric": { "name": "quality", "regex": "quality[^0-9]*([0-9]+(?:\\.[0-9]+)?)" }
    },
    {
      "id": "dependency-blindness-review",
      "failure_modes": ["dependency_blindness"],
      "runs_per_commit": true,
      "command": "python3 .saica/saica_llm_review.py --prompt .saica/prompts/dependency_blindness.md --model gpt-6-luna --api-style azure --api-base-env SAICA_LLM_API_BASE --api-key-env SAICA_LLM_API_KEY",
      "blocking": false,
      "timeout_s": 300
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
  "kit": "custom",
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

---

## LLM reviewer checks

`saica_llm_review.py` (Python 3.9+, stdlib only) runs one SAICA-Bench
reviewer prompt as an ordinary `command`, so its results flow through the
same events, blocking rules and dashboard as any other tool. Commit it and
the prompts: pre-commit runs commands in a temporary checkout of the staged
tree, and untracked files are not in that checkout.

```bash
python3 .saica/saica_llm_review.py --prompt .saica/prompts/dependency_blindness.md \
    --model gpt-6-luna --api-style azure --dry-run   # print the filled prompt; no call
```

- **Which change.** In pre-commit (`SAICA_REPO_ROOT` is set) the reviewer
  reads the staged diff with `git diff --cached`, which inside the temporary
  checkout reads the snapshot's index. Everywhere else (CI, `run --commit`,
  manual runs) it reviews `HEAD` against its first parent; `saica-ci.yml`
  checks each commit out first. Override with `--staged`, `--commit REV` or
  `--diff-file PATH` (`-` = stdin). Do not use `replay --with-tools` with LLM
  reviewers: replay does not check out old commits, so the reviewer would
  re-review the current `HEAD` once per replayed commit and pay for every call.
- **Environment.** The endpoint and key are read from the variables named by
  `--api-base-env` / `--api-key-env` (defaults `SAICA_LLM_API_BASE` /
  `SAICA_LLM_API_KEY`). Never put a key in `checks.json`. The base is the URL
  in front of `/chat/completions`, e.g.
  `https://<resource>.services.ai.azure.com/openai/v1`. `--api-style openai`
  sends `Authorization: Bearer` and `max_tokens`. `--api-style azure` sends
  `api-key` and `max_completion_tokens`, plus `?api-version=` when
  `--api-version` is given. In CI, set both variables from repository secrets
  in the `env` of the "Run SAICA checks for each commit" step. The key is
  redacted from all output. The diff and task text are sent to the provider.
- **Task file.** The benchmark gave each reviewer the issue text; at commit
  time the task file plays that role. `{issue}` (also `{task}`, `{spec}`) is
  filled from `--task-file`, else `$SAICA_TASK_FILE`, else `.saica/task.md`,
  else `(no task description provided)`. Relative task paths are looked up in
  the real checkout first, so the file can stay untracked: have the agent, or
  you, write the task there when the work starts. In CI it is absent unless a
  step writes one (e.g. the PR description) and sets `SAICA_TASK_FILE`.
- **Template.** For a `.md` prompt the template is the first fenced code
  block. Placeholders are `{issue}`, `{patch}` (also `{diff}`, `{code}`),
  `{context}` (from `--context-file`, repeatable, shown as in the benchmark),
  and `--fill NAME=FILE` for any other name. Unknown placeholders are emptied
  with a warning. Literal braces are written `{{` `}}`, as in the benchmark
  source.
- **Output and exit codes.** The reviewer prints one line:
  `flagged: <evidence>` (exit 1, recorded as `caught`), `ok: <reason>`
  (exit 0, `pass`) or `error: <reason>` (exit 127, `error`). Errors are a
  missing variable, an HTTP failure after retries, `--timeout` reached, an
  unreadable answer or bad arguments. Contract v1 maps only exit 127 and
  timeouts to `error`, so these events' detail starts with the runner's
  generic `command not found (exit 127):` before the reviewer's `error:`
  line. An `error` never blocks. Any other non-zero exit would be recorded
  as `caught`; `--error-exit N` sets a different code for other runners.
  Answers are parsed as in SAICA-Bench: the text after `</think>`, then the
  last JSON object holding the flag field (by default the field the template
  asks to be `true or false`; `--flag-field` overrides it). Keep `timeout_s`
  above `--timeout` (default 240 s, retries included).
- **Comparable results.** A result is comparable to the SAICA-Bench score
  only when the prompt is unchanged and the model, provider and settings
  match the recipe published with that prompt: `--temperature` (not sent by
  default; the benchmark used 0, except for gpt-6-luna, which accepts only
  its default), `--max-tokens` (default 16384, the benchmark's most common
  setting; other recipes used 1024 to 32768, so use the recipe's value),
  `--stream` (used for Hyperbolic), `--extra-body` (e.g.
  `'{"reasoning_effort": "low"}'`), and a real task description. Cutting the
  diff (`--max-diff-chars`, default 100000) also breaks comparability.
- **Combined mode (untested).** With several `--prompt` files, the reviewer
  sends ONE request that holds every template. It prints one line per failure
  mode, named after each file (`dependency_blindness.md` →
  `dependency_blindness`). It exits 1 if any mode is flagged, 127 if any answer
  is unreadable and none is flagged, else 0. It warns that combined review is
  not benchmarked: SAICA-Bench measured one prompt per call. The runner still
  records one outcome per tool, so every failure mode of a combined entry gets
  the same outcome. Use one entry per mode to keep them apart.
- **Cost.** Each LLM entry makes one paid call per commit, plus one per
  commit that CI checks. Start with `blocking: false`.
