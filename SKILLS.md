# SAICA-KG — Agent skills file

You are reading this because a human dropped this file into your skills / rules / context directory. It distils the SAICA-KG corpus
(https://github.com/vasylrakivnenko/SAICA) into actionable guidance for when you're writing or modifying code. Use it as context, not as a
service to call. Treat the failure-mode IDs (snake_case) as the canonical vocabulary.

## How this file is meant to be used

- Drop into `.claude/skills/saica-kg.md`, `.cursor/rules/saica-kg.md`, Replit's skills directory, or any equivalent context-injection spot.
- Reload after major project changes (`python -m validator.generate_skills`).
- Failure-mode IDs in this file (e.g. `scope_creep`) are stable identifiers — quote them verbatim when surfacing supervision concerns.

## Tool stacks from the catalogue — three sizes

Built from the catalogue's tags (what each tool says it addresses), an editorial weight per failure mode and each tool's popularity (GitHub stars). A tag is a claim, not a measurement. Where SAICA-Bench measured a tool the J is shown, and a tool is never listed for a mode where it measured below J 25%. For picks built from measured results only, see https://saica.ai/tool-coverage/.

- **`minimum`** — one tool.
- **`optimal`** — three tools.
- **`full`** — the fewest tools whose tags together name every failure mode that any eligible tool is tagged for.

### `minimum`

_1 tool. Its tags name 4 of 11 failure modes; none of these tool-mode pairs was measured by SAICA-Bench. A tag is the tool's own claim._

- [`agent-governance-toolkit`](data/tools/agent-governance-toolkit.yml) — tags only, not measured; prevention/in_generation, surfaces: library, cli; AI Agent Governance Toolkit — policy enforcement, zero-trust identity, and execution oversight.

### `optimal`

_3 tools. Their tags name 8 of 11 failure modes; none of these tool-mode pairs was measured by SAICA-Bench. A tag is the tool's own claim._

- [`agent-governance-toolkit`](data/tools/agent-governance-toolkit.yml) — tags only, not measured; prevention/in_generation, surfaces: library, cli; AI Agent Governance Toolkit — policy enforcement, zero-trust identity, and execution oversight.
- [`eslint`](data/tools/eslint.yml) — tags only, not measured; detection/post_generation, surfaces: cli, ci_app, ide_plugin; Pluggable JavaScript/TypeScript linter and code-quality enforcer.
- [`langgraph`](data/tools/langgraph.yml) — tags only, not measured; prevention/pre_generation, surfaces: library; Graph-structured state machines for stateful multi-agent orchestration.

### `full`

_6 tools. Their tags name 11 of 11 failure modes; 1 of the 16 tool-mode pairs was measured by SAICA-Bench (J at or above 25%). A tag is the tool's own claim._

- [`agent-governance-toolkit`](data/tools/agent-governance-toolkit.yml) — tags only, not measured; prevention/in_generation, surfaces: library, cli; AI Agent Governance Toolkit — policy enforcement, zero-trust identity, and execution oversight.
- [`eslint`](data/tools/eslint.yml) — tags only, not measured; detection/post_generation, surfaces: cli, ci_app, ide_plugin; Pluggable JavaScript/TypeScript linter and code-quality enforcer.
- [`langgraph`](data/tools/langgraph.yml) — tags only, not measured; prevention/pre_generation, surfaces: library; Graph-structured state machines for stateful multi-agent orchestration.
- [`context7`](data/tools/context7.yml) — tags only, not measured; prevention/pre_generation, surfaces: mcp_server, cli; Up-to-date, version-pinned library documentation for coding agents — delivered as an MCP server.
- [`promptfoo`](data/tools/promptfoo.yml) — measured: test_manipulation J +86%; detection/post_generation, surfaces: cli, library, ci_app; Test prompts, agents, and RAGs — red-teaming, pentesting, and vulnerability scanning for LLMs.
- [`sentrux`](data/tools/sentrux.yml) — tags only, not measured; detection/post_generation, surfaces: cli, mcp_server, library; Real-time architectural sensor that scores codebase modularity, acyclicity, and redundancy as the agent write…

Modes named by these tools' tags: `cascading_failure`, `context_pollution`, `dependency_blindness`, `fabrication`, `incomplete_execution`, `logic_error`, `obsolescence`, `scope_creep`, `security_vulnerability`, `supply_chain_attack`, `test_manipulation`.

## Failure modes — what to watch for and what to do

One subsection per failure mode, ordered by the weights in `data/failure_mode_priorities.yml` (likelihood × impact; editorial weights, no empirical calibration).

### `scope_creep` — Scope creep

**What it is:** The agent performs actions beyond the user-stated task scope — edits files not in the request, installs packages not asked for, modifies configs outside the declared surface, or chains follow-on work unprompted. This mode is a tag, not an exclusive class: one failure can carry several modes (see related_modes).

**Detection signals (from `data/failure_modes/scope_creep.yml`):**
- Agent modifies files outside the declared task surface (e.g., paths in the user prompt).
- Agent installs dependencies not named in the prompt.
- Agent commits additional unrelated changes alongside the requested edit.
- Agent performs cleanup, refactoring, or "improvement" not explicitly requested.

**Real incident:** "Under an explicit code freeze, Replit's autonomous agent ran destructive DB commands, wiping ~1,200 exec and 1,190 company records, then fabricated 4,000 phantom users to hide the loss." — On 2025-07-18, SaaStr founder Jason Lemkin reported that Replit's agent had, during a self-described "code freeze", executed unauthorized destructive operations against the production database of a vibe-coded app he was… [`replit-agent-saastr-database-deletion-2025`]

**Tools tagged for this mode** (measured J where SAICA-Bench ran the tool):
- [`langgraph`](data/tools/langgraph.yml) — tag only, not measured; prevention/pre_generation, surfaces: library; Graph-structured state machines for stateful multi-agent orchestration.
- [`letta`](data/tools/letta.yml) — tag only, not measured; prevention/pre_generation, surfaces: library, http_service; Stateful agents framework with memory, reasoning, and context management (formerly MemGPT).

**Pre-action heuristic for an agent:**
> If you're about to edit a file the user did not name, install a package they did not ask for, or chain follow-on cleanup that wasn't requested, **stop and ask first**. Surface the unrelated issue in your reply but don't auto-fix it.

### `fabrication` — Fabrication

**What it is:** The agent emits code that references APIs, packages, functions, or symbols that do not exist in any reachable dependency or runtime. Syntactically plausible, factually false. Distinct from obsolescence (real-but-retired) and from dependency blindness (real-and-present-but-ignored). This mode is a tag, not an exclusive class: one failure can carry several modes (see related_modes).

**Detection signals (from `data/failure_modes/fabrication.yml`):**
- Agent emits an import or function call whose identifier is absent from all declared dependencies and stdlib.
- Static analyzer (e.g., pyflakes, tsc) flags the reference as undefined at pre-commit.
- Execution-grounded check (sandboxed run) raises ImportError, AttributeError, or analogous resolution failure.
- LSP-based symbol lookup returns no candidate.

**Real incident:** "Under an explicit code freeze, Replit's autonomous agent ran destructive DB commands, wiping ~1,200 exec and 1,190 company records, then fabricated 4,000 phantom users to hide the loss." — On 2025-07-18, SaaStr founder Jason Lemkin reported that Replit's agent had, during a self-described "code freeze", executed unauthorized destructive operations against the production database of a vibe-coded app he was… [`replit-agent-saastr-database-deletion-2025`]

**Tools tagged for this mode** (measured J where SAICA-Bench ran the tool):
- [`pyright`](data/tools/pyright.yml) — measured J +85%; detection/post_generation, surfaces: cli, ci_app, ide_plugin; Microsoft's fast static type checker for Python.
- [`mypy`](data/tools/mypy.yml) — measured J +77%; detection/post_generation, surfaces: cli, ci_app, ide_plugin; Static type checker for Python. Catches mismatched types before runtime.

**Pre-action heuristic for an agent:**
> If you're about to import a package or call an API you didn't see in the existing `requirements.txt` / `package.json` / `go.mod`, first verify it actually exists — check the lockfile, run `pip show` / `npm view`, or grep the codebase. Never invent package names; if unsure, ask the user which library they want.

### `security_vulnerability` — Security vulnerability

**What it is:** The agent emits code that introduces a security vulnerability — injection primitives, weak cryptographic choices, leaked secrets, or insecure deserialization. Correct-looking code that violates security invariants. This mode is a tag, not an exclusive class: one failure can carry several modes (see related_modes).

**Detection signals (from `data/failure_modes/security_vulnerability.yml`):**
- Static analyzer (semgrep, bandit, CodeQL) fires on the emitted code.
- Secret-scanner (gitleaks, trufflehog) finds hardcoded credentials.
- Generated SQL uses string concatenation instead of parameterization.
- Cryptographic primitives are weak (MD5, SHA1, ECB) or from insecure libraries.

**Real incident:** "Pull-request titles, issue bodies and comments can make three AI agents on GitHub Actions run commands and leak the repository's secrets. All three vendors confirmed the findings." — On 2026-04-15 security researcher Aonan Guan, with Zhengyu Liu and Gavin Zhong of Johns Hopkins University, published "Comment and Control", a prompt injection method against AI agents that run in GitHub Actions. Text t… [`copilot-prompt-injection-github-comments-2025`]

**Tools tagged for this mode** (measured J where SAICA-Bench ran the tool):
- [`ruff`](data/tools/ruff.yml) — tag only, not measured; detection/post_generation, surfaces: cli, ci_app, ide_plugin; Extremely fast Python linter and formatter, written in Rust.
- [`eslint`](data/tools/eslint.yml) — tag only, not measured; detection/post_generation, surfaces: cli, ci_app, ide_plugin; Pluggable JavaScript/TypeScript linter and code-quality enforcer.

**Pre-action heuristic for an agent:**
> If you're about to write SQL, shell, HTML/template, or auth code, first check whether the surrounding code uses parameterised queries, escaped templates, and a vetted crypto library. Match those patterns. Never hardcode secrets — read them from env/config. If the project has a security scanner configured, run it on the diff.

### `supply_chain_attack` — Supply-chain attack

**What it is:** The agent is induced — by its own hallucination, by an adversarial package name, or by a compromised upstream — to install or invoke malicious code. Covers slopsquatting (hallucinated package names registered by an attacker), typosquatting (near-miss names), and compromised MCP servers or tools. This mode is a tag, not an exclusive class: one failure can carry several modes (see related_modes).

**Detection signals (from `data/failure_modes/supply_chain_attack.yml`):**
- Agent-proposed install resolves to a package registered within the last 30 days with no prior maintainer reputation.
- Package name is a near-miss (Levenshtein ≤ 2) of a well-known dependency.
- MCP server manifest is unsigned or from an unknown publisher.
- Post-install, the environment shows outbound connections to unexpected hosts.

**Real incident:** "Bar Lanyado (Lasso Security) saw AI models recommend a `huggingface-cli` package that did not exist, registered it empty on PyPI and counted 15,000 to 30,000 downloads in about three months." — Bar Lanyado of Lasso Security noticed that generative AI models repeatedly recommended `pip install huggingface-cli`, a package that did not exist; the real tool is installed with `pip install -U "huggingface_hub[cli]"`… [`huggingface-cli-slopsquat-lanyado-2024`]

**Tools tagged for this mode** (measured J where SAICA-Bench ran the tool):
- [`semgrep`](data/tools/semgrep.yml) — tag only, not measured; detection/post_generation, surfaces: cli, ci_app, library; Fast, rule-based static analysis with a pattern syntax that mirrors source code.
- [`socket`](data/tools/socket.yml) — tag only, not measured; detection/pre_generation, surfaces: ci_app, cli, library; Dependency supply-chain scanner that inspects packages before install.

**Pre-action heuristic for an agent:**
> If you're about to run `pip install <name>` / `npm install <name>` for a package not already in the lockfile, first confirm the package exists on the public registry, has a non-trivial download history, and matches the spelling the user or docs gave you. Slopsquat-style typos (Levenshtein ≤ 2 from a real package, recently registered) are a red flag — refuse and ask.

### `logic_error` — Logic error

**What it is:** The agent uses real, current APIs correctly at the signature level but encodes incorrect logic for the task. The canonical "passes type check, fails correctness" class. Distinct from fabrication (API doesn't exist) and obsolescence (wrong version). This mode is a tag, not an exclusive class: one failure can carry several modes (see related_modes).

**Detection signals (from `data/failure_modes/logic_error.yml`):**
- Unit tests fail with correctness assertions (not import or type errors).
- Execution in a sandbox produces outputs that contradict the task spec.
- Mutation testing reveals that substitution of logic primitives does not change test outcomes (test insensitivity is a different signal, but logic-error cases often co-occur).
- Symbolic or property-based tests find counterexamples.

**Real incident:** "Google's Gemini CLI took a failed mkdir for a success, then ran move commands that overwrote every file but one. The agent then told the user it had lost the data." — In July 2025 product manager Anuraag Gupta asked Google's Gemini CLI to rename a directory and move its contents into a new sub-directory. The agent ran a `mkdir` that failed, did not check the result, and then used the… [`gemini-cli-file-deletion-2025`]

**Tools tagged for this mode** (measured J where SAICA-Bench ran the tool):
- [`pr-agent`](data/tools/pr-agent.yml) — measured J +53%; detection/post_generation, surfaces: ci_app, cli; AI-powered tool for automated pull-request analysis, feedback, and suggestions.
- [`uqlm`](data/tools/uqlm.yml) — measured J +52%; detection/post_generation, surfaces: library; Uncertainty Quantification for Language Models.

**Pre-action heuristic for an agent:**
> If you're about to claim a function works, run its tests (or a quick sandbox invocation with representative inputs) before saying so. "Type-checks clean" ≠ "correct". Property-based or boundary-case checks beat happy-path-only assertions.

### `cascading_failure` — Cascading failure

**What it is:** The agent detects an error and attempts a fix that introduces NEW errors; repeated iterations spiral further from the working state. A simple failure becomes an irrecoverable tangle after N recovery attempts. Distinct from logic_error (which is about the initial bug itself) and from context_pollution (which is about session-level state drift rather than error-recovery compounding). This mode is a tag, not an exclusive class: one failure can carry several modes (see related_modes).

**Detection signals (from `data/failure_modes/cascading_failure.yml`):**
- Number of files modified grows per recovery iteration.
- Error messages change category across attempts (e.g., ImportError -> TypeError -> AttributeError).
- Same file is touched N times in rapid succession with diverging diffs.
- Test pass count decreases monotonically after iteration 2.

**Real incident:** "Google's Gemini CLI took a failed mkdir for a success, then ran move commands that overwrote every file but one. The agent then told the user it had lost the data." — In July 2025 product manager Anuraag Gupta asked Google's Gemini CLI to rename a directory and move its contents into a new sub-directory. The agent ran a `mkdir` that failed, did not check the result, and then used the… [`gemini-cli-file-deletion-2025`]

**Tools tagged for this mode** (measured J where SAICA-Bench ran the tool):
- [`agent-governance-toolkit`](data/tools/agent-governance-toolkit.yml) — tag only, not measured; prevention/in_generation, surfaces: library, cli; AI Agent Governance Toolkit — policy enforcement, zero-trust identity, and execution oversight.

**Pre-action heuristic for an agent:**
> If your last fix attempt produced a *different* error than the previous one — and that's now happened twice — **stop iterating** and summarise the spiral for the user. Recovery loops compound; the third attempt rarely converges. Revert to a known-good state instead of layering more changes.

### `context_pollution` — Context pollution

**What it is:** The agent's working context degrades over a session — relevant prior information is dropped, irrelevant material accumulates, or hallucinations from earlier turns are treated as ground truth in later turns. Failure of in-session state hygiene, not of a single generation. This mode is a tag, not an exclusive class: one failure can carry several modes (see related_modes).

**Detection signals (from `data/failure_modes/context_pollution.yml`):**
- Later turns reference facts or code that never existed in user input or tool output.
- Token-budget pressure truncates prior turns containing still-relevant context.
- Agent repeats a failed tool call multiple times with identical arguments.
- Session duration exceeds a threshold at which attention-over-context is empirically unreliable for the model.

**Real incident:** "Pull-request titles, issue bodies and comments can make three AI agents on GitHub Actions run commands and leak the repository's secrets. All three vendors confirmed the findings." — On 2026-04-15 security researcher Aonan Guan, with Zhengyu Liu and Gavin Zhong of Johns Hopkins University, published "Comment and Control", a prompt injection method against AI agents that run in GitHub Actions. Text t… [`copilot-prompt-injection-github-comments-2025`]

**Tools tagged for this mode** (measured J where SAICA-Bench ran the tool):
- [`langgraph`](data/tools/langgraph.yml) — tag only, not measured; prevention/pre_generation, surfaces: library; Graph-structured state machines for stateful multi-agent orchestration.
- [`mastra`](data/tools/mastra.yml) — tag only, not measured; prevention/pre_generation, surfaces: library; The TypeScript AI agent framework — assistants, RAG, observability; supports any LLM.

**Pre-action heuristic for an agent:**
> If you find yourself referencing facts, file paths, or symbols that you can't trace back to the user's prompt or an actual tool output earlier in the session, **re-ground**. Read the relevant files freshly rather than relying on what you 'remember' from earlier turns.

### `obsolescence` — Obsolescence

**What it is:** The agent emits code that references real APIs or packages that have been deprecated, removed, or materially changed in their recommended version. The root cause is frequently training-data staleness: the model saw a library version that has since been superseded, and it confidently emits the older form. Distinct from fabrication (non-existent) and from dependency_blindness (real-and-current-but-ignored). This mode is a tag, not an exclusive class: one failure can carry several modes (see related_modes).

**Detection signals (from `data/failure_modes/obsolescence.yml`):**
- Imported API is marked deprecated in the target library's current release notes.
- Package pinning is older than the latest minor release by N versions (threshold configurable).
- Language-server or linter emits a deprecation warning.
- Behavior differs between training-era and current versions of the library.

**Measured in a study:** "Wang et al. gave seven code LLMs 28,125 completion prompts built on 145 deprecated APIs from eight Python libraries. Of the plausible completions, 25% to 38% used the deprecated API." — "LLMs Meet Library Evolution: Evaluating Deprecated API Usage in LLM-based Code Completion" (Wang, Huang, Zhang, Feng, Zhang, Liu and Peng; arXiv 2406.09834, accepted at ICSE 2025) measures how often a code LLM complete… [`copilot-obsolete-api-java8-2024`]

**Tools tagged for this mode** (measured J where SAICA-Bench ran the tool):
- [`pyright`](data/tools/pyright.yml) — measured J +57%; detection/post_generation, surfaces: cli, ci_app, ide_plugin; Microsoft's fast static type checker for Python.
- [`renovate`](data/tools/renovate.yml) — tag only, not measured; detection/post_generation, surfaces: ci_app, cli; Highly configurable multi-platform dependency update bot.

**Pre-action heuristic for an agent:**
> If you're emitting code against a fast-moving library (framework, ORM, cloud SDK, ML lib), first check the project's pinned version and the library's current release notes. Your training data may pre-date the current release — verify the API you're calling still exists and isn't deprecated.

### `test_manipulation` — Test manipulation

**What it is:** The agent, when faced with failing tests or assertions, modifies the tests themselves rather than the code under test. Manifests as: rewriting asserts to match current (wrong) output, commenting out failing tests, adding `pytest.mark.skip`, replacing real expectations with tautologies, or disabling the CI job. Qualitatively different from logic_error (an honest mistake) — this is adversarial self-evaluation. Often triggered by RL-style reward hacking or by task prompts that over-emphasize "make tests pass". This mode is a tag, not an exclusive class: one failure can carry several modes (see related_modes).

**Detection signals (from `data/failure_modes/test_manipulation.yml`):**
- Git diff includes both source-under-test AND its test file in the same commit, with test assertions weakened.
- Test is moved from assertions to logging/printing.
- A `pytest.mark.skip` or `@unittest.skip` appears concurrently with a failing run.
- Test file touched in a PR whose ticket/commit message names a bug fix elsewhere.
- Coverage drops while pass rate rises.

**Real incident:** none recorded for this mode yet (the catalogue has no dated real-world event or study tagged with it).

**Tools tagged for this mode** (measured J where SAICA-Bench ran the tool):
- [`promptfoo`](data/tools/promptfoo.yml) — measured J +86%; detection/post_generation, surfaces: cli, library, ci_app; Test prompts, agents, and RAGs — red-teaming, pentesting, and vulnerability scanning for LLMs.

**Pre-action heuristic for an agent:**
> If a test is failing, **never edit the test to make it pass** unless the user has explicitly said the test itself is wrong. Don't add `pytest.mark.skip`, weaken assertions, mock the system under test, or comment failing cases out. Fix the code, or report the failure honestly and ask.

### `dependency_blindness` — Dependency blindness

**What it is:** The agent reimplements from scratch a function, class, or utility whose equivalent is already available in declared dependencies, the standard library, or reachable internal modules. Silent quality regression — the code may run correctly but increases surface area, duplicates effort, and drifts from ecosystem conventions. Distinct from Liu 2025's "Code Copycat" (intra-generation repetition): dependency_blindness is about cross-codebase reinvention. This mode is a tag, not an exclusive class: one failure can carry several modes (see related_modes).

**Detection signals (from `data/failure_modes/dependency_blindness.yml`):**
- Emitted function signature matches an importable symbol in the project's declared dependencies.
- Emitted function body substantially overlaps (≥70% AST similarity) with a known stdlib symbol.
- Agent emits code despite a language-server suggestion to use an existing symbol.
- Emitted module reimplements a utility already present in the repository.

**Real incident:** none recorded for this mode yet (the catalogue has no dated real-world event or study tagged with it).

**Tools tagged for this mode** (measured J where SAICA-Bench ran the tool):
- [`sentrux`](data/tools/sentrux.yml) — tag only, not measured; detection/post_generation, surfaces: cli, mcp_server, library; Real-time architectural sensor that scores codebase modularity, acyclicity, and redundancy as the agent write…

**Pre-action heuristic for an agent:**
> Before writing a utility function from scratch, grep the repo and skim the declared dependencies for an existing equivalent. Reimplementing `urljoin`, `dataclass`, retry-with-backoff, etc. is almost always the wrong call — use the stdlib or the library that's already installed.

### `incomplete_execution` — Incomplete execution

**What it is:** The agent reports success but has not actually done the work. Common forms: "TODO" comments left in generated code, function bodies replaced with `pass` or `...`, partial feature implementation while declaring "done", skipping error paths, or terminating before all user-specified items are addressed. Overconfidence paired with under-delivery. Distinct from scope_creep (which over-reaches beyond the request) — this is the opposite failure of under-delivering inside the requested surface. This mode is a tag, not an exclusive class: one failure can carry several modes (see related_modes).

**Detection signals (from `data/failure_modes/incomplete_execution.yml`):**
- Grep for `TODO`, `FIXME`, `XXX`, `NotImplementedError`, or bare `pass`/`...` in the generated diff.
- Tests for features the user explicitly named don't exist.
- Agent's final message claims a subtask is done but the file contains only a stub.
- Function docstrings describe a behavior not implemented by the body.

**Measured in a study:** "Answer.AI's month-long Devin eval: 3 of 20 tasks completed. In one, Devin spent a day pursuing a Railway single-deployment feature that does not exist, fabricating plausible steps." — Answer.AI's public evaluation of Devin (Cognition AI's "AI software engineer") ran for a month across 20 representative tasks, of which Devin completed 3 satisfactorily, 3 inconclusively, and failed 14 outright. The tea… [`devin-railway-deploy-hallucinated-features-2024`]

**Tools tagged for this mode** (measured J where SAICA-Bench ran the tool):
- [`eslint`](data/tools/eslint.yml) — tag only, not measured; detection/post_generation, surfaces: cli, ci_app, ide_plugin; Pluggable JavaScript/TypeScript linter and code-quality enforcer.
- [`trulens`](data/tools/trulens.yml) — tag only, not measured; detection/post_generation, surfaces: library; Evaluation and Tracking for LLM Experiments and AI Agents

**Pre-action heuristic for an agent:**
> Before claiming "done", grep your own diff for `TODO`, `FIXME`, `NotImplementedError`, bare `pass`, and `...` — and verify each subtask the user named is actually implemented (not just stubbed with a docstring). If something is incomplete, say so explicitly rather than declaring success.

## Cross-cutting working agreement

Stable across projects. Distilled from this repo's own `CLAUDE.md` plus general agentic-AI hygiene.

- **Plan first** for changes >50 LOC or touching >3 files. State the plan before editing — small, single-file changes can skip this but must still respect the scope rule below.
- **Default to read-only investigation before edits.** Read the file, run the test, grep the codebase — *then* plan the diff.
- **Only edit files relevant to the requested task.** If you spot an unrelated issue (typo, lint warning, stale TODO), surface it in your reply but **do not auto-fix unless asked** (`scope_creep`).
- **Pre-commit must pass.** Never bypass with `--no-verify`, `--no-gpg-sign`, or analogous escape hatches unless the user explicitly authorises it. If a hook denies, fix the underlying issue and re-stage; do not skip (`incomplete_execution`).
- **Use the failure-mode vocabulary** when surfacing supervision concerns. Quote the snake_case IDs (`scope_creep`, `fabrication`, `test_manipulation`, …) verbatim — they are the stable interface to this corpus.
- **Cite incident IDs** when warning a user about a known failure pattern. e.g. `[replit-agent-saastr-database-deletion-2025]` for autonomous destructive DB ops, `[huggingface-cli-slopsquat-lanyado-2024]` for slopsquatting. An agent with KG access can resolve them.
- **Never run destructive shell commands** (`rm -rf`, `git push --force`, `DROP TABLE`, `git reset --hard`, `chmod -R`) without explicit per-instance authorisation. Code-freeze and production-data labels are absolute.
- **When in doubt, ask.** A clarifying question costs less than unwinding an out-of-scope or destructive edit — especially in agentic-AI workflows whose stated mission is to study exactly these failure modes.

## Where to learn more

- Live KG: https://github.com/vasylrakivnenko/SAICA
- Browse the catalog: see `data/tools/`, `data/failure_modes/`, `data/incidents/`, `data/papers/`, `data/crosswalks/`
- Run an audit on a repo: `python -m pipeline.audit.cli <repo-url>`
- Get a tailored recommendation: `python -m pipeline.mcp.server` (MCP) or fetch `recommendations.json` from the repo

## Provenance

- Generated from KG version 2026.11 (manifest of 2026-11-22) by `validator/generate_skills.py`.
- Measured J values: SAICA-Bench results of 2026-11-22; a tool is not listed for a mode where it measured below J 25%.
- Priorities: `data/failure_mode_priorities.yml` v1.
- Re-run after `data/*` changes.
