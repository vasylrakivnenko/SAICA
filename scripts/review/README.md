# On-demand Claude → Codex patch review

The supervisor (the person running this procedure) owns scope, tests, and the
integration decision. Claude edits one disposable clone; Codex reviews one
frozen patch in a separate named CAO session. None of these steps commits,
pushes, or publishes. Run the commands from the main repository root in Bash.

## One-time setup

1. Check `command -v claude codex cao cao-server tmux`, `claude --version`,
   `codex --version`, and `cao --version`. The examples use CAO 2.5.4 and Codex
   0.170.0. If a stale Codex shadows the intended binary, fix `PATH` **before**
   starting CAO; the server/tmux must see the same tools. Use authenticated
   provider CLIs with a trusted configuration (no writable MCP servers, hooks,
   or sandbox overrides for the reviewer). Never forward app secrets to agents.
2. For this account, install the named Codex configuration and CAO profile:

   ```bash
   codex_home="${CODEX_HOME:-$HOME/.codex}"
   mkdir -p "$codex_home"
   cp -i scripts/review/saica-review-read-only.config.toml "$codex_home/"
   cao profile validate scripts/review/saica-patch-reviewer.md
   cao install scripts/review/saica-patch-reviewer.md --provider codex
   ```

   Do not reuse a conflicting config. Check that the installed profile names
   `saica-review-read-only` and its config sets `sandbox_mode = "read-only"`
   and `approval_policy = "never"`. CAO's tool allowlist is advisory for
   Codex: it does **not** replace the native sandbox. Never use `--yolo`,
   `--allowed-tools '*'`, or a generic CAO reviewer profile; they can cause
   Codex to launch with its sandbox disabled.
3. Use a running local CAO server; `cao session list` checks connectivity.
   If none is running, start it in a separate terminal with the verified
   `PATH` and provider configuration, without the application's secrets:

   ```bash
   env -u HYPERBOLIC_API_KEY -u SESSION_SECRET \
     cao-server --host 127.0.0.1 --port 9889
   ```

   Do not expose the server publicly. If session creation fails despite a
   responsive server, check its log and verify it can find `tmux` and Codex.

## 1. Give Claude one small edit batch

Agree on the exact file paths, intended behavior, and checks before starting.
Only committed `HEAD` is cloned, not local changes in the main repository.

```bash
RUN=$(python3 scripts/review_batch.py prepare validator/cli.py) || exit 1
(
  cd "$RUN/edit" || exit 1
  env -u HYPERBOLIC_API_KEY -u SESSION_SECRET timeout 300s claude --print --safe-mode \
    --tools 'Read,Glob,Grep,Edit,Write' --permission-mode acceptEdits \
    'Only edit validator/cli.py. <Replace this with the agreed change and acceptance criteria.>
     Do not run tests or perform Git or deployment operations.
     Stop after this batch and summarize the changes.'
) >"$RUN/claude.log" 2>&1
```

Use the real paths and instructions instead of the example. For a timeout or
nonzero exit, read the log and inspect the partial diff before doing anything
with it. Discard it or finish the batch and capture a new candidate; never
assume it is complete. The supervisor may use `git -C "$RUN/edit" add -N --
path/to/new-file` for an intended new file already in the agreed scope.

## 2. Review the exact candidate in Codex

```bash
REVIEW=$(python3 scripts/review_batch.py capture "$RUN") || exit 1
read -r BASE SHA < <(python3 scripts/review_batch.py verify "$REVIEW") || exit 1
SESSION="cao-saica-review-${RUN##*/}-${REVIEW##*/}"
```

`candidate.patch` is the exact binary-capable Git patch; it is not a summary
or a diff Codex must regenerate. The reviewer starts in the snapshot
directory, which has the patch but no edit checkout. Inspect the patch before
sending it to the provider; don't include credentials or unrelated work.

From the supervisor terminal, launch a **named session** with the snapshot
as input. Do not try `cao agent handoff` outside an active CAO supervisor
terminal: that was refused in the pilot.

```bash
PROMPT=$(python3 scripts/review_batch.py prompt "$REVIEW") || exit 1
timeout 360s cao launch --agents saica-patch-reviewer --provider codex \
  --session-name "$SESSION" --working-directory "$REVIEW" --headless \
  -- "$PROMPT" \
  2>&1 | tee "$RUN/$SESSION.log"
review_status=${PIPESTATUS[0]}
```

The inline prompt contains the exact patch bytes between its markers, and
Codex needs no shell access to review them. The helper rejects unsafe terminal
characters and caps inline input at 8,000 patch bytes. If it rejects the
patch, split the batch or use file input on a host with a working native
Codex sandbox. For file input, replace the `PROMPT` assignment with:

```bash
PROMPT="Read the complete candidate.patch without changing it. Base: $BASE.
Expected SHA-256: $SHA. Compute and report its hash and your findings."
```

Do not bypass the sandbox if file input fails. If Codex is waiting at a
sign-in or trust prompt, resolve it manually before starting a fresh review.

Launch confirmation is not a completed review. Accept only a successful,
complete reply with the expected SHA-256 (an identifier for inline input, a
computed hash for file input) and findings (or explicit no
findings). If `review_status` is nonzero or the reply is missing, inspect
`cao session status "$SESSION"` and `tmux attach-session -t "$SESSION"` before
retrying, and save the final reply in the run log if needed. An expired CLI
wait may leave the session running. Never substitute a truncated copy. If
the patch is too large for a complete review, split the work into smaller
batches and review each new snapshot. After saving the reply, stop only this
session with `cao shutdown --session "$SESSION"`.

## 3. Test and approve manually

1. Resolve reviewer findings. Any edit after capture means a new capture
   and review. Verify again, run the task-specific checks **in the isolated
   clone** (for graph changes, e.g. `python3 validator/cli.py` and focused
   tests), save the commands and results, and verify again after testing.
   If checks fail, do not integrate. The supervisor records the candidate
   digest, review outcome, test results, and explicit approval together.
2. After approval only, in the intended integration checkout, confirm its
   `HEAD` is still `$BASE` and `git status --short` is empty. Verify the
   candidate again and apply that exact patch, not a copied approximation:

   ```bash
   python3 scripts/review_batch.py verify "$REVIEW" &&
     test "$(git rev-parse HEAD)" = "$BASE" &&
     test -z "$(git status --porcelain)" &&
     git apply --check "$REVIEW/candidate.patch" &&
     git apply "$REVIEW/candidate.patch"
   ```

   If the base changed or the patch doesn't apply cleanly, start a new batch
   at the intended base. Inspect the final diff. Committing, pushing, and
   publishing are separate manual decisions.
3. Runs and logs are in the ignored `.saica/reviews/` directory. Retain
   the reviewed patch and evidence as needed; delete the specific batch
   directory manually when you no longer need it.
