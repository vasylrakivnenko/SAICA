import { defineConfig } from 'astro/config';
import { fileURLToPath } from 'node:url';

// https://astro.build/config
export default defineConfig({
  output: 'static',
  site: 'https://saica-kg.dev',
  trailingSlash: 'ignore',
  vite: {
    server: {
      // Dev only: forward /api/* (ask, assess, health) to the Python backend
      // started by `python -m pipeline.webapp`. In production the same process
      // serves both the built site and /api, so no proxy is needed.
      proxy: {
        '/api': 'http://127.0.0.1:4322',
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
