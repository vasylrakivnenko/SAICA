import { defineConfig } from 'astro/config';
import { fileURLToPath } from 'node:url';

// https://astro.build/config
export default defineConfig({
  output: 'static',
  // Astro's HTML compression drops a line break between a word and an inline tag on the next line
  // ("on\n<a>GitHub</a>" -> "onGitHub"), gluing words to links site-wide. Keep the whitespace.
  compressHTML: false,
  site: 'https://saica.ai',
  trailingSlash: 'ignore',
  vite: {
    server: {
      // Dev only: forward the dynamic endpoints to the Python backend, but
      // let Astro serve its own /api/v1 catalog routes.
      proxy: {
        '^/api/(ask|assess|health)/?(?:\\?|$)': 'http://127.0.0.1:4322',
      },
    },
    define: {
      'import.meta.env.KG_DATA_DIR': JSON.stringify(
        fileURLToPath(new URL('../data/', import.meta.url)),
      ),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5000,
    allowedHosts: true,
  },
  build: {
    format: 'directory',
  },
});
