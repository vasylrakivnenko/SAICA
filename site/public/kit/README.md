# SAICA supervision kit

Drop-in files that make every commit in a repository get checked by the
checks you picked in the kit builder at <https://saica.ai/tool-coverage>,
log what each check caught, and show it over time.

Your coding agent copies these files into your repo and adapts them; the
setup prompt copied from <https://saica.ai/tool-coverage> walks it through
the steps.

| File | Installed at | Purpose |
|---|---|---|
| `saica_check.py` | `.saica/saica_check.py` | Check runner (Python 3.9+, standard library only). |
| `checks.example.json` | `.saica/checks.json` | The default kit: one check per failure mode that SAICA-Bench can score well enough. Generated from the benchmark results. **Adapt this.** |
| `saica_llm_review.py` | `.saica/saica_llm_review.py` | Runs a benchmarked LLM reviewer prompt as a check (see [LLM reviewer checks](#llm-reviewer-checks)). |
| `saica_static.py` | `.saica/saica_static.py` | Runs mypy, pyright, ruff, bandit or semgrep with the benchmark's flag rule (see [Static checker checks](#static-checker-checks)). |
| `prompts/<mode>.md` | `.saica/prompts/<mode>.md` | The SAICA-Bench reviewer prompts, with the settings of each benchmark row. `prompts/test_manipulation.rule.txt` is the rule text that prompt is filled with. |
| `hooks/pre-commit` | `.git/hooks/pre-commit` (via `install-hooks`) | Runs the checks; stops the commit when a blocking check caught something. |
| `hooks/post-commit` | `.git/hooks/post-commit` (via `install-hooks`) | Stamps the results with the new commit sha. |
| `saica-ci.yml` | `.github/workflows/saica-ci.yml` | The same checks in CI (backstop for `--no-verify`). |
| `dashboard.html` | `.saica/dashboard.template.html` | Offline dashboard: commits × failure modes. |
| `selftest.py` | `.saica/selftest.py` | End-to-end proof that the wiring works. |
| `SHA256SUMS` | (not installed) | Checksums of the files above. Check your downloads: `shasum -a 256 -c SHA256SUMS`. |

Commit `.saica/saica_check.py`, `.saica/checks.json`, `.saica/selftest.py`,
`.saica/dashboard.template.html`, the helper scripts and `.saica/prompts/`.
Gitignore `.saica/events.jsonl`, `.saica/pending.jsonl`,
`.saica/dashboard.html`, `.saica/cache/`, `.saica/task.md`,
`.saica/session.txt` and `.saica/final_message.txt`.

## What the numbers mean

Each check in the builder and in `checks.example.json` carries a
`note` such as "Benchmark J 92% (95% interval 88% to 95%; 348 bad + 288
clean samples) on <what the benchmark reviewed>. At commit time this check
sees <what it gets in your repository>."

- J is recall minus false-alarm rate on one benchmark set, where the reviewer
  was told which failure to look for. It is not the accuracy of the check on
  your commits. No check has been measured on commit-shaped input yet.
- For some failure modes the benchmark input does not exist at commit time
  (a whole agent session for test manipulation, one function with its own
  task for logic error). The note says so.
- A tool the kit cannot run by itself (hybrid tools) is listed with
  `runs_per_commit: false` and the words "benchmark rule, not the installed
  check".
- False alarms add up when several checks run on every change. The builder
  shows an estimate for your selection.

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
      "id": "fabrication-mypy",
      "failure_modes": ["fabrication"],
      "runs_per_commit": true,
      "command": "python3 .saica/saica_static.py --tool mypy --codes name-defined,import-not-found,attr-defined,call-arg,import --added-lines-only",
      "blocking": false,
      "timeout_s": 600,
      "note": "free text: what the check is, where its numbers come from"
    },
    {
      "id": "my-linter",
      "failure_modes": ["logic_error"],
      "command": "my-linter --quiet {files}",
      "caught_exit_codes": [1, 3]
    }
  ]
}
```

- **Which config judges a change.** At commit time the runner reads
  `.saica/checks.json`, and runs the helper scripts and prompts under
  `.saica/`, as they are in the last commit (`HEAD`), not as they are in the
  working tree or in the change being committed. A change cannot weaken the
  checks that judge it. Before the kit's first commit the staged files are
  used. `--config PATH` overrides this. CI takes the kit from the base of the
  change (see [CI](#ci)).
- `command`: a command made of plain words (quotes allowed) is run directly,
  without a shell. A command with a shell operator (`|`, `>`, `;`, `$VAR`,
  `*`, `!` …) or a `NAME=value` prefix runs through the shell. Pre-commit runs
  tools in a temporary checkout of the staged files; unstaged changes and
  untracked files are not there (`SAICA_REPO_ROOT` names the real checkout).
  CI runs commands against the checked-out commit.
- **Environment.** A tool gets the runner's environment, except model API
  keys: a variable named with `--api-key-env` in some command (and
  `SAICA_LLM_API_KEY`) is passed only to the commands that name it.
- **Exit codes.** `0` → `pass`. A code listed in `caught_exit_codes`
  (default `[1]`) → `caught`. Every other exit code, a timeout, or a command
  that cannot start → `error`: a tool that failed is not a finding. Many tools
  use 2 or more for their own failures (pytest 2–5, ruff 2, a shell syntax
  error 2). If your tool reports findings with another code, list it. `0` and
  `127` cannot be listed. `python -m tool` with the tool not installed exits 1;
  the runner records `error` only when the interpreter's one-line message is
  the whole output and names that module.
- **Result lines.** A command may print one of these as its last line; the
  kit's helper scripts do. `ok: …` (exit 0) is kept as the detail of the
  `pass`; `skipped: …` (exit 0) is recorded as `skipped`; `flagged: …`
  (exit 1) is the detail of the `caught`; `error: …` / `partial: …`
  (exit 127) is the detail of the `error`.
- **`{files}`** expands to the list of changed files (POSIX only): one
  argument per file without a shell, shell-quoted with one. It must be a word
  of its own: inside quotes, a `#` comment, backticks, `$(...)` or a
  here-document the runner refuses to fill it in and records `error`,
  because a file name could then run as a command. In a shell command, paths
  that contain a newline, carriage return or NUL are refused. An empty list
  is `skipped`. A list that would make the command longer than 120,000 bytes
  is an `error` that says so.
- **`{files_from}`** expands to the path of a temporary file that holds the
  changed files separated by NUL bytes, for long lists and odd names:
  `xargs -0 my-linter < {files_from}`.
- `timeout_s` (default 300): the tool and everything it started is stopped.
- `metric.regex` is applied to stdout+stderr; group 1 is parsed as a float.
- `runs_per_commit: false` tools are recorded (`not_runnable`) but never run.
- `blocking: true` + `caught` → pre-commit exits non-zero (commit blocked).
  A blocking check that could not run on the change (`error`: the tool is
  missing, timed out, was refused a file list, or a helper reported
  `partial`) blocks too, and the message says why: it did not vouch for the
  change. `"on_error": "pass"` lets such errors through for one check;
  `"on_error": "block"` makes the errors of a non-blocking check block.
  Default: `block` when `blocking` is true, else `pass`. Start with
  `blocking: false`.
- `note`: free text. Put explanations here, not in the command.

### Built-in checks (`builtin.enabled`)

Cheap diff heuristics. Tool ids are prefixed `saica:`. **They are not
benchmarked** and do not count as coverage: a failure mode that only a
built-in watches still gets a `not_covered` event, and the dashboard counts
it as a gap.

| tool_id | failure_mode | Signal |
|---|---|---|
| `saica:stub-markers` | `incomplete_execution` | added lines with `TODO`, `FIXME`, `XXX`, `raise NotImplemented…`, body-only `pass` / `...` |
| `saica:test-weakening` | `test_manipulation` | in test files: removed assertions > added assertions, or new `skip` / `xfail` / `.skip(` / `it.only`-style markers |
| `saica:phantom-import` | `fabrication` | new Python / JS imports of a package that is not stdlib, not a local module, and not declared in `requirements*.txt` / `pyproject.toml` / `package.json` |
| `saica:kit-tamper` | `test_manipulation` | the change adds, edits or deletes a file of the kit: anything under `.saica/` (the event log included) except `task.md`, `session.txt`, `final_message.txt` and `dashboard.html`; `.github/workflows/saica-ci.yml`; a file in a hooks directory inside the repository that `core.hooksPath` points at; or a hook config line that names the kit |

`saica:kit-tamper` exists because the cheapest way around a check is to
switch it off. **It blocks by default** (`"builtin": {"tamper_blocking":
false}` turns that off) and it still runs when the same change sets
`builtin.enabled` to false. To commit an intended change to the kit, commit
it on its own with `SAICA_KIT_CHANGE_OK=1 git commit …`: the event is still
recorded as `caught`. The first commit that installs the kit is recorded as
`pass`. CI takes the whole kit from the base of the change (see [CI](#ci)).
Add a `CODEOWNERS` rule for `.saica/` and the workflow so that changes to
the kit need a person's review.

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
  "tool_id": "fabrication-mypy",
  "failure_mode": "fabrication",
  "outcome": "caught",
  "blocking": false,
  "detail": "flagged: src/fetch.py:42 attr-defined Module \"os\" has no attribute \"fetch\"",
  "metric": null,
  "metric_name": null
}
```

- One event per (commit, tool, failure_mode). A tool covering three
  failure modes emits three events with the same outcome.
- `outcome` ∈ `pass` | `caught` | `error` | `skipped` | `not_runnable` |
  `not_covered`.
  - `error`: the tool did not run or failed. It says nothing about the change.
  - `not_runnable`: tool has `runs_per_commit: false`.
  - `not_covered`: one event per failure mode that no configured tool
    checks per commit (`tool_id: null`). Built-in heuristics do not count.
- `commit`: full sha; `"staged"` while pending (pre-commit, before
  `stamp`). Pending results are stamped only if the checked tree and base
  match the new commit. An amend that changes the expected parent is not
  stamped; use `run --commit HEAD` from a clean checkout to check the
  amended commit explicitly.
- `agent`: detected from the commit author / `Co-Authored-By` trailers:
  `claude`, `copilot`, `cursor`, `devin`, `codex`, `aider`, other bots
  → `"bot"`, otherwise `null` (human).
- `source` ∈ `pre-commit` | `ci` | `replay` | `manual`.
- `detail` ≤ 500 chars. No author names or emails are recorded. A tool's
  output can quote what it found (a secret scanner quotes the secret), and
  the detail goes into the event log, the dashboard and the CI artifact.
- `metric` / `metric_name`: from the tool's `metric` config, else null.
- The log must be an untracked regular file inside the repository. The
  runner stops (exit 2) when `.saica/events.jsonl` or `.saica/pending.jsonl`
  is tracked by git or is a symbolic link: a commit could otherwise replace
  or discard the record of its own checks. `--events PATH` writes the log
  somewhere else (CI uses a folder outside the checkout).

### Runner CLI

```bash
python .saica/saica_check.py run --staged            # pre-commit: writes .saica/pending.jsonl, exit 1 if a blocking check caught
python .saica/saica_check.py stamp                   # post-commit: pending → events.jsonl with HEAD sha
python .saica/saica_check.py run --commit <sha> --source ci   # CI / manual: writes events.jsonl directly
python .saica/saica_check.py replay --last 30        # built-ins over history (tools only with --with-tools)
python .saica/saica_check.py dashboard               # writes .saica/dashboard.html with events embedded
python .saica/saica_check.py install-hooks           # installs hooks/pre-commit + post-commit into .git/hooks
```

`install-hooks` refuses to overwrite a hook that is not a kit hook unless
`--force`, which saves the old hook to a new backup. It refuses to install
when the hooks directory is outside the repository (a global
`core.hooksPath`): hooks written there would run in every repository that
shares the folder. If the repo uses the `pre-commit` framework, configure
local entries for both stages with `pass_filenames: false`. The install
self-test uses PyYAML when verifying framework configuration; the runner
and direct Git hooks do not require it.

`python .saica/selftest.py --repo` fails when a command still holds a
`<placeholder>` or a `{files}` in an unsafe place.

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

## Static checker checks

A checker's exit code says "some file has a problem somewhere". In a
repository that is not already clean under that checker this is true for
many clean changes. SAICA-Bench scored programs with a narrower rule, and
`saica_static.py` applies that rule: a change is flagged only when a finding
with one of the counted codes lies on a line the change **added**.

```bash
python3 .saica/saica_static.py --tool mypy --tool-arg=--check-untyped-defs \
    --codes name-defined,import-not-found,attr-defined,call-arg,import --added-lines-only
```

- Tools: `mypy`, `pyright`, `ruff`, `bandit`, `semgrep`. It works out the
  changed files itself (no `{files}`), runs the tool without a shell, in
  batches, and reads the tool's machine-readable output.
- `--codes` takes rule codes (a trailing `*` matches by prefix, `NPY*`);
  `--severity error` keeps one severity; `--tool-arg=…` passes an option to
  the tool; `--python PATH` names the interpreter whose installed packages
  mypy / pyright resolve imports against.
- Result: `flagged: …` exit 1, `ok: …` or `skipped: …` exit 0, `error: …`
  exit 127 when the tool is missing, failed, timed out or printed something
  that cannot be read. A tool failure never looks like a pass or a finding.
- `partial: …` (exit 127) when the tool found nothing that counts but the
  change itself makes the tool say less: it adds a suppression comment
  (`# noqa`, `# type: ignore`, `# nosec`, `nosemgrep`, `# pyright: …`) to a
  checked file, or edits the tool's own configuration (`ruff.toml`,
  `mypy.ini`, `pyrightconfig.json`, `.bandit`, the tool's section of
  `pyproject.toml` / `setup.cfg` / `tox.ini`). With a counted finding the
  result is `flagged` and the note is added.
- A file renamed or copied into another extension (`payload.txt` →
  `payload.py`) is new to the checker: all of its lines count as added. File
  names reach the tool as `./name`, after `--` where the tool takes it. Diffs
  are read with `git diff --text`, so `.gitattributes` cannot hide a file.
- The checker must see the project's installed packages, or every
  third-party import looks like a missing one.

## LLM reviewer checks

`saica_llm_review.py` (Python 3.9+, standard library only) runs one
SAICA-Bench reviewer prompt as an ordinary `command`. Commit it and the
prompts: pre-commit runs commands in a temporary checkout of the staged
tree, and untracked files are not in that checkout.

```bash
python3 .saica/saica_llm_review.py --prompt .saica/prompts/scope_creep.md \
    --model mimo-v2.6-flash --dry-run   # print the filled prompt; no call
```

- **Which change.** In pre-commit (`SAICA_REPO_ROOT` is set) the staged
  diff. Everywhere else (CI, `run --commit`, manual runs) `HEAD` against its
  first parent. Override with `--staged`, `--commit REV` or
  `--diff-file PATH` (`-` = stdin). Do not use `replay --with-tools` with
  LLM reviewers: replay does not check out old commits.
- **What is sent.** The diff, the task text and any `--fill` /
  `--context-file` file go to the provider you configure. Not sent by
  default: `.saica/`, `node_modules/`, lock files, minified files, binary
  files. A change that touches one of them was not reviewed in full, so the
  result is `partial` (or `flagged`), never `ok`, and the files are named.
  `--exclude GLOB` names paths you accept leaving out (no `partial` for
  those); `--no-default-excludes` sends everything. Nothing filters secrets
  inside the files that are sent. Code and dependency manifests go first. A
  diff longer than `--max-diff-chars` (default 100,000) is cut at a file
  boundary and the result is `partial`, never `ok`. Diffs are made with
  `git diff --text`, so `.gitattributes` cannot hide a file.
- **Input per failure mode.** The benchmark did not always review a commit
  diff. The builder adds the options that bring the input closest:

  | Prompt | The benchmark reviewed | Options / files needed |
  |---|---|---|
  | `fabrication.md` | the diff of one file, 15 lines of context | `--per-file --context-lines 15` |
  | `obsolescence.md` | one whole file and the request | `--whole-file` |
  | `logic_error.md` | one function and its task | `--whole-file` (whole files, not single functions: not the benchmark input) |
  | `scope_creep.md`, `security_vulnerability.md`, `supply_chain_attack.md` | task text and a patch | none; needs a task file |
  | `dependency_blindness.md` | issue, patch, sometimes the helper's file | `--context-file PATH` if you know which file |
  | `incomplete_execution.md` | issue, patch, the agent's closing message | `--fill final=.saica/final_message.txt` |
  | `test_manipulation.md` | the agent's whole session | `--fill rule=.saica/prompts/test_manipulation.rule.txt --fill transcript=.saica/session.txt` (nothing in the kit writes the session; your agent must) |

  `--per-file` makes one request per changed file (at most `--max-files`,
  default 20; more is `partial`). `--whole-file` sends each changed file in
  full instead of its diff.
- **Environment.** The endpoint and key are read from the variables named
  by `--api-base-env` / `--api-key-env` (defaults `SAICA_LLM_API_BASE` /
  `SAICA_LLM_API_KEY`). Never put a key in `checks.json` or in the URL. A
  hook started by an IDE or a Git GUI does not see variables exported in your
  shell profile; set them where that program reads its environment. The base
  is the URL in front of `/chat/completions`. `--api-style openai` sends
  `Authorization: Bearer` and `max_tokens`; `--api-style azure` sends
  `api-key` and `max_completion_tokens`, plus `?api-version=` when
  `--api-version` is given. For a model that takes neither field, pass
  `--max-tokens 0` and the right field in `--extra-body`. The key and any
  credentials in the URL are kept out of all output; plain `http://` to
  another machine gets a warning.
- **Task file.** `{issue}` (also `{task}`, `{spec}`) is filled from
  `--task-file`, else `$SAICA_TASK_FILE`, else `.saica/task.md`, else
  `(no task description provided)`. Have the agent, or you, write the task
  there when the work starts. In CI it is absent unless a step writes one
  (for example the pull request description) and sets `SAICA_TASK_FILE`.
  Scope creep cannot be judged without a task.
- **Template.** For a `.md` prompt the template is the first fenced code
  block. A placeholder with no value, or a `--fill` file that is empty, is an
  `error` before any request; `--allow-empty NAME` leaves one empty on
  purpose.
- **Output and exit codes.** One result line: `flagged: <evidence>`
  (exit 1), `ok: <reason>` or `skipped: <why>` (exit 0), `partial: …` or
  `error: …` (exit 127). Errors are a missing variable, an HTTP failure
  after retries, the time budget used up, an unreadable answer or bad
  arguments. An `error` never blocks, so a missing key switches the check
  off unless the entry is blocking: watch for `error` rows on the dashboard
  and in the CI summary. Answers are parsed as in SAICA-Bench
  (`bench/common.py`): the text after `</think>`, then the last JSON object
  holding the flag field; a value that is not `true` / `false` is
  unreadable. The kit is stricter in one case: when several objects in the
  answer hold the field and any of them says `true`, the change is flagged
  (an answer that says true and then quotes `{"field": false}` from the diff
  must not come back ok). Keep `timeout_s` above `--timeout`
  (default 240 s for the whole run).
- **Verdict cache.** A `flagged` or `ok` answer is stored under a hash of
  the kit version, the endpoint, the model, the settings and the complete
  prompt (`$SAICA_CACHE_DIR`, else `.saica/cache/llm/`), and the same request
  to the same endpoint is answered from there without a call. A stored answer that is tracked by git is ignored. `--no-cache`
  turns it off; delete the folder to start over.
- **Comparable results.** A result is comparable to a SAICA-Bench score
  only when the prompt is unchanged, the input is of the kind the benchmark
  used (table above), and the model, provider and settings match the recipe
  in the prompt file: `--temperature`, `--max-tokens`, `--stream`,
  `--extra-body`.
- **Combined mode (untested).** With several `--prompt` files the reviewer
  sends one request that holds every template and prints one line per
  failure mode. SAICA-Bench measured one prompt per call; the builder does
  not offer this mode.
- **Cost.** Each LLM entry makes one paid call per commit, or one per
  changed file with `--per-file` / `--whole-file`. CI makes the calls again
  for commits its cache has not seen: a commit is usually reviewed once at
  commit time and once in its pull request, and a merged branch once more as
  one change on the default branch. Prices on the builder page are for
  benchmark-sized inputs; a commit is usually larger.

## CI

`saica-ci.yml` runs the same checks in GitHub Actions.

- Pull requests: all commits of the pull request, on every push to it, so a
  later commit cannot clear a finding of an earlier one (cached LLM verdicts
  are not paid for again). Pushes: the default branch only, one check per
  first-parent commit (a merge is checked as one change).
- The runner, `checks.json`, helper scripts and prompts are taken from the
  **base** of the change, so a commit cannot weaken the checks that judge it.
  When the base has no kit (the first install) the change's own kit is used
  and the job says so.
- LLM verdicts are cached between runs (`actions/cache`), and the event log
  and dashboard are written to `$RUNNER_TEMP/saica-out`: both outside the
  checkout, so a commit cannot replace them.
- The job fails when a blocking check caught something or could not run, and
  when a commit edits the kit itself (`saica:kit-tamper`): a person reviews
  that change and merges it on purpose.
- The job summary lists every check and warns when a tool only produced
  errors (for example a missing install step or secret). Pull requests from
  forks get no secrets, so LLM checks are `error` there.
- The template does not install your tools: add one install step per tool.

## What the kit cannot prevent

- On `pull_request` GitHub runs the workflow file of the pull request
  itself: a pull request that edits `saica-ci.yml` decides how it is checked.
  The same holds for anyone who can push to the default branch. Protect the
  workflow and `.saica/` with CODEOWNERS and branch rules.
- On a developer machine the hooks, the runner file and `git commit
  --no-verify` are in the hands of whoever (or whatever agent) works there.
  The local checks are a record and a speed bump; CI is the backstop.
- A check sees what its tool or model can see. A benchmark J says how a
  reviewer did on one kind of input; it does not say a change is safe.

## Where these files come from

`checks.example.json`, `prompts/*.md` and `SHA256SUMS` are generated from
the benchmark results by `bench/kitbuilder/build_kit.py` in the SAICA
repository; do not edit the published copies by hand.
