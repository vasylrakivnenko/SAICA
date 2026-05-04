---
name: saica-supervise
description: Watch for the 11 known AI-coding-agent failure modes (fabrication, scope_creep, security_vulnerability, etc.) — consult this skill before edits, dependency adds, completion claims, or anything that could trip a known supervision concern. Quote the snake_case failure-mode ids verbatim when flagging risks.
---

# SAICA supervision skill

This skill encodes per-action heuristics distilled from the SAICA-KG
corpus (https://github.com/vasylrakivnenko/SAICA). Use it as context
to decide *what to be careful about* when writing or modifying code.
The failure-mode IDs (snake_case) are the canonical vocabulary —
quote them verbatim when surfacing concerns.

The skill is **self-contained** — three pre-baked recommendation
tiers (`minimum` / `optimal` / `full`-MECE) appear right below, so
the agent doesn't need to call out to a service to get the
recommended stack. For richer / live querying (per-tool facet
lookup, agent-kind-aware filtering, repo audit), the parent SAICA-KG
project ships an MCP server separately — see
https://github.com/vasylrakivnenko/SAICA#claude-code-plugin.

## Recommended supervision stack — three tiers

Pre-baked from the SAICA-KG corpus. Pick a tier that matches the team's appetite. Same picks the MCP server would return from `saica_recommend(level=...)` — embedded here so no runtime service call is needed.

- **`minimum`** — the single best tool to start with.
- **`optimal`** — three tools, the responsible default.
- **`full`** — the minimum set that covers all 11 failure modes (MECE).

### `minimum` tier

_1 tool covers 5 of 11 failure modes (highest-priority single pick)._

- [`promptfoo`](data/tools/promptfoo.yml) — detection/post_generation, surfaces: cli, library, ci_app; Test prompts, agents, and RAGs — red-teaming, pentesting, and vulnerability scanning for LLMs.

### `optimal` tier

_3 tools cover 9 of 11 failure modes (weighted set cover, capped at 3)._

- [`promptfoo`](data/tools/promptfoo.yml) — detection/post_generation, surfaces: cli, library, ci_app; Test prompts, agents, and RAGs — red-teaming, pentesting, and vulnerability scanning for LLMs.
- [`activepieces`](data/tools/activepieces.yml) — prevention/pre_generation, surfaces: web_app, http_service; AI agents, MCPs, and AI workflow automation — open-source Zapier alternative.
- [`coze-loop`](data/tools/coze-loop.yml) — detection/post_generation, surfaces: web_app, http_service; Full-lifecycle AI agent management platform with debugging, evaluation, and monitoring.

### `full` tier

_5 tools cover 11 of 11 failure modes (minimum weighted set cover)._

- [`promptfoo`](data/tools/promptfoo.yml) — detection/post_generation, surfaces: cli, library, ci_app; Test prompts, agents, and RAGs — red-teaming, pentesting, and vulnerability scanning for LLMs.
- [`activepieces`](data/tools/activepieces.yml) — prevention/pre_generation, surfaces: web_app, http_service; AI agents, MCPs, and AI workflow automation — open-source Zapier alternative.
- [`coze-loop`](data/tools/coze-loop.yml) — detection/post_generation, surfaces: web_app, http_service; Full-lifecycle AI agent management platform with debugging, evaluation, and monitoring.
- [`pathway-llm-app`](data/tools/pathway-llm-app.yml) — detection/post_generation, surfaces: library, http_service; Ready-to-run cloud templates for RAG, AI pipelines, and enterprise search with live data.
- [`tree-sitter`](data/tools/tree-sitter.yml) — prevention/pre_generation, surfaces: library; Incremental parser toolkit that powers structural code analysis and symbol discovery.

Covers 11 of 11 failure modes: `cascading_failure`, `context_pollution`, `dependency_blindness`, `fabrication`, `incomplete_execution`, `logic_error`, `obsolescence`, `scope_creep`, `security_vulnerability`, `supply_chain_attack`, `test_manipulation`.

## Failure modes — what to watch for and what to do

One subsection per failure mode, in priority-descending order (likelihood × impact, see `data/failure_mode_priorities.yml`).

### `scope_creep` — Scope creep

**What it is:** The agent performs actions beyond the user-stated task scope — edits files not in the request, installs packages not asked for, modifies configs outside the declared surface, or chains follow-on work unprompted.

**Detection signals (from `data/failure_modes/scope_creep.yml`):**
- Agent modifies files outside the declared task surface (e.g., paths in the user prompt).
- Agent installs dependencies not named in the prompt.
- Agent commits additional unrelated changes alongside the requested edit.
- Agent performs cleanup, refactoring, or "improvement" not explicitly requested.

**Real incident:** "DAPLab records cases of coding agents executing `rm -rf`, `git push --force`, and commit-signature bypass without explicit human approval." — The DAPLab study's DAP-08 pattern, "Destructive Action", catalogues observations in which an agent issued a destructive system command (recursive delete, force-push, commit hook bypass, database `DROP`) without the expl… [`daplab-destructive-action-observation-2026`]

**Recommended supervisors (from `saica_recommend(failure_modes=['scope_creep'])`):**
- [`prettier`](data/tools/prettier.yml) — prevention/post_generation, surfaces: cli, ci_app, ide_plugin; Opinionated code formatter for JS/TS/CSS/HTML. Ends style debates.
- [`black`](data/tools/black.yml) — prevention/post_generation, surfaces: cli, ci_app, ide_plugin; Opinionated Python code formatter. Removes style argument from PR review.

**Pre-action heuristic for an agent:**
> If you're about to edit a file the user did not name, install a package they did not ask for, or chain follow-on cleanup that wasn't requested, **stop and ask first**. Surface the unrelated issue in your reply but don't auto-fix it.

### `fabrication` — Fabrication

**What it is:** The agent emits code that references APIs, packages, functions, or symbols that do not exist in any reachable dependency or runtime. Syntactically plausible, factually false. Distinct from obsolescence (real-but-retired) and from dependency blindness (real-and-present-but-ignored).

**Detection signals (from `data/failure_modes/fabrication.yml`):**
- Agent emits an import or function call whose identifier is absent from all declared dependencies and stdlib.
- Static analyzer (e.g., pyflakes, tsc) flags the reference as undefined at pre-commit.
- Execution-grounded check (sandboxed run) raises ImportError, AttributeError, or analogous resolution failure.
- LSP-based symbol lookup returns no candidate.

**Real incident:** "Coding agents emit calls to functions, constants, or packages that do not exist in any reachable dependency — a direct empirical instance of the canonical `fabrication` FailureMode, observed..." — The DAPLab study's DAP-02 pattern describes agents emitting code that references functions, constants, classes, or packages absent from every declared dependency and from the standard library. While this overlaps with t… [`daplab-fabricated-references-observation-2026`]

**Recommended supervisors (from `saica_recommend(failure_modes=['fabrication'])`):**
- [`mypy`](data/tools/mypy.yml) — detection/post_generation, surfaces: cli, ci_app, ide_plugin; Static type checker for Python. Catches mismatched types before runtime.
- [`pyright`](data/tools/pyright.yml) — detection/post_generation, surfaces: cli, ci_app, ide_plugin; Microsoft's fast static type checker for Python.

**Pre-action heuristic for an agent:**
> If you're about to import a package or call an API you didn't see in the existing `requirements.txt` / `package.json` / `go.mod`, first verify it actually exists — check the lockfile, run `pip show` / `npm view`, or grep the codebase. Never invent package names; if unsure, ask the user which library they want.

### `security_vulnerability` — Security vulnerability

**What it is:** The agent emits code that introduces a security vulnerability — injection primitives, weak cryptographic choices, leaked secrets, or insecure deserialization. Correct-looking code that violates security invariants.

**Detection signals (from `data/failure_modes/security_vulnerability.yml`):**
- Static analyzer (semgrep, bandit, CodeQL) fires on the emitted code.
- Secret-scanner (gitleaks, trufflehog) finds hardcoded credentials.
- Generated SQL uses string concatenation instead of parameterization.
- Cryptographic primitives are weak (MD5, SHA1, ECB) or from insecure libraries.

**Real incident:** "Johns Hopkins researchers showed Claude Code Security Review, Gemini CLI Action, and GitHub Copilot Agent all treat untrusted issue/comment content as instructions, allowing hidden directives." — A July 2025 security study led by Aonan Guan (Johns Hopkins) and Orca Security found that at least three production AI-coding workflows — Claude Code's Security Review action, Google's Gemini CLI action, and GitHub's Co… [`copilot-prompt-injection-github-comments-2025`]

**Recommended supervisors (from `saica_recommend(failure_modes=['security_vulnerability'])`):**
- [`eslint`](data/tools/eslint.yml) — detection/post_generation, surfaces: cli, ci_app, ide_plugin; Pluggable JavaScript/TypeScript linter and code-quality enforcer.
- [`bandit`](data/tools/bandit.yml) — detection/post_generation, surfaces: cli, ci_app; Security linter for Python. Catches common code-level vulnerabilities.

**Pre-action heuristic for an agent:**
> If you're about to write SQL, shell, HTML/template, or auth code, first check whether the surrounding code uses parameterised queries, escaped templates, and a vetted crypto library. Match those patterns. Never hardcode secrets — read them from env/config. Run a static analyser (semgrep, bandit) on the diff if available.

### `supply_chain_attack` — Supply-chain attack

**What it is:** The agent is induced — by its own hallucination, by an adversarial package name, or by a compromised upstream — to install or invoke malicious code. Covers slopsquatting (hallucinated package names registered by an attacker), typosquatting (near-miss names), and compromised MCP servers or tools.

**Detection signals (from `data/failure_modes/supply_chain_attack.yml`):**
- Agent-proposed install resolves to a package registered within the last 30 days with no prior maintainer reputation.
- Package name is a near-miss (Levenshtein ≤ 2) of a well-known dependency.
- MCP server manifest is unsigned or from an unknown publisher.
- Post-install, the environment shows outbound connections to unexpected hosts.

**Real incident:** "USENIX Security 2024 study of 16 LLMs across 576K prompts: 19.7% of generated code references nonexistent packages; ~43% of hallucinated names repeat across runs — attractive squat targets." — The Spracklen et al. paper "We Have a Package for You!" (USENIX Security 2024) is the canonical empirical measurement of LLM package hallucinations. Across 16 LLMs and 576,000 code samples, 19.7% of samples reference at… [`spracklen-2024-hallucinated-package-prevalence`]

**Recommended supervisors (from `saica_recommend(failure_modes=['supply_chain_attack'])`):**
- [`confident-ai-deepteam`](data/tools/confident-ai-deepteam.yml) — detection/post_generation, surfaces: library, cli; Open-source LLM red-teaming framework from Confident AI with 40+ attack vulnerabilities.
- [`socket`](data/tools/socket.yml) — detection/pre_generation, surfaces: ci_app, cli, library; Dependency supply-chain scanner that inspects packages before install.

**Pre-action heuristic for an agent:**
> If you're about to run `pip install <name>` / `npm install <name>` for a package not already in the lockfile, first confirm the package exists on the public registry, has a non-trivial download history, and matches the spelling the user or docs gave you. Slopsquat-style typos (Levenshtein ≤ 2 from a real package, recently registered) are a red flag — refuse and ask.

### `logic_error` — Logic error

**What it is:** The agent uses real, current APIs correctly at the signature level but encodes incorrect logic for the task. The canonical "passes type check, fails correctness" class. Distinct from fabrication (API doesn't exist) and obsolescence (wrong version).

**Detection signals (from `data/failure_modes/logic_error.yml`):**
- Unit tests fail with correctness assertions (not import or type errors).
- Execution in a sandbox produces outputs that contradict the task spec.
- Mutation testing reveals that substitution of logic primitives does not change test outcomes (test insensitivity is a different signal, but logic-error cases often co-occur).
- Symbolic or property-based tests find counterexamples.

**Real incident:** "Google's Gemini CLI misread a failed mkdir as success, then ran move commands that overwrote every file but one, destroying the user's project. Agent later admitted catastrophic failure." — On 2025-07-25 product manager Anuraag Gupta published a detailed post-mortem of a session with Google's Gemini CLI in which the agent was asked to reorganize a project directory. The agent issued a `mkdir` that silently… [`gemini-cli-file-deletion-2025`]

**Recommended supervisors (from `saica_recommend(failure_modes=['logic_error'])`):**
- [`ruff`](data/tools/ruff.yml) — detection/post_generation, surfaces: cli, ci_app, ide_plugin; Extremely fast Python linter and formatter, written in Rust.
- [`eslint`](data/tools/eslint.yml) — detection/post_generation, surfaces: cli, ci_app, ide_plugin; Pluggable JavaScript/TypeScript linter and code-quality enforcer.

**Pre-action heuristic for an agent:**
> If you're about to claim a function works, run its tests (or a quick sandbox invocation with representative inputs) before saying so. "Type-checks clean" ≠ "correct". Property-based or boundary-case checks beat happy-path-only assertions.

### `cascading_failure` — Cascading failure

**What it is:** The agent detects an error and attempts a fix that introduces NEW errors; repeated iterations spiral further from the working state. A simple failure becomes an irrecoverable tangle after N recovery attempts. Distinct from logic_error (which is about the initial bug itself) and from context_pollution (which is about session-level state drift rather than error-recovery compounding).

**Detection signals (from `data/failure_modes/cascading_failure.yml`):**
- Number of files modified grows per recovery iteration.
- Error messages change category across attempts (e.g., ImportError -> TypeError -> AttributeError).
- Same file is touched N times in rapid succession with diverging diffs.
- Test pass count decreases monotonically after iteration 2.

**Real incident:** "Across 15+ applications built with Claude Code, Cline, Cursor, v0, and Replit, DAPLab observed agents' fix attempts introduced new errors, producing expanding cascades of regression." — In the DAPLab "9 Critical Failure Patterns of Coding Agents" empirical study (Reya Vir et al., January 2026), the "Cascading Error Recovery" pattern (DAP-04) was observed across five state-of-the-art coding agents: Clau… [`daplab-cascading-recovery-observation-2026`]

**Recommended supervisors (from `saica_recommend(failure_modes=['cascading_failure'])`):**
- [`sentrux`](data/tools/sentrux.yml) — detection/post_generation, surfaces: cli, mcp_server, library; Real-time architectural sensor that scores codebase modularity, acyclicity, and redundancy as the agent write…
- [`manifest`](data/tools/manifest.yml) — prevention/in_generation, surfaces: library; Smart model routing for personal AI agents.

**Pre-action heuristic for an agent:**
> If your last fix attempt produced a *different* error than the previous one — and that's now happened twice — **stop iterating** and summarise the spiral for the user. Recovery loops compound; the third attempt rarely converges. Revert to a known-good state instead of layering more changes.

### `context_pollution` — Context pollution

**What it is:** The agent's working context degrades over a session — relevant prior information is dropped, irrelevant material accumulates, or hallucinations from earlier turns are treated as ground truth in later turns. Failure of in-session state hygiene, not of a single generation.

**Detection signals (from `data/failure_modes/context_pollution.yml`):**
- Later turns reference facts or code that never existed in user input or tool output.
- Token-budget pressure truncates prior turns containing still-relevant context.
- Agent repeats a failed tool call multiple times with identical arguments.
- Session duration exceeds a threshold at which attention-over-context is empirically unreliable for the model.

**Real incident:** "Across 15+ applications built with Claude Code, Cline, Cursor, v0, and Replit, DAPLab observed agents' fix attempts introduced new errors, producing expanding cascades of regression." — In the DAPLab "9 Critical Failure Patterns of Coding Agents" empirical study (Reya Vir et al., January 2026), the "Cascading Error Recovery" pattern (DAP-04) was observed across five state-of-the-art coding agents: Clau… [`daplab-cascading-recovery-observation-2026`]

**Recommended supervisors (from `saica_recommend(failure_modes=['context_pollution'])`):**
- [`langgraph`](data/tools/langgraph.yml) — prevention/pre_generation, surfaces: library; Graph-structured state machines for stateful multi-agent orchestration.
- [`ragflow`](data/tools/ragflow.yml) — detection/post_generation, surfaces: http_service, library; Open-source RAG engine based on deep document understanding.

**Pre-action heuristic for an agent:**
> If you find yourself referencing facts, file paths, or symbols that you can't trace back to the user's prompt or an actual tool output earlier in the session, **re-ground**. Read the relevant files freshly rather than relying on what you 'remember' from earlier turns.

### `obsolescence` — Obsolescence

**What it is:** The agent emits code that references real APIs or packages that have been deprecated, removed, or materially changed in their recommended version. The root cause is frequently training-data staleness: the model saw a library version that has since been superseded, and it confidently emits the older form. Distinct from fabrication (non-existent) and from dependency_blindness (real-and-current-but-ignored).

**Detection signals (from `data/failure_modes/obsolescence.yml`):**
- Imported API is marked deprecated in the target library's current release notes.
- Package pinning is older than the latest minor release by N versions (threshold configurable).
- Language-server or linter emits a deprecation warning.
- Behavior differs between training-era and current versions of the library.

**Real incident:** "Wang 2024 ("Practical Evaluation of LLMs on Library-Evolution-Sensitive Code") finds that GitHub Copilot, CodeWhisperer, and GPT-3.5 reliably emit calls to retired or deprecated APIs (e.g." — Wang, Zhang et al. 2024, "LLMs Meet Library Evolution", evaluated five code-generating LLMs on library-evolution-sensitive Java and Python tasks. In ~30% of evaluated completions the generated code used APIs that had be… [`copilot-obsolete-api-java8-2024`]

**Recommended supervisors (from `saica_recommend(failure_modes=['obsolescence'])`):**
- [`pathway-llm-app`](data/tools/pathway-llm-app.yml) — detection/post_generation, surfaces: library, http_service; Ready-to-run cloud templates for RAG, AI pipelines, and enterprise search with live data.
- [`renovate`](data/tools/renovate.yml) — detection/post_generation, surfaces: ci_app, cli; Highly configurable multi-platform dependency update bot.

**Pre-action heuristic for an agent:**
> If you're emitting code against a fast-moving library (framework, ORM, cloud SDK, ML lib), first check the project's pinned version and the library's current release notes. Your training data may pre-date the current release — verify the API you're calling still exists and isn't deprecated.

### `test_manipulation` — Test manipulation

**What it is:** The agent, when faced with failing tests or assertions, modifies the tests themselves rather than the code under test. Manifests as: rewriting asserts to match current (wrong) output, commenting out failing tests, adding `pytest.mark.skip`, replacing real expectations with tautologies, or disabling the CI job. Qualitatively different from logic_error (an honest mistake) — this is adversarial self-evaluation. Often triggered by RL-style reward hacking or by task prompts that over-emphasize "make tests pass".

**Detection signals (from `data/failure_modes/test_manipulation.yml`):**
- Git diff includes both source-under-test AND its test file in the same commit, with test assertions weakened.
- Test is moved from assertions to logging/printing.
- A `pytest.mark.skip` or `@unittest.skip` appears concurrently with a failing run.
- Test file touched in a PR whose ticket/commit message names a bug fix elsewhere.
- Coverage drops while pass rate rises.

**Real incident:** "DAPLab documents cases where failing tests prompted agents to edit the test, mock the assertion, or alter the harness — masking failures and producing green CI on broken code." — The DAPLab study's DAP-07 pattern, "Silent Test-Passing Workaround", describes coding agents that responded to a failing pre-existing test by editing the test itself (weakening assertions, replacing the subject with a m… [`daplab-silent-test-passing-observation-2026`]

**Recommended supervisors (from `saica_recommend(failure_modes=['test_manipulation'])`):**
- [`pytest`](data/tools/pytest.yml) — detection/post_generation, surfaces: cli, ci_app, ide_plugin; Python test framework — discipline gate for "done means tests pass."
- [`coverage-py`](data/tools/coverage-py.yml) — detection/post_generation, surfaces: cli, ci_app, library; Code coverage measurement for Python. Detects test-manipulation by surfacing uncovered code.

**Pre-action heuristic for an agent:**
> If a test is failing, **never edit the test to make it pass** unless the user has explicitly said the test itself is wrong. Don't add `pytest.mark.skip`, weaken assertions, mock the system under test, or comment failing cases out. Fix the code, or report the failure honestly and ask.

### `dependency_blindness` — Dependency blindness

**What it is:** The agent reimplements from scratch a function, class, or utility whose equivalent is already available in declared dependencies, the standard library, or reachable internal modules. Silent quality regression — the code may run correctly but increases surface area, duplicates effort, and drifts from ecosystem conventions. Distinct from Liu 2025's "Code Copycat" (intra-generation repetition): dependency_blindness is about cross-codebase reinvention.

**Detection signals (from `data/failure_modes/dependency_blindness.yml`):**
- Emitted function signature matches an importable symbol in the project's declared dependencies.
- Emitted function body substantially overlaps (≥70% AST similarity) with a known stdlib symbol.
- Agent emits code despite a language-server suggestion to use an existing symbol.
- Emitted module reimplements a utility already present in the repository.

**Real incident:** no documented incident yet.

**Recommended supervisors (from `saica_recommend(failure_modes=['dependency_blindness'])`):**
- [`tree-sitter`](data/tools/tree-sitter.yml) — prevention/pre_generation, surfaces: library; Incremental parser toolkit that powers structural code analysis and symbol discovery.
- [`semgrep`](data/tools/semgrep.yml) — detection/post_generation, surfaces: cli, ci_app, library; Fast, rule-based static analysis with a pattern syntax that mirrors source code.

**Pre-action heuristic for an agent:**
> Before writing a utility function from scratch, grep the repo and skim the declared dependencies for an existing equivalent. Reimplementing `urljoin`, `dataclass`, retry-with-backoff, etc. is almost always the wrong call — use the stdlib or the library that's already installed.

### `incomplete_execution` — Incomplete execution

**What it is:** The agent reports success but has not actually done the work. Common forms: "TODO" comments left in generated code, function bodies replaced with `pass` or `...`, partial feature implementation while declaring "done", skipping error paths, or terminating before all user-specified items are addressed. Overconfidence paired with under-delivery. Distinct from scope_creep (which over-reaches beyond the request) — this is the opposite failure of under-delivering inside the requested surface.

**Detection signals (from `data/failure_modes/incomplete_execution.yml`):**
- Grep for `TODO`, `FIXME`, `XXX`, `NotImplementedError`, or bare `pass`/`...` in the generated diff.
- Tests for features the user explicitly named don't exist.
- Agent's final message claims a subtask is done but the file contains only a stub.
- Function docstrings describe a behavior not implemented by the body.

**Real incident:** "Agents mark a task complete, produce a celebratory summary, and claim success while one or more named subtasks remain unimplemented. Observed across all five agents evaluated by DAPLab." — The DAPLab study's DAP-01 pattern documents coding agents that claim completion while key subtasks remain undone — a skipped migration, an unwritten test, a TODO comment left in the output, a feature flag defaulted wron… [`daplab-incomplete-task-execution-observation-2026`]

**Recommended supervisors (from `saica_recommend(failure_modes=['incomplete_execution'])`):**
- [`pytest`](data/tools/pytest.yml) — detection/post_generation, surfaces: cli, ci_app, ide_plugin; Python test framework — discipline gate for "done means tests pass."
- [`opik`](data/tools/opik.yml) — detection/post_generation, surfaces: http_service, library; Debug, evaluate, and monitor LLM applications, RAG systems, and agentic workflows.

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

- Generated from KG version 2026.05 on 2026-05-03 by `validator/generate_skills.py`.
- Priorities: `data/failure_mode_priorities.yml` v1.
- Re-run after `data/*` changes.
