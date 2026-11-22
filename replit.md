# Running SAICA-Bench and SAICA-KG on Replit

> **The public site is not deployed from Replit.** Since 2026-11-21 the plan is a static build on Cloudflare
> Pages (settings: README, "Deploying the site (Cloudflare Pages)"). This file describes Replit as a workspace:
> the dev server, the optional backend and the CAO swarm. The "Publishing" section at the end describes the
> earlier Replit deployment and is kept only for reference.

- The existing Astro website lives in `site/`. The knowledge graph remains in
  the repository's `data/` directory; no database is needed to browse it.
- Use the **Run** button to start the **Start website** workflow.
- Manual start from the repository root: `npm --prefix site run dev`.
- The development server binds to `0.0.0.0:5000` and accepts Replit preview hosts.
- Node.js 22.23.4 or newer is required by Astro 7. The imported Astro 5 releases
  were blocked by the package security policy, so Astro and Node were upgraded
  with user approval. Tailwind 3 is preserved through PostCSS.
- `--ignore-lock` keeps Astro in the foreground under Replit's managed workflow;
  otherwise Astro can auto-background itself in an agent environment.
- Install website dependencies: `npm --prefix site ci`. The Node version is
  pinned in `site/.nvmrc` (22).
- Build the static website: `npm --prefix site run build`. Output: `site/dist/`.
  The build regenerates TypeScript definitions from the existing schemas and
  stops when a file under `site/public` names an id that is not in `data/`.
- Type check: `npm --prefix site run check`. Link check after a build:
  `npm --prefix site run check:links`.
- Astro configuration resolves the catalog's absolute data path before bundling,
  so both development and production builds load the original YAML corpus.

## Ask / Assess backend

- `python3 -m pipeline.webapp` is the one entry point of the FastAPI backend
  (`--help` prints help). It serves `/api/ask`, `/api/assess` and `/api/health`
  (which answers `{"ok": true}` and nothing else). It is started by the
  **Ask backend** workflow, which the **Run** button starts alongside the website.
- `/api/assess` reads a public repository through the GitHub API. It does not
  use `git`; it needs outbound https to `api.github.com` and
  `raw.githubusercontent.com`.
- In development it listens on `127.0.0.1:4322`; Astro's dev server proxies
  `/api` to it (`site/astro.config.mjs`), so the pages call it same-origin.
- LLM: if `HYPERBOLIC_API_KEY` is set (Replit Secret), the backend uses
  Hyperbolic's OpenAI-compatible API with `ASK_MODEL` (default
  `deepseek-v4.1-flash`). Explicit `AZURE_KIMI_*` variables take precedence.
- Retrieval uses a local sentence-transformers index in `.cache/embeddings/`.
  The deployment build pre-builds it; at runtime it is (re)built lazily on the
  first Ask request when missing or older than `data/`, never before the port
  opens, so health checks are not blocked.
- Python deps: `pip install torch --index-url https://download.pytorch.org/whl/cpu`
  then `pip install -r pipeline/requirements-web.txt`. That file points at
  `requirements/web.txt`, where the list lives.
- `SAICA_ASK_BUDGET` caps questions per UTC day (default 50). The count lives
  in the server process, so it also starts again on a restart. The other
  limits and their defaults are in `pipeline/ask/README.md`.

### Proxy setting a backend deployment must set (since 2026-11-21)

This matters only where the Python backend itself is deployed behind a proxy. A static site on Cloudflare
Pages has no backend and needs nothing from this section.

The web service believes `X-Forwarded-For` / `X-Forwarded-Proto` only from peers listed in
`FORWARDED_ALLOW_IPS`. The default is loopback only (it was `*`). Behind Replit's proxy the deployment `run`
command in `.replit` has to set it: `FORWARDED_ALLOW_IPS=*` if the proxy is the only way to reach the app, or
the proxy's address range. Without it the service is safe but strict: no HSTS header is sent and all visitors
share one hourly limit for Ask and one for Assess. To find the proxy's address, make one request to the deployed
app and read the peer address in the uvicorn access log. `.replit` is not changed by this repository's fix round.

## Local CAO swarm

- CAO is opt-in: start it from the workspace **Shell**, not with **Run** or
  publishing. The launcher uses the shell's `tmux` and looks for CAO in
  `.local/bin` and on `PATH`. If CAO is missing, the tested upstream revision
  can be installed as a standalone CLI tool:
  `uv tool install git+https://github.com/awslabs/cli-agent-orchestrator.git@b2b366688e22918409b9e92b48096120eafa1e69`.
- Start the foreground server from the repository root:
  `bash scripts/cao-local.sh serve`. Leave that shell open. In another shell,
  check it with `curl --fail --noproxy '*' http://127.0.0.1:9897/health`,
  then run `bash scripts/cao-local.sh client --help` for CAO commands. Use the
  `client` wrapper instead of bare `cao` to target this instance. Real workers
  still need their own provider CLI and credentials.
- The server binds only to `127.0.0.1:9897`. Do not forward this port or add
  it to Replit's port mappings. This instance stores its own profiles and
  sessions under the ignored `.local/state/cao-swarm/` directory and uses a
  separate tmux socket; it does not import or change existing CAO sessions.
  To see its tmux sessions from the repository root:
  `env -u TMUX -u TMUX_PANE TMUX_TMPDIR="$PWD/.local/state/cao-swarm/tmux" tmux list-sessions`.
- Press Ctrl+C in the server shell to stop the API. tmux sessions are separate
  from the API process; use the `client` wrapper to delete only the sessions
  you no longer need while the API is running.

## Publishing (the earlier Replit deployment; not the current plan)

- Autoscale deployment (switched from Static so /ask and /assess work in
  production). One process, `pipeline.webapp` with `SERVE_STATIC=1`, serves the
  built site and `/api` on port 5000.
- Build: installs CPU-only torch and `pipeline/requirements-web.txt`, builds the
  site, and builds the embeddings index. See `[deployment]` in `.replit`.
- The build installs the newest versions that fit the requirement file; nothing
  is pinned. Tested versions are in `requirements/constraints.txt`. To use them,
  add `-c requirements/constraints.txt` to both `pip install` commands of the
  build line in `.replit` (not done: deployment settings are the owner's).
- Two more deployment settings to decide (also the owner's, in `.replit`): add
  `HF_HUB_OFFLINE=1` to the `run` command so the first Ask on a cold instance
  does not contact huggingface.co; and consider one instance at most, because
  the daily budgets are counted per process.
- After publishing, check the deployment with
  `bash scripts/smoke_check.sh https://saica.ai`.
- `HYPERBOLIC_API_KEY` must be available to the deployment (Replit Secrets).
- Publishing settings take effect only when the user publishes again.
