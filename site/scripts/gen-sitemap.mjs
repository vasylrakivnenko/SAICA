// Post-build: write dist/sitemap.xml from the built pages (every dist/**/index.html, canonical URL with a trailing
// slash), skipping pages marked noindex, and drop files that must never ship (Python bytecode caches).
//   node scripts/gen-sitemap.mjs              (run by `npm run build` after `astro build`)
//   node scripts/gen-sitemap.mjs <out dir>    (for a build made with `astro build --outDir <out dir>`)
import { readdirSync, readFileSync, writeFileSync, statSync, rmSync, existsSync } from 'node:fs';
import { join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE = 'https://saica.ai';
const DIST = process.argv[2] ? resolve(process.argv[2]) : fileURLToPath(new URL('../dist/', import.meta.url));

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === '__pycache__') { rmSync(p, { recursive: true, force: true }); continue; }
      walk(p, out);
    } else if (name === 'index.html') out.push(p);
  }
  return out;
}

if (!existsSync(DIST)) throw new Error(`no build output at ${DIST}`);
const urls = [];
for (const file of walk(DIST)) {
  const html = readFileSync(file, 'utf8');
  if (/<meta\s+name="robots"\s+content="[^"]*noindex/i.test(html)) continue;
  const rel = relative(DIST, file).split(sep).join('/').replace(/index\.html$/, '');
  urls.push(`${SITE}/${rel}`);
}
// Home first, then section hubs, then the rest alphabetically.
const rank = (u) => (u === `${SITE}/` ? 0 : u.split('/').length <= 5 ? 1 : 2);
urls.sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.map((u) => `  <url><loc>${u}</loc></url>`).join('\n')}
</urlset>
`;
writeFileSync(join(DIST, 'sitemap.xml'), xml);
console.log(`sitemap.xml: ${urls.length} URLs`);
