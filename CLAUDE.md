# SAICA-KG — Claude Code working agreement

This file is read by Claude Code on every session in this repo. It encodes
the project's first **prevention**-paradigm supervisor: a written contract
that blocks bad outputs *before* they are generated rather than catching
them after the fact.

KG citations (so the supervision-on-supervision chain is auditable):

- `data/failure_modes/scope_creep.yml` — the failure mode this file
  primarily guards against.
- `data/failure_modes/incomplete_execution.yml` — the "pre-commit must
  pass" rule below.
- `data/tools/semgrep.yml`, `data/tools/dependabot.yml` — sibling
  supervisors; the citation style here mirrors theirs.

---

## Plan first

For any change > 50 LOC or touching > 3 files, propose a plan in chat
**before** editing. Maps to `scope_creep` — preventing over-action by
forcing an explicit boundary up front.

Small changes (single file, single concern) can skip the plan step but
must still respect the scope rule below.

## Scope

Only edit files relevant to the requested task. If you discover an
unrelated issue (typo in a comment, lint error in another module, stale
TODO), surface it in your reply but **do not auto-fix unless asked**.

Files explicitly off-limits unless the task names them:

- `pipeline/audit/`, `pipeline/mcp/`, `pipeline/ask/`, `validator/` —
  owned by other agents or treated as stable.
- `data/` — KG content. Schema-driven; needs a separate review pass.

## Pre-commit must pass

Before claiming a task complete, run:

```bash
pre-commit run --files <changed paths>
```

(Or just `git commit` and let the hook fire.) If a hook denies, log the
denial so the prevention layer is observable:

```bash
python -m pipeline.supervision log \
    --tool-id <hook-id> \
    --failure-mode <fm-id> \
    --mechanism "blocked-commit-via-pre-commit" \
    --detail "<short, e.g. file:line message>" \
    --invoked-by claude-code-hook
```

After fixing the underlying issue, re-stage and commit. Do not bypass
hooks with `--no-verify`.

## Tool denials log to `.saica/prevention_log/`

Wired via `.claude/hooks/log_pretool.sh`, which fires on Claude Code's
`PreToolUse` event and records denials as JSONL. The file format is
documented in `pipeline/supervision/logger.py`. The log directory is
gitignored; events stay developer-local.

To enable the hook, point Claude Code at it from your personal
`.claude/settings.local.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      { "command": ".claude/hooks/log_pretool.sh" }
    ]
  }
}
```

## Test discipline

- Run `python -m pytest pipeline/supervision/tests -q` after changing
  anything under `pipeline/supervision/`.
- Run `python validator/cli.py` after changing anything under `data/` to
  confirm the KG still validates with 0 errors.

## When in doubt

Ask. The cost of one clarifying question is far below the cost of
unwinding an out-of-scope edit, especially in a project whose stated
mission is to study exactly this failure mode.
