// Post-build link check: every internal link in the built pages must point to something that was built.
//   node scripts/check-links.mjs [out dir]      (default: dist; `npm run check:links` after `npm run build`)
//
// Reads every .html file under the out dir and checks each href / src that stays on the site: the target
// file must exist, and a "#fragment" must be an id on the target page. Skipped: other sites, mailto: and
// data: URLs, and the Python backend's routes (/api/ask, /api/assess, /api/health), which are not static files.
// Links that scripts create in the browser are not seen here; scripts/check-public-data.mjs covers their data.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const DIST = process.argv[2] ? resolve(process.argv[2]) : fileURLToPath(new URL('../dist/', import.meta.url));
if (!existsSync(DIST)) throw new Error(`no build output at ${DIST}`);

const BACKEND = /^\/api\/(ask|assess|health)(\/|$)/;

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (name.endsWith('.html')) out.push(p);
  }
  return out;
}

/** File that serves a site path, or null. "/a/" -> a/index.html; "/a" -> a, a.html or a/index.html. */
function fileFor(pathname) {
  const rel = decodeURIComponent(pathname).replace(/^\/+/, '');
  const candidates = pathname.endsWith('/')
    ? [join(DIST, rel, 'index.html')]
    : [join(DIST, rel), join(DIST, `${rel}.html`), join(DIST, rel, 'index.html')];
  return candidates.find((c) => existsSync(c) && statSync(c).isFile()) ?? null;
}

// Inline scripts hold link templates ("/tools/${id}"), not links: leave them out of the scan.
const withoutScripts = (html) => html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');

// The home page's leaderboard tabs are chosen by the URL fragment in its script (/#security, /#overview), so
// they are not element ids. The valid ones are the mode ids in bench/results.json.
function leaderboardTabs() {
  const file = join(DIST, 'bench', 'results.json');
  if (!existsSync(file)) return [];
  const results = JSON.parse(readFileSync(file, 'utf8'));
  return ['overview', ...(results.modes ?? []).map((m) => m.id), ...(results.star_modes ?? []).map((m) => m.id)];
}

const idCache = new Map();
function idsOf(file) {
  if (!idCache.has(file)) {
    const html = withoutScripts(readFileSync(file, 'utf8'));
    const ids = new Set([...html.matchAll(/\s(?:id|name)="([^"]+)"/g)].map((m) => m[1]));
    if (file === join(DIST, 'index.html')) for (const tab of leaderboardTabs()) ids.add(tab);
    idCache.set(file, ids);
  }
  return idCache.get(file);
}

const pages = walk(DIST);
if (!existsSync(join(DIST, 'index.html'))) {
  // An empty or half-written out dir must not pass as "no broken links".
  console.log(`check-links: no index.html in ${DIST}; the build did not finish`);
  process.exit(1);
}
const problems = [];
let checked = 0;
for (const page of pages) {
  const html = withoutScripts(readFileSync(page, 'utf8'));
  // The page's own URL path, so relative links resolve the way a browser resolves them.
  const self = '/' + relative(DIST, page).split(sep).join('/').replace(/index\.html$/, '');
  const from = relative(DIST, page).split(sep).join('/');
  for (const m of html.matchAll(/\s(?:href|src)="([^"]*)"/g)) {
    const raw = m[1].replace(/&amp;/g, '&');
    if (!raw || /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(raw)) continue; // other sites, mailto:, data:, javascript:
    let url;
    try {
      url = new URL(raw, `https://site.invalid${self}`);
    } catch {
      problems.push(`${from}: unparsable link "${raw}"`);
      continue;
    }
    if (BACKEND.test(url.pathname)) continue;
    checked += 1;
    const target = fileFor(url.pathname);
    if (!target) {
      problems.push(`${from}: "${raw}" -> no such page or file`);
      continue;
    }
    const fragment = decodeURIComponent(url.hash.slice(1));
    if (fragment && target.endsWith('.html') && !idsOf(target).has(fragment)) {
      problems.push(`${from}: "${raw}" -> no element with id "${fragment}" on ${relative(DIST, target).split(sep).join('/')}`);
    }
  }
}

if (problems.length) {
  console.log(`check-links: ${problems.length} broken internal link(s) in ${pages.length} pages:`);
  for (const p of [...new Set(problems)].sort()) console.log(`  - ${p}`);
  process.exit(1);
}
console.log(`check-links: OK, ${checked} internal links in ${pages.length} pages all resolve (${DIST})`);
