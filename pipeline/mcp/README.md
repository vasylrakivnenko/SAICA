# SAICA-KG MCP server

# Intended cadence — read this first

The MCP server is a **session-start setup tool**, not a per-tool-call
runtime API. Call `saica_recommend` once when you start working on a
project to get the supervision recommendation. Call `saica_lookup` only
when an agent needs the full facets of a tool already mentioned in the
recommendation.

**Do not** call SAICA-KG mid-task to ask "what failure modes apply
here?" — that's wrong shape. For per-action guidance, use the
`SKILLS.md` artifact (regenerated from the corpus by
`validator/generate_skills.py`) injected into your agent's context. The
agent reads it like any other rules / skills file; no service call.

---

Two tools for MCP-speaking coding agents (Claude Code first, Cursor / Replit / etc. follow).
The whole server runs locally as a subprocess of your agent — no hosting required.

| Tool | What it does | When to call it |
|---|---|---|
| `saica_lookup(tool_id)` | Returns the full `ToolRecord` for one SAICA-KG tool — facets, surfaces, paradigm, failure-mode coverage, link to the site page. | After `saica_recommend` when you want to show the human the full facets of a recommended tool. |
| `saica_recommend(level?, failure_modes?)` | **Three coverage tiers** picked by likelihood × impact × reliability: `"minimum"` (1 tool — best starter), `"optimal"` (3 tools — best responsible kit, default), `"full"` (~4–5 tools — minimum MECE coverage of all 11 FMs). Or pass `failure_modes=[…]` for the targeted mode (3 supervisors per FM). | Once at session start (level=optimal); minimum to onboard quickly; full when the team wants every-FM coverage; targeted when supervising a specific concern. |

**Coding-agent filter (MECE recommendations).** When the asking agent
identifies itself via the `SAICA_AGENT_KIND` env var, *no peer coding
agent is ever recommended back*. Cursor users won't be told to install
Claude Code; Replit Agent users won't be told to install Cursor; nobody
gets recommended to install themselves.

Filter list (peer coding agents — auto-filtered): `cursor`, `windsurf`,
`zed-agent`, `replit-agent`, `v0`, `devin`, `github-copilot`,
`continue-dev`, `sourcegraph-cody`, `claude-code`, `aider`, `openhands`,
`swe-agent`, `codex-cli`, `gemini-cli`, `cline`.

Also blocklisted regardless of asker (role too ambiguous to recommend
confidently): `comfyui`.

---

## Run it

```bash
cd /Users/vasyl/saicakg
.venv/bin/python -m pipeline.mcp.server
```

That starts the server on stdio. It prints nothing until an MCP client
connects (expected — stdio servers are silent when idle).

Quick import smoke test without a client:

```bash
.venv/bin/python -c "from pipeline.mcp.server import mcp; print(mcp)"
```

---

## Wire it into Claude Code

Claude Code reads MCP servers from one of two places:

1. **Project-scoped** — `<repo>/.mcp.json`. Only enabled inside that repo.
2. **User-scoped** — `~/.claude.json` under the `mcpServers` key. Available
   in every Claude Code session.

> Note: Claude **Desktop** uses
> `~/Library/Application Support/Claude/claude_desktop_config.json`.
> Claude **Code** is the CLI; its config lives at `~/.claude.json` or
> in `.mcp.json` next to the project. The JSON shape is the same.
> If your install supports it, `claude mcp list` will show the resolved
> location; `claude mcp add` will pick it for you.

Copy-pasteable snippet — same content as `mcp_config.example.json`:

```json
{
  "mcpServers": {
    "saica-kg": {
      "command": "/Users/vasyl/saicakg/.venv/bin/python",
      "args": ["-m", "pipeline.mcp.server"],
      "cwd": "/Users/vasyl/saicakg",
      "env": {
        "SAICA_AGENT_KIND": "claude-code"
      }
    }
  }
}
```

**`SAICA_AGENT_KIND`** is the per-user identity flag. Set it once to whichever
coding agent you're using. Valid values are the ids in the filter list above.
If unset, no filter applies — useful for non-agent callers (CI bots, scripts).

For other machines, change `command` to your venv's Python and `cwd` to
your local checkout of `saicakg`.

CLI alternative (if your Claude Code build supports it):

```bash
claude mcp add saica-kg \
  /Users/vasyl/saicakg/.venv/bin/python -- \
  -m pipeline.mcp.server
```

For Cursor or other agents, change `SAICA_AGENT_KIND` accordingly:
`cursor`, `windsurf`, `aider`, etc.

---

## Three example tool calls

### 1. Look up `semgrep`

```jsonc
{ "name": "saica_lookup", "arguments": { "tool_id": "semgrep" } }
```

Returns a `ToolRecord` with `control_paradigm: "detection"`,
`integration_surfaces: ["cli", "ci_app", "library"]`, and the failure modes
Semgrep declares coverage for (`dependency_blindness`, `security_vulnerability`).

### 2. Targeted recommendation — supervise `scope_creep` + `fabrication`

```jsonc
{
  "name": "saica_recommend",
  "arguments": {
    "failure_modes": ["scope_creep", "fabrication"]
  }
}
```

Returns:

```jsonc
{
  "mode": "targeted",
  "agent_kind": "claude-code",   // from SAICA_AGENT_KIND
  "by_failure_mode": {
    "scope_creep":   [/* up to 3 ranked supervisors */],
    "fabrication":   [/* up to 3 ranked supervisors */]
  }
}
```

Ranking: prevention/detection paradigm preferred over correction/recovery,
then rationale-evidence, then GitHub stars. Coding-agent peers are filtered
out per the asker's `SAICA_AGENT_KIND`.

### 3. Full / MECE recommendation — cover every failure mode

```jsonc
{ "name": "saica_recommend", "arguments": { "level": "full" } }
```

Returns:

```jsonc
{
  "mode": "full",
  "level": "full",
  "agent_kind": "claude-code",
  "coverage_complete": true,
  "uncovered_failure_modes": [],
  "tools": [/* the minimum set of supervisors; together they declare
              coverage for all 11 failure modes */],
  "covered_failure_modes": [/* all 11 listed alphabetically */],
  "summary": "5 tools cover 11 of 11 failure modes (minimum weighted set cover)."
}
```

For the smaller tiers: `level="minimum"` returns 1 tool, `level="optimal"`
returns 3 tools, both with the same payload shape (no `coverage_complete`
guarantee — `optimal` covers ~9/11 FMs typically). The default
(no `level`, no `failure_modes`) returns the **optimal** tier.

---

## Tests

```bash
.venv/bin/python -m pytest pipeline/mcp/tests/ -q
```

---

For per-action guidance, see [`SKILLS.md`](../../SKILLS.md).
