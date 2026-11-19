---
name: External CLI review pairing
description: Run a requested Codex and Claude Code cross-review without mixing workspace edits or losing partial progress.
---

When asked to use Codex and Claude Code together, confirm both versions and
paths, review a clean local clone of the exact commit, and run changes in
small edit batches before integrating the verified patch.

**Why:** In this workspace a stale Nix Codex executable shadowed a newer
standalone executable on PATH. Broad CLI edit and review runs also timed out
after making partial changes, while narrowly scoped batches completed.

**How to apply:** Check the standalone executable if the PATH version cannot
run the requested CLI mode. Save reviewer outputs, give reviewers read-only
access, and use bounded write batches for implementers. If a batch times out,
inspect its diff; a written change may still contain unresolved helper calls.

For CAO pilots, a healthy HTTP server does not prove that its process can
find tmux. Check the server log on session-creation errors; a separate
loopback-only instance started with the workspace PATH can test the setup
without changing the user's running server.

An opt-in CAO instance must isolate both its persisted state and its tmux
socket and clear an inherited tmux pane context. **Why:** CAO startup
reconciles sessions against tmux; a different HTTP port alone does not keep
that reconciliation away from an existing tmux server. **How to apply:** use
a private `TMUX_TMPDIR` with a separate CAO home and verify that a test
session and an unrelated same-named session can coexist.

CAO's Codex allowlist is advisory: name a native read-only Codex config and
never select unrestricted tools. Use the actual `cao-` session name for status
and cleanup. Prefer a bounded inline diff when Codex cannot read the frozen
patch in its shell sandbox.

**Why:** Without a named native config, CAO 2.5.4 launches Codex with its
sandbox bypassed. A local shell sandbox probe can also fail on this runtime's
Bubblewrap capabilities independently of CAO or provider login.

**How to apply:** Pass the exact small patch as named-session input rather
than weakening the sandbox or attempting handoff outside a CAO supervisor.
