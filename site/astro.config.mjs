import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

// https://astro.build/config
export default defineConfig({
  output: 'static',
  site: 'https://saica-kg.dev',
  integrations: [tailwind({ applyBaseStyles: false })],
  trailingSlash: 'ignore',
  server: {
    host: '0.0.0.0',
    port: 5000,
    allowedHosts: true,
  },
  build: {
    format: 'directory',
  },
});
