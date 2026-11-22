// Proof that no benchmark value is typed into a page: build the site from a changed copy of the results file
// and check that every benchmark page follows the changed file.
//   node scripts/check-results-mutation.mjs [--keep] [--dist <existing build>]   (`npm run check:mutation`)
//
// Nothing in the repository is written: the changed copy and the build go to a temp dir, and the build reads
// the copy through SAICA_RESULTS_JSON (astro.config.mjs). --keep leaves the temp dir for inspection.
//
// What is changed in the copy:
//   mode A (first mode with a tied top group): every row's J, interval, TPR, FPR and cost; a row from outside
//     the top group becomes the single winner; title, summary, tier, tier label, ranking sentence, tuning
//     disclosure and the number of bad samples.
//   mode B (first mode with a winner): put under the floor, so nobody may be named.
//   mode C (second mode with a winner, if any): winner removed, top group of two.
//   file level: version, cite_as, floor, prevalences, first finding, first caveat, method.setting, method.metric,
//     first threat, the label of the "model" kind, the sample count.
// What is checked: the new values of mode A and the file-level values are on the pages, the old ones are gone.
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { elementsWith, fileStrings, htmlFiles, pagePath, read, visibleText, withoutFileStrings } from './bench-check-lib.mjs';

const SITE = fileURLToPath(new URL('..', import.meta.url));
const KEEP = process.argv.includes('--keep');
const original = JSON.parse(readFileSync(join(SITE, 'public/bench/results.json'), 'utf8'));
const R = structuredClone(original);

// The site's number formats (src/lib/format.ts), repeated here so the check does not import what it checks.
const MINUS = '−';
const signedPct = (x, d = 1) => {
  const s = (Math.abs(x) * 100).toFixed(d);
  return (Number(s) === 0 ? '' : x < 0 ? MINUS : '+') + s + '%';
};
const pct = (x, d = 1) => {
  const s = (Math.abs(x) * 100).toFixed(d);
  return (x < 0 && Number(s) !== 0 ? MINUS : '') + s + '%';
};
const int = (n) => n.toLocaleString('en-US');
const r4 = (x) => Math.round(x * 1e4) / 1e4;
const mode = (id) => R.modes.find((m) => m.id === id);
/** Set the given fields on one object of the copy. */
const set = (target, fields) => { for (const [k, v] of Object.entries(fields)) target[k] = v; };
const ref = (r) => ({ key: r.key, tool: r.tool, short: r.short, type: r.type, kind: r.kind, j: r.j, j_ci: r.j_ci, catch: r.catch, fa: r.fa, cost1k: r.cost1k });

// ---------- choose the modes ----------
const tied = original.modes.filter((m) => !m.winner && !m.below_floor && m.top_group.length > 1 && m.rows.some((r) => r.ranked && !m.top_group.includes(r.key)));
const won = original.modes.filter((m) => m.winner && !m.below_floor);
if (!tied.length || !won.length) throw new Error('check-results-mutation: the results file has no tied mode or no mode with a winner to change');
const A = mode(tied[0].id), A0 = tied[0];
const B = mode(won[0].id), B0 = won[0];
const C = won[1] ? mode(won[1].id) : null;

// ---------- mode A: new numbers in every row, a new single winner ----------
A.rows.forEach((r) => {
  r.j = r4(r.j * 0.61 - 0.0173);
  // a changed J that rounds to the old floor would read as "the old floor is still shown" in step 5
  if (Math.round(r.j * 100) === Math.round(original.floor * 100)) r.j = r4(r.j + 0.0213);
  r.j_ci = [r4(r.j - 0.0311), r4(r.j + 0.0289)];
  r.catch = r4(r.catch * 0.83 + 0.011);
  r.fa = r4(r.fa * 0.5 + 0.0207);
  r.fa_per_100 = r4(r.fa * 100);
  if (r.cost1k) r.cost1k = Math.round((r.cost1k * 1.37 + 0.11) * 100) / 100;
  r.in_top_group = false;
});
const newWinner = A.rows.filter((r) => r.ranked && !A0.top_group.includes(r.key)).sort((a, b) => a.rank - b.rank)[0];
set(newWinner, { j: 0.9871, j_ci: [0.9712, 0.9934], in_top_group: true });
A.rows.filter((r) => r.ranked).sort((a, b) => b.j - a.j).forEach((r, i) => { r.rank = i + 1; });
set(A, {
  winner: newWinner.key, top_group: [newWinner.key], best_reviewer: ref(newWinner), below_floor: false,
  tier: 'partly', tier_label: 'ZZ-TIER label of the changed set', ranking: 'ZZ-RANKING sentence of the changed set.',
  title: 'ZZ-TITLE of the changed set', summary: 'ZZ-SUMMARY of the changed set.', tuning_disclosure: 'ZZ-TUNING disclosure of the changed set.',
  n_pos: A.n_pos + 1000, n: A.n + 1000,
});
set(R.overview.best[A.id], { ...ref(newWinner), winner: true, below_floor: false, top_group: [newWinner.short], top_group_keys: [newWinner.key] });
for (const row of R.overview.rows) {
  const cell = row.cells?.[A.id];
  const r = cell && A.rows.find((x) => x.key === cell.key);
  if (r) set(cell, { j: r.j, j_ci: r.j_ci, fa: r.fa, cost1k: r.cost1k });
}

// ---------- mode B: under the floor; mode C: a top group of two ----------
set(B, { winner: null, below_floor: true, tier: 'not-yet', tier_label: 'ZZ-TIER under the floor', ranking: 'ZZ-RANKING nobody is named here.' });
set(R.overview.best[B.id], { winner: false, below_floor: true });
let cPair = [];
if (C) {
  cPair = C.rows.filter((r) => r.ranked).sort((a, b) => a.rank - b.rank).slice(0, 2);
  cPair.forEach((r) => { r.in_top_group = true; });
  set(C, { winner: null, top_group: cPair.map((r) => r.key), ranking: 'ZZ-RANKING a top group of two.' });
  set(R.overview.best[C.id], { winner: false, top_group: cPair.map((r) => r.short), top_group_keys: cPair.map((r) => r.key) });
}

// ---------- file level ----------
const OLD_PREV = original.prevalences, NEW_PREV = [0.02, 0.07, 0.3];
R.prevalences = NEW_PREV;
for (const m of R.modes) {
  m.floor = 0.26;
  for (const r of m.rows) if (r.ppv) r.ppv = Object.fromEntries(OLD_PREV.map((p, i) => [String(NEW_PREV[i]), r.ppv[String(p)]]));
}
set(R, { version: '9.9.9', cite_as: 'ZZ-CITE results v9.9.9', floor: 0.26 });
R.overview.findings[0] = ['ZZ-FINDING lead sentence.', ' ZZ-FINDING rest of the first finding.'];
R.overview.caveats[0] = 'ZZ-CAVEAT first caveat.';
R.method.setting = 'ZZ-SETTING sentence.';
R.method.metric = 'ZZ-METRIC sentence.';
R.threats[0].threat = 'ZZ-THREAT first threat';
R.kind_label.model = 'ZZ-KIND model';
R.overview.counts.samples = original.overview.counts.samples + 1000;

// ---------- build from the changed copy ----------
// --dist <dir> skips the build and checks an existing one (a build from the unchanged file must fail: self-test).
const given = process.argv.includes('--dist') ? resolve(process.argv[process.argv.indexOf('--dist') + 1]) : null;
const work = mkdtempSync(join(tmpdir(), 'saica-results-mutation-'));
const changed = join(work, 'results.json');
const dist = given ?? join(work, 'dist');
writeFileSync(changed, JSON.stringify(R));
if (!given) {
  const build = spawnSync('npx', ['astro', 'build', '--outDir', dist], { cwd: SITE, env: { ...process.env, SAICA_RESULTS_JSON: changed }, encoding: 'utf8' });
  if (build.status !== 0) {
    process.stderr.write(`${(build.stdout ?? '').slice(-3000)}\n${(build.stderr ?? '').slice(-3000)}\n`);
    throw new Error(`check-results-mutation: the build from the changed file failed (temp dir kept: ${work})`);
  }
}

// ---------- check ----------
// The pages have the classic layout: one grid on the home page, one table per failure-mode page, a glance table
// on /findings/ and /tools/, one row per configuration on a tool page. Each must print the changed numbers of
// mode A and none of the old ones; the file-level values (cite_as, sample count, floor) must follow as well.
const problems = [];
const strings = fileStrings(R);
const pages = new Map(htmlFiles(dist).map((f) => [pagePath(dist, f), read(f)]));
const text = new Map();
const textOf = (p) => { if (!text.has(p)) text.set(p, visibleText(pages.get(p))); return text.get(p); };
const need = (p, what, label = what) => { if (!pages.has(p)) problems.push(`${p}: page not built`); else if (!textOf(p).includes(what)) problems.push(`${p}: does not show the changed ${label}`); };
const SLUG = { security: 'security-vulnerability', supply_chain: 'supply-chain-attack' };
const fmPage = (id) => `/failure-modes/${SLUG[id] ?? id.replace(/_/g, '-')}/`;
const listed = (m) => m.rows.filter((r) => r.kind !== 'shortcut_baseline');
const whole = (x) => `${Math.round(x * 100)}%`;

// 1. home page: the static grid and the data handed to the page script
need('/', whole(newWinner.j), `best J of ${A.id}`);
need('/', newWinner.short, `best reviewer of ${A.id}`);
if (pages.has('/')) {
  const html = pages.get('/');
  for (const r of listed(A)) if (!html.includes(`"j":${r.j}`)) problems.push(`/: the page script's data has no row with the changed J ${r.j} (${r.key})`);
  for (const o of listed(A0)) if (html.includes(`"j":${o.j},`)) problems.push(`/: the page script's data still carries the old J ${o.j} (${o.key})`);
}

// 2. the failure-mode page of mode A: every listed row with its changed J, TPR and FPR, none of the old J values
const pA = fmPage(A.id);
if (!pages.has(pA)) problems.push(`${pA}: page not built`);
else {
  const t = textOf(pA);
  const newJ = new Set(listed(A).map((r) => pct(r.j)));
  for (const r of listed(A)) {
    if (!t.includes(pct(r.j))) problems.push(`${pA}: row ${r.key} does not show the changed J ${pct(r.j)}`);
    if (!t.includes(pct(r.catch)) || !t.includes(pct(r.fa))) problems.push(`${pA}: row ${r.key} does not show the changed TPR / FPR`);
  }
  for (const o of listed(A0)) if (!newJ.has(pct(o.j)) && t.includes(`${pct(o.j)} `)) problems.push(`${pA}: still shows the old J ${pct(o.j)} (${o.key})`);
  need(pA, int(A.n_pos), 'number of bad samples');
}

// 3. the glance tables and the hub
for (const p of ['/findings/', '/tools/', '/failure-modes/']) need(p, pct(newWinner.j), `best J of ${A.id}`);
need('/benchmark/', String(A.n_pos), 'number of bad samples');
need('/benchmark/', 'ZZ-THREAT first threat', 'first threat');
need('/findings/', `J ${pct(0.26, 0)}`, 'floor');

// 4. tool pages: a catalog tool measured in mode A shows its changed row
for (const r of A.rows.filter((x) => x.kg_id)) {
  const hit = [...pages].find(([p, html]) => p.startsWith('/tools/') && html.includes(`data-measured="${A.id}/${r.key}"`));
  if (!hit) { problems.push(`no tool page shows the row ${A.id}/${r.key}`); continue; }
  const tr = elementsWith(hit[1], 'data-measured', `${A.id}/${r.key}`)[0];
  if (!tr || !visibleText(tr.inner).includes(pct(r.j))) problems.push(`${hit[0]}: row ${r.key} does not show the changed J`);
}

// 5. old file-level values are gone from the benchmark pages (the file's own sentences set aside)
const BENCH_PAGE = /^\/($|findings\/|benchmark\/|glossary\/|about\/|failure-modes\/|tools\/)/;
const gone = [
  [original.cite_as, 'old cite_as'],
  [int(original.overview.counts.samples), 'old sample count'],
  [`J ${pct(original.floor, 0)}`, 'old floor'],
];
for (const [p, html] of pages) {
  if (!BENCH_PAGE.test(p)) continue;
  const typed = withoutFileStrings(textOf(p), strings);
  const head = visibleText((html.match(/<head>[\s\S]*?<\/head>/) ?? [''])[0].replace(/<meta\b[^>]*content="([^"]*)"[^>]*>/g, ' $1 '));
  for (const [s, label] of gone) if (typed.includes(s) || head.includes(s)) problems.push(`${p}: still shows the ${label} "${s.slice(0, 60)}"`);
}

if (!KEEP) rmSync(work, { recursive: true, force: true });
if (problems.length) {
  console.error(`check-results-mutation: ${problems.length} problem(s)${KEEP ? ` (temp dir: ${work})` : '; run with --keep to inspect the build'}`);
  for (const p of [...new Set(problems)].slice(0, 60)) console.error('  ' + p);
  process.exit(1);
}
console.log(`check-results-mutation: OK. Changed ${A.id} (new winner ${newWinner.short}), ${B.id} (under the floor)${C ? `, ${C.id} (top group of two)` : ''} and the file-level values; ${pages.size} pages followed the changed file.${KEEP ? ` Temp dir: ${work}` : ''}`);
