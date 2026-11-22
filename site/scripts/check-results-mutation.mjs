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
// What is checked: the new values and sentences are on the pages, the old ones are gone.
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
const problems = [];
const strings = fileStrings(R);
const pages = new Map(htmlFiles(dist).map((f) => [pagePath(dist, f), read(f)]));
const text = new Map();
const textOf = (p) => { if (!text.has(p)) text.set(p, visibleText(pages.get(p))); return text.get(p); };
const need = (p, what, label = what) => { if (!pages.has(p)) problems.push(`${p}: page not built`); else if (!textOf(p).includes(what)) problems.push(`${p}: does not show the changed ${label}`); };
const fmPage = (id) => [...pages.keys()].find((p) => /^\/failure-modes\/[^/]+\/$/.test(p) && pages.get(p).includes(`data-ranking-for="${id}"`));
const pageA = fmPage(A.id), pageB = fmPage(B.id);
if (!pageA || !pageB) problems.push('no failure-mode page carries data-ranking-for for the changed modes');

// 1. sentences and labels of the file, page by page
const everywhere = { '/': 1, '/findings/': 1, '/benchmark/': 1 };
for (const p of Object.keys(everywhere)) {
  need(p, A.title, 'set title');
  need(p, A.tuning_disclosure, 'tuning disclosure');
  need(p, A.tier_label, 'tier label');
  need(p, R.method.setting, 'method.setting');
  need(p, R.cite_as, 'cite_as');
}
for (const p of ['/', '/findings/', pageA].filter(Boolean)) need(p, A.ranking, 'ranking sentence');
for (const p of ['/', '/findings/', '/failure-modes/']) need(p, R.overview.findings[0].join(''), 'first finding');
for (const p of ['/', '/findings/', '/failure-modes/']) need(p, R.overview.caveats[0], 'first caveat');
for (const p of ['/', '/findings/', '/benchmark/', '/glossary/']) need(p, R.method.metric.replace(/\.$/, ''), 'method.metric');
for (const p of ['/failure-modes/', '/tools/', '/about/', '/glossary/', pageA].filter(Boolean)) need(p, R.method.setting, 'method.setting');
need('/benchmark/', R.threats[0].threat, 'first threat');
need('/', R.kind_label.model, 'kind label');
if (pageA) for (const s of [A.title, A.summary, A.tier_label, A.tuning_disclosure]) need(pageA, s);
need('/failure-modes/', A.tier_label, 'tier label');
need('/tools/', A.tier_label, 'tier label');
need('/benchmark/', int(A.n_pos), 'number of bad samples');
for (const p of ['/', pageA].filter(Boolean)) for (const q of NEW_PREV) need(p, `if ${pct(q, 0)} of changes are bad`, 'prevalence');

// 2. who is named best
let bestCells = 0;
for (const [p, html] of pages) {
  for (const el of elementsWith(html, 'data-best-for', A.id)) {
    bestCells++;
    const t = visibleText(el.inner);
    if (!t.includes(newWinner.short)) problems.push(`${p}: best reviewer of ${A.id} is "${t}", the changed file names ${newWinner.short}`);
    if (/top group/i.test(t)) problems.push(`${p}: best reviewer of ${A.id} still says "top group"`);
  }
  for (const el of elementsWith(html, 'data-best-for', B.id)) {
    bestCells++;
    const t = visibleText(el.inner);
    const named = B.rows.map((r) => r.short).filter((n) => t.includes(n));
    if (named.length) problems.push(`${p}: ${B.id} is under the floor in the changed file but "${t}" names ${named.join(', ')}`);
    if (!t.includes(pct(0.26, 0))) problems.push(`${p}: ${B.id} does not state the changed floor ("${t}")`);
  }
  if (C) for (const el of elementsWith(html, 'data-best-for', C.id)) {
    bestCells++;
    const t = visibleText(el.inner);
    if (!/top group of 2/i.test(t) || !cPair.every((r) => t.includes(r.short))) problems.push(`${p}: best reviewer of ${C.id} is "${t}", the changed file has a top group of ${cPair.map((r) => r.short).join(' and ')}`);
  }
}
if (bestCells < 6) problems.push(`only ${bestCells} data-best-for cells found; the pages no longer mark who is best`);

// 3. every row of mode A, in the leaderboard panel and on the failure-mode page
const old = new Map(A0.rows.map((r) => [r.key, r]));
const home = pages.get('/') ?? '';
const start = home.indexOf(`data-panel="${A.id}"`);
const next = home.indexOf('data-panel="', start + 20);
const scopes = [['/', start < 0 ? '' : home.slice(start, next < 0 ? undefined : next)], [pageA, pageA ? pages.get(pageA) : '']];
for (const [p, html] of scopes) {
  let seen = 0;
  for (const r of A.rows) {
    const tr = elementsWith(html, 'data-key', r.key).find((e) => e.tag === 'tr');
    if (!tr) continue;
    seen++;
    const t = visibleText(tr.inner);
    const o = old.get(r.key);
    if (!t.includes(signedPct(r.j))) problems.push(`${p}: row ${r.key} does not show the changed J ${signedPct(r.j)}`);
    if (!t.includes(`${signedPct(r.j_ci[0])} to ${signedPct(r.j_ci[1])}`)) problems.push(`${p}: row ${r.key} does not show the changed interval`);
    if (signedPct(o.j) !== signedPct(r.j) && t.includes(signedPct(o.j))) problems.push(`${p}: row ${r.key} still shows the old J ${signedPct(o.j)}`);
    if (!t.includes(pct(r.catch)) || !t.includes(pct(r.fa))) problems.push(`${p}: row ${r.key} does not show the changed TPR / FPR`);
  }
  if (seen < A.rows.filter((r) => r.ranked).length) problems.push(`${p}: only ${seen} of the ${A.rows.length} rows of ${A.id} found (tr[data-key])`);
}
const island = home.match(/<script type="application\/json" id="lb-data">([\s\S]*?)<\/script>/);
const chart = island ? JSON.parse(island[1]).modes?.[A.id]?.rows ?? [] : [];
if (!chart.length) problems.push('/: no chart data for the changed mode');
if (chart.some((c) => !A.rows.some((r) => r.short === c.short && r.j === c.j))) problems.push('/: the chart data does not carry the changed J values');
if (chart.filter((c) => c.top).map((c) => c.short).join() !== newWinner.short) problems.push('/: the chart marks another top group than the changed file');

// 4. tool pages: a catalog tool measured in mode A shows its changed row
for (const r of A.rows.filter((x) => x.kg_id)) {
  const hit = [...pages].find(([p, html]) => p.startsWith('/tools/') && html.includes(`data-measured="${A.id}/${r.key}"`));
  if (!hit) { problems.push(`no tool page shows the row ${A.id}/${r.key}`); continue; }
  const tr = elementsWith(hit[1], 'data-measured', `${A.id}/${r.key}`)[0];
  if (!tr || !visibleText(tr.inner).includes(signedPct(r.j))) problems.push(`${hit[0]}: row ${r.key} does not show the changed J`);
}

// 5. old file-level values are gone from the benchmark pages (the file's own sentences set aside)
const BENCH_PAGE = /^\/($|findings\/|benchmark\/|glossary\/|about\/|failure-modes\/|tools\/)/;
const gone = [
  [original.cite_as, 'old cite_as'],
  [int(original.overview.counts.samples), 'old sample count'],
  [`J ${pct(original.floor, 0)}`, 'old floor'],
  [`reaches J ${pct(original.floor, 0)}`, 'old floor'],
  ...OLD_PREV.filter((q) => !NEW_PREV.includes(q)).map((q) => [`if ${pct(q, 0)} of changes are bad`, 'old prevalence']),
  [original.method.setting, 'old method.setting'],
  [original.overview.findings[0][0], 'old first finding'],
  [A0.ranking, 'old ranking sentence'],
  [B0.ranking, 'old ranking sentence'],
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
