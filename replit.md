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

## Optional backend is not configured

The static catalog, graph, recipes, and precomputed recommendations need no
secrets. The Ask and repository-audit pages render, but their submission forms
require the separate Python service described in `pipeline/ask/README.md`.
Ask additionally needs an AI service and semantic-retrieval prerequisites.
No credentials or replacement service values have been invented.
The imported forms still default to a local backend address and will need
same-origin routing when that service is enabled on Replit.
