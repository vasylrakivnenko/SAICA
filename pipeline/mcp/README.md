# SAICA-KG MCP server

Three tools for MCP-speaking coding agents (Claude Code first, Cursor / Replit
follow):

| Tool | What it does | When to call it |
|---|---|---|
| `saica_lookup(tool_id)` | Returns the full `ToolRecord` for one SAICA-KG tool. | When you want the facets / surfaces / paradigm of a specific tool. |
| `saica_preflight(action, context?, agent_kind?)` | Returns risk failure modes + 2-3 supervisor recommendations for a proposed agent action. **Hot path** — keyword classification, no LLM call. | Before any non-trivial action: edit, install, shell, commit, network fetch. |
| `saica_audit_repo(repo_url)` | One-shot supervision-coverage audit of a public GitHub repo. Delegates to `pipeline.audit`. | At session start, on the user's repo. |

All three return Pydantic objects defined in `pipeline/audit/schemas.py`.

---

## Run it

```bash
cd /Users/vasyl/saicakg
.venv/bin/python -m pipeline.mcp.server
```

That starts the server on stdio. It prints nothing until an MCP client
connects (that's expected — stdio servers are silent in idle).

Smoke test without a client:

```bash
.venv/bin/python -c "from pipeline.mcp.server import mcp; print(mcp)"
```

---

## Wire it into Claude Code

Claude Code reads MCP servers from one of two places:

1. **Project-scoped** — `<repo>/.mcp.json`. Only enabled inside that repo.
2. **User-scoped** — `~/.claude.json` under the `mcpServers` key. Available
   in every Claude Code session.

> Note: Claude **Desktop** uses `~/Library/Application Support/Claude/claude_desktop_config.json`.
> Claude **Code** is the CLI; its config lives under `~/.claude/` or in
> `.mcp.json` next to your project. The snippets below work for either —
> the JSON shape is the same.
> If you're unsure where your install reads from, run `claude mcp list` after
> adding the entry; if your version doesn't have that subcommand, add it via
> `claude mcp add` and let the CLI pick the location.

Copy-pasteable snippet — the same content is in `mcp_config.example.json`:

```json
{
  "mcpServers": {
    "saica-kg": {
      "command": "/Users/vasyl/saicakg/.venv/bin/python",
      "args": ["-m", "pipeline.mcp.server"],
      "cwd": "/Users/vasyl/saicakg"
    }
  }
}
```

For other machines, change `command` to your venv's Python and `cwd` to
your local checkout of `saicakg`.

CLI alternative (if your Claude Code build supports it):

```bash
claude mcp add saica-kg \
  /Users/vasyl/saicakg/.venv/bin/python -- \
  -m pipeline.mcp.server
```

---

## Three example tool calls

### 1. Look up `semgrep`

```jsonc
// from the agent
{ "name": "saica_lookup", "arguments": { "tool_id": "semgrep" } }
```

Returns a `ToolRecord` with `control_paradigm: "detection"`,
`integration_surfaces: ["cli", "ci_app", "library"]`, and the failure modes
Semgrep declares coverage for (`dependency_blindness`,
`security_vulnerability`).

### 2. Preflight `pip install left-pad` from Claude Code

```jsonc
{
  "name": "saica_preflight",
  "arguments": {
    "action": "pip install left-pad",
    "agent_kind": "claude-code"
  }
}
```

Returns `risk_failure_modes: ["supply_chain_attack", "dependency_blindness"]`
and 2-3 supervisor recommendations preferring `cli` / `ci_app` / `library`
surfaces (since `claude-code` is CLI-first).

### 3. Audit a GitHub repo

```jsonc
{
  "name": "saica_audit_repo",
  "arguments": { "repo_url": "https://github.com/langfuse/langfuse" }
}
```

Returns an `AuditReport` (detected stack + coverage grid + ranked gaps +
Markdown rendering). Note: this delegates to `pipeline.audit.audit_repo`,
which is built in parallel; if it's not yet ready you'll get a clear
"analyzer module isn't ready" error.

---

## Tests

```bash
.venv/bin/python -m pytest pipeline/mcp/tests/ -q
```
