# SAICA — supervision skill (Claude Code plugin)

A pure-skill plugin distilled from the
[SAICA-KG](https://github.com/vasylrakivnenko/SAICA) corpus. One file
of curated guidance the agent reads as context — no MCP server, no
Python dependency, no `.venv`.

What you get when this plugin is enabled:

- **Three pre-baked supervision-stack tiers** at the top of the skill —
  `minimum` (1 tool), `optimal` (3 tools), `full` (the MECE set
  covering all 11 failure modes). Same picks the SAICA recommender
  would return; embedded so no runtime call is needed.
- **Per-failure-mode pre-action heuristics** — for each of the 11
  known AI-coding failure modes (`fabrication`, `scope_creep`,
  `security_vulnerability`, etc.): what it is, detection signals,
  a real-world incident reference, the top 2 supervisors to install,
  and a hand-curated rule for the agent to follow before acting.
- **A cross-cutting working agreement** — plan first, scope-respect,
  no `--no-verify` bypass, cite incident IDs, ask when in doubt.

The skill is regenerated from the canonical `SKILLS.md` whenever the
KG corpus changes. CI drift gate keeps them in sync.

---

## Install (from a marketplace)

```text
/plugin marketplace add vasylrakivnenko/SAICA
/plugin install saica-supervise@saica-kg
```

That's it. No clone, no venv, no Python.

## Install (sideload, for development)

```bash
git clone https://github.com/vasylrakivnenko/SAICA
cd SAICA
claude --plugin-dir ./plugin
```

---

## What this plugin is NOT

- **It's not the MCP server.** SAICA-KG ships a real MCP server with
  `saica_lookup`, `saica_recommend(level | failure_modes)`, and audit
  tools — but that lives in the parent `saicakg` repo
  (`pipeline/mcp/`) and requires a Python install. We deliberately
  *don't* ship it via the marketplace because Python-deps inside a
  marketplace plugin are fragile (no `npm install`-grade UX).
- **It's not a runtime guard.** This is a context-injection skill.
  The agent reads it; what it does with the guidance is up to the
  agent. For runtime enforcement, see the recommended supervisors
  inside the skill (Dependabot, Semgrep, pre-commit, etc.) and
  install them in your repo.
- **It's not the audit (`saica_audit_repo`).** That lives at
  [`/assess`](https://saica-kg.dev/assess) on the public web app.

---

## What's in the file

After install, the agent has access to a single skill named
`saica-kg:saica-supervise` — call it explicitly with `/skills` (or
let the agent auto-invoke based on context). The body covers:

1. The three recommended supervision tiers (minimum / optimal / full)
2. Per-failure-mode sections (11 of them, priority-descending)
3. A cross-cutting working agreement
4. Pointers to the live KG, the audit web page, and the corpus

The skill is ~250 lines — small enough to fit any agent's context
budget, big enough to be useful per-action.

---

## Power-user setup (live MCP server)

If you want the live `saica_lookup` / `saica_recommend` MCP tools
(targeted FM queries, agent-kind filtering, etc.):

```bash
git clone https://github.com/vasylrakivnenko/SAICA
cd SAICA
python3 -m venv .venv
.venv/bin/pip install -r pipeline/requirements.txt
```

Then add to your `~/.claude.json`:

```jsonc
{
  "mcpServers": {
    "saica-kg": {
      "command": "/path/to/SAICA/.venv/bin/python",
      "args": ["-m", "pipeline.mcp.server"],
      "cwd": "/path/to/SAICA",
      "env": { "SAICA_AGENT_KIND": "claude-code" }
    }
  }
}
```

See [`pipeline/mcp/README.md`](../pipeline/mcp/README.md) for the
full power-user documentation.

---

## License

Apache-2.0 (code). CC-BY-4.0 (data, including the skill body).
