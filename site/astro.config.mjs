import { defineConfig } from 'astro/config';
import { fileURLToPath } from 'node:url';

// https://astro.build/config
export default defineConfig({
  output: 'static',
  site: 'https://saica-kg.dev',
  trailingSlash: 'ignore',
  vite: {
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
