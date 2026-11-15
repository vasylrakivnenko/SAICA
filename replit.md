# Running SAICA-KG on Replit

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
- Install website dependencies: `npm --prefix site ci`.
- Build the static website: `npm --prefix site run build`. Output: `site/dist/`.
  The build regenerates TypeScript definitions from the existing schemas.
- Astro configuration resolves the catalog's absolute data path before bundling,
  so both development and production builds load the original YAML corpus.

## Ask / Assess backend

- `python3 -m pipeline.webapp` runs the FastAPI backend from `pipeline/ask/`
  under `/api` (`/api/ask`, `/api/assess`, `/api/health`). It is started by the
  **Ask backend** workflow, which the **Run** button starts alongside the website.
- In development it listens on `127.0.0.1:4322`; Astro's dev server proxies
  `/api` to it (`site/astro.config.mjs`), so the pages call it same-origin.
- LLM: if `HYPERBOLIC_API_KEY` is set (Replit Secret), the backend uses
  Hyperbolic's OpenAI-compatible API with `ASK_MODEL` (default
  `deepseek-v4.1-flash`). Explicit `AZURE_KIMI_*` variables take precedence.
- Retrieval uses a local sentence-transformers index in `.cache/embeddings/`,
  built automatically on startup when missing or older than `data/`.
- Python deps: `pip install torch --index-url https://download.pytorch.org/whl/cpu`
  then `pip install -r pipeline/requirements-web.txt`.
- `SAICA_ASK_BUDGET` caps LLM calls per server process (default 50; resets on restart).

## Publishing

- Autoscale deployment (switched from Static so /ask and /assess work in
  production). One process, `pipeline.webapp` with `SERVE_STATIC=1`, serves the
  built site and `/api` on port 5000.
- Build: installs CPU-only torch and `pipeline/requirements-web.txt`, builds the
  site, and builds the embeddings index. See `[deployment]` in `.replit`.
- `HYPERBOLIC_API_KEY` must be available to the deployment (Replit Secrets).
- Publishing settings take effect only when the user publishes again.
