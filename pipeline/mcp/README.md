# SAICA MCP server

A local MCP server (stdio) with two tools for coding agents. It runs as a
subprocess of your agent; nothing is hosted.

| Tool | What it returns |
|---|---|
| `saica_lookup(tool_id)` | One catalog entry: paradigm, phase, autonomy level, integration surfaces, the failure modes the tool is tagged for, the path of its page on the site. |
| `saica_recommend(level?, failure_modes?)` | Catalog tools ranked by their tags. `level`: `"minimum"` (1 tool), `"optimal"` (3 tools, the default) or `"full"` (as many as add a failure mode). Or `failure_modes=[…]`: up to 3 tagged tools per mode. |

## What the ranking is, and what it is not

- A **tag** (`addresses_failure_modes`) is what a tool says it deals with.
  It is a claim, not a measurement.
- The ranking multiplies an editorial weight per failure mode
  (`data/failure_mode_priorities.yml`) by the tool's **popularity**:
  `log10(stars + 1)` plus an adjustment for its maintenance status. Star
  counts in the catalog can be months old.
- The one measured input: a tool is never returned for a failure mode on
  which SAICA-Bench measured it below the floor (J 0.25 today), and an
  archived tool is never returned. After that rule a mode can be left with
  no tool; `full` then lists it under `uncovered_failure_modes` and
  `coverage_complete` is `false`.
- For picks based on measurements, use <https://saica.ai/tool-coverage/>.

`saica_lookup` accepts only ids of catalog tools (lower-case letters,
digits, hyphens). Anything else is an error.

Call `saica_recommend` once when you set a project up, not during a task.

## Install and run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements/mcp.txt -c requirements/constraints.txt

.venv/bin/python -m pipeline.mcp.server --help   # prints help and exits
.venv/bin/python -m pipeline.mcp.server          # serves on stdio
```

The server prints nothing until an MCP client connects.

## Wire it into Claude Code

Claude Code reads MCP servers from `<project>/.mcp.json` (that project
only) or from `~/.claude.json` under `mcpServers` (every session). The
snippet is also in [`mcp_config.example.json`](mcp_config.example.json);
replace `<repo>` with the path of your clone:

```json
{
  "mcpServers": {
    "saica-kg": {
      "command": "<repo>/.venv/bin/python",
      "args": ["-m", "pipeline.mcp.server"],
      "cwd": "<repo>"
    }
  }
}
```

Or: `claude mcp add saica-kg <repo>/.venv/bin/python -- -m pipeline.mcp.server`
(run it from `<repo>`).

Optional: `"env": {"SAICA_AGENT_KIND": "claude-code"}`. It names the coding
agent that asks, so that no coding agent is ever recommended to it. The
catalog holds no coding agents today, so the setting changes nothing.

## Example calls

```jsonc
{ "name": "saica_lookup", "arguments": { "tool_id": "semgrep" } }
```

```jsonc
{ "name": "saica_recommend", "arguments": { "failure_modes": ["scope_creep", "fabrication"] } }
// → { "mode": "targeted", "agent_kind": null,
//     "by_failure_mode": { "scope_creep": [ … up to 3 … ], "fabrication": [ … ] } }
```

Order within a mode: prevention and detection tools before correction and
recovery, then tools whose catalog entry names the mode, then stars.

```jsonc
{ "name": "saica_recommend", "arguments": { "level": "full" } }
// → { "mode": "full", "level": "full", "agent_kind": null,
//     "tools": [ … ],
//     "covered_failure_modes": [ … ], "uncovered_failure_modes": [ … ],
//     "coverage_complete": false,
//     "summary": "6 tools; their tags name 10 of 11 failure modes (a tag is the tool's claim, not a measurement)." }
```

The numbers in that summary are an example; they change with the catalog.

## Tests

```bash
.venv/bin/python -m pytest pipeline/mcp/tests/ -q
```

They run on a fixture catalog and on fixed "measured" results, so they do
not depend on the catalog's current content.
