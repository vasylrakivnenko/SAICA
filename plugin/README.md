# SAICA — supervision skill (Claude Code plugin)

One skill file built from the
[SAICA](https://github.com/vasylrakivnenko/SAICA) catalog. The agent reads
it as context. No MCP server, no Python, no `.venv`.

What the skill contains:

- **Three tool stacks built from the catalog's tags**: one tool, three
  tools, and the fewest tools whose tags name every failure mode that is
  left after the measured floor. A tag is what a tool says it addresses;
  it is not a measurement. Where SAICA-Bench measured a tool, the skill
  shows the result, and a tool is never listed for a failure mode on which
  it measured below the floor. Measured picks: <https://saica.ai/tool-coverage/>.
- **A section per failure mode** (`fabrication`, `scope_creep`,
  `security_vulnerability` and eight more): what it is, signals to look
  for, a documented case where the catalog has one, catalog tools tagged
  for it, and a rule to follow before acting.
- **A working agreement**: plan first, stay in scope, never bypass commit
  hooks with `--no-verify`, ask when in doubt.

The skill is generated (`python -m validator.generate_skills`);
`tests/test_skill_copies_in_sync.py` fails when the copy in this plugin is
not the generator's output.

---

## Install (from a marketplace)

```text
/plugin marketplace add vasylrakivnenko/SAICA
/plugin install saica-supervise@saica-kg
```

## Install (sideload, for development)

```bash
git clone https://github.com/vasylrakivnenko/SAICA
cd SAICA
claude --plugin-dir ./plugin
```

After install the skill is named `saica-supervise:saica-supervise`.

---

## What this plugin is not

- **Not the MCP server.** The repository has a small MCP server with two
  tools, `saica_lookup` and `saica_recommend`. It needs Python, so it is
  not shipped through the marketplace; see below.
- **Not a runtime guard.** The skill is text the agent reads. What the
  agent does with it is up to the agent. To enforce something, install a
  tool that checks it.
- **Not the audit.** The repository audit is a web page,
  <https://saica.ai/assess/>, and a command
  (`python -m pipeline.audit.cli <repo-url>`). There is no MCP audit tool.

---

## The MCP server (needs a clone and Python)

```bash
git clone https://github.com/vasylrakivnenko/SAICA
cd SAICA
python3 -m venv .venv
.venv/bin/pip install -r requirements/mcp.txt -c requirements/constraints.txt
.venv/bin/python -m pipeline.mcp.server --help
```

Then add it to `~/.claude.json` (replace `<repo>` with the path of your clone):

```jsonc
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

See [`pipeline/mcp/README.md`](../pipeline/mcp/README.md).

---

## License

Apache-2.0 for the code. The licence of the data and of the skill text is
stated in the repository's README.
