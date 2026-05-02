# SAICA-KG — Claude Code plugin

A Claude Code plugin that ships:

1. **An MCP server** (`saica-kg`) exposing two tools the agent can call:
   - `saica_lookup(tool_id)` — full facets for one supervisor in the
     SAICA-KG corpus
   - `saica_recommend(level | failure_modes)` — minimum / optimal /
     full / targeted set of recommended supervisors for the asking
     agent's stack
2. **A skill** (`saica-supervise`) — per-action heuristics for the 11
   known AI-coding-agent failure modes (fabrication, scope_creep,
   security_vulnerability, etc.). The agent reads it like any other
   skill file; no service call.

The plugin is the *agent-side* surface of SAICA-KG. The web app
(`/leaderboard`, `/assess`, `/tool-coverage`) remains separate and
exists for human consumption.

---

## Prerequisites

- Claude Code (any recent version with plugin support).
- Python 3.12+ on PATH **or** a project virtualenv at `<repo>/.venv/`.
- This repo cloned somewhere on disk — the plugin lives at
  `<repo>/plugin/` and reaches into the parent for the actual MCP
  server code and KG data.

Install Python deps once:

```bash
cd /path/to/saicakg
python3 -m venv .venv
.venv/bin/pip install -r pipeline/requirements.txt
```

The `bin/saica-mcp` wrapper prefers `<repo>/.venv/bin/python` if it
exists, falls back to system `python3` otherwise.

---

## Install (sideload, dev / single-user)

```bash
cd /path/to/saicakg
claude --plugin-dir ./plugin
```

Or, for persistent install in your `~/.claude.json`, add:

```jsonc
{
  "plugins": [
    { "path": "/path/to/saicakg/plugin" }
  ]
}
```

(Exact key depends on your Claude Code version — see
`claude plugin --help` for the canonical syntax.)

---

## Verify it loaded

After Claude Code starts with the plugin enabled:

- The MCP server `saica-kg` should appear in `/mcp` (or equivalent
  command). It exposes `saica_lookup` and `saica_recommend`.
- The skill `saica-kg:saica-supervise` should be visible. The agent
  may auto-invoke it, or you can invoke explicitly.

Quick MCP smoke test from the command line:

```bash
cd /path/to/saicakg
.venv/bin/python -c "from pipeline.mcp.server import mcp; print(mcp)"
```

---

## What stays in sync, automatically

The skill body (`skills/saica-supervise/SKILL.md`) is regenerated from
the canonical `SKILLS.md` whenever you run:

```bash
python -m validator.generate_skills
```

The CI drift gate (`generate_skills --check`) covers both files, so
the plugin can't ship a stale skill.

---

## Why a plugin (vs just an MCP config + a CLAUDE.md drop)?

- One install — users get the MCP server **and** the skill in one
  step instead of two manual setups.
- Namespaced — invocations become `saica-kg:saica-supervise`, no
  collision with other plugins or local rules.
- Versioned — `plugin.json` carries identity Claude Code can track.
- The same wiring works across machines once the parent repo is
  cloned and `.venv/` is set up.

---

## Distribution (future)

For sideload (today): cloners install via `--plugin-dir`. For wider
distribution, the plugin can be published in a marketplace
(GitHub repo with a `marketplace.json`); not in this commit.
