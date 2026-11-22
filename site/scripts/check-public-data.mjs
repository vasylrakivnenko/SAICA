// Build-time check of the generated JSON files in site/public against the knowledge graph in data/.
//   node scripts/check-public-data.mjs        (run by `npm run build` before `astro build`)
//
// 1. Every knowledge-graph id used in a published file must exist in data/. A stale id becomes a dead link
//    or a dot for a node that is gone, so this FAILS the build.
// 2. The reverse is only reported: nodes in data/ that a file should cover and does not.
// 3. data/MANIFEST.json must list exactly the ids in data/, because the site publishes its version and date
//    (/api/v1/snapshot.json). A manifest that is behind FAILS the build.
// Archived snapshots are listed with what no longer matches but never fail: their pages say they are frozen.
//
// SAICA_PUBLIC_DATA_CHECK=warn turns failures into warnings (to build while data/ is being edited).
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import yaml from 'js-yaml';

const SITE_ROOT = fileURLToPath(new URL('../', import.meta.url));
const DATA = join(SITE_ROOT, '..', 'data');
const PUBLIC = join(SITE_ROOT, 'public');
const WARN_ONLY = process.env.SAICA_PUBLIC_DATA_CHECK === 'warn';

const KINDS = ['tools', 'failure_modes', 'papers', 'taxonomies', 'crosswalks', 'incidents', 'recipes'];
// Leaderboard mode ids that differ from the failure-mode ids (same table as src/lib/seo.ts BENCH_TO_KG).
const BENCH_TO_KG = { 'test-manipulation': 'test_manipulation', security: 'security_vulnerability', supply_chain: 'supply_chain_attack' };

const errors = [];
const reports = [];
const archived = [];

// ---------- data/ ----------
const ids = {};
const categories = {}; // taxonomy id -> Set of category external_ids
for (const kind of KINDS) {
  ids[kind] = new Set();
  const dir = join(DATA, kind);
  if (!existsSync(dir)) continue;
  for (const file of readdirSync(dir).filter((f) => /\.ya?ml$/.test(f)).sort()) {
    const doc = yaml.load(readFileSync(join(dir, file), 'utf8'));
    if (!doc || typeof doc !== 'object' || doc.id == null) continue;
    ids[kind].add(String(doc.id));
    if (kind === 'taxonomies') {
      categories[doc.id] = new Set((doc.categories ?? []).map((c) => String(c.external_id)));
    }
  }
}
const KIND_OF_TYPE = { tool: 'tools', failure_mode: 'failure_modes', taxonomy: 'taxonomies', paper: 'papers' };
const anyNode = new Set(KINDS.flatMap((k) => [...ids[k]]));

const readJson = (rel) => {
  const file = join(PUBLIC, rel);
  if (!existsSync(file)) return null;
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch (err) {
    errors.push(`${rel}: not valid JSON (${err.message})`);
    return null;
  }
};
const list = (items, max = 12) => {
  const all = [...new Set(items)].sort();
  return all.slice(0, max).join(', ') + (all.length > max ? `, and ${all.length - max} more` : '');
};
/** `unknown` ids are an error for a live file and a note for an archived one. */
function unknown(rel, what, items, isArchived = false) {
  if (items.length === 0) return;
  const line = `${rel}: ${what} not in data/ (${new Set(items).size}): ${list(items)}`;
  (isArchived ? archived : errors).push(line);
}
function uncovered(rel, kind, have) {
  const missing = [...ids[kind]].filter((id) => !have.has(id));
  if (missing.length) reports.push(`${rel}: ${kind} in data/ that are not in the file (${missing.length} of ${ids[kind].size}): ${list(missing)}`);
}
/** Every value stored under `key` anywhere in a JSON document. */
function valuesOf(doc, key, out = []) {
  if (Array.isArray(doc)) for (const v of doc) valuesOf(v, key, out);
  else if (doc && typeof doc === 'object') {
    for (const [k, v] of Object.entries(doc)) {
      if (k === key && typeof v === 'string') out.push(v);
      else valuesOf(v, key, out);
    }
  }
  return out;
}

// ---------- embeddings.json (the /explore/ map) ----------
{
  const rel = 'embeddings.json';
  const doc = readJson(rel);
  if (doc) {
    const rows = [...(doc.combined ?? []), ...Object.values(doc.by_type ?? {}).flat()];
    const bad = rows.filter((r) => !ids[KIND_OF_TYPE[r.type]]?.has(r.id)).map((r) => `${r.type}:${r.id}`);
    unknown(rel, 'node ids', bad);
    unknown(rel, 'top_similar_ids', rows.flatMap((r) => r.top_similar_ids ?? []).filter((id) => !anyNode.has(id)));
    if (typeof doc.count === 'number' && doc.count !== (doc.combined ?? []).length) {
      errors.push(`${rel}: header "count" is ${doc.count} but "combined" has ${(doc.combined ?? []).length} rows`);
    }
    for (const [type, kind] of Object.entries(KIND_OF_TYPE)) {
      uncovered(rel, kind, new Set((doc.combined ?? []).filter((r) => r.type === type).map((r) => r.id)));
    }
  }
}

// ---------- maturity.json, tool_fm_heatmap.json ----------
{
  const rel = 'maturity.json';
  const doc = readJson(rel);
  if (doc) {
    const have = new Set(Object.keys(doc.tools ?? {}));
    unknown(rel, 'tool ids', [...have].filter((id) => !ids.tools.has(id)));
    uncovered(rel, 'tools', have);
  }
}
{
  const rel = 'tool_fm_heatmap.json';
  const doc = readJson(rel);
  if (doc) {
    const tools = ['tools_minimum', 'tools_optimal', 'tools_full', 'tools_all'].flatMap((k) => doc[k] ?? []);
    unknown(rel, 'tool ids', tools.map((t) => t.id).filter((id) => !ids.tools.has(id)));
    const fms = [...(doc.failure_modes ?? []), ...tools.flatMap((t) => Object.keys(t.tiers ?? {}))];
    unknown(rel, 'failure-mode ids', fms.filter((id) => !ids.failure_modes.has(id)));
    uncovered(rel, 'tools', new Set((doc.tools_all ?? []).map((t) => t.id)));
  }
}

// ---------- bench/results.json, bench/kit.json ----------
for (const rel of ['bench/results.json', 'bench/kit.json']) {
  const doc = readJson(rel);
  if (!doc) continue;
  unknown(rel, 'kg_id values (tool ids)', valuesOf(doc, 'kg_id').filter((id) => !ids.tools.has(id)));
  const fms = [
    ...valuesOf(doc, 'fm'),
    ...(rel === 'bench/results.json' ? (doc.modes ?? []).map((m) => BENCH_TO_KG[m.id] ?? m.id) : []),
  ];
  unknown(rel, 'failure-mode ids', fms.filter((id) => !ids.failure_modes.has(id)));
}

// ---------- archived snapshots: listed, never fail ----------
{
  const rel = 'taxonomy_study.json (archived, computed 2026-04-23)';
  const doc = readJson('taxonomy_study.json');
  if (doc) {
    const points = doc.points ?? [];
    unknown(rel, 'taxonomy ids', Object.keys(doc.taxonomies ?? {}).filter((id) => !ids.taxonomies.has(id)), true);
    const gone = points.filter((p) => !categories[p.source_tax_id]?.has(String(p.id))).map((p) => `${p.source_tax_id}/${p.id}`);
    unknown(rel, `category ids (of ${points.length})`, gone, true);
    const now = Object.values(categories).reduce((n, set) => n + set.size, 0);
    if (points.length !== now) archived.push(`${rel}: ${points.length} categories in the file, ${now} in data/taxonomies today`);
  }
}
{
  const rel = 'saica_index.json (archived, generated 2026-05-02)';
  const doc = readJson('saica_index.json');
  if (doc) {
    const fms = Object.values(doc.boards ?? {}).flat().flatMap((row) => Object.keys(row.per_fm ?? {}));
    unknown(rel, 'failure-mode ids', fms.filter((id) => !ids.failure_modes.has(id)), true);
  }
}
{
  const rel = 'prevention_log_sample.jsonl (archived demo data)';
  const file = join(PUBLIC, 'prevention_log_sample.jsonl');
  if (existsSync(file)) {
    const events = readFileSync(file, 'utf8').split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l));
    unknown(rel, 'tool ids', events.map((e) => e.tool_id).filter((id) => !ids.tools.has(id)), true);
    unknown(rel, 'failure-mode ids', events.map((e) => e.failure_mode).filter((id) => !ids.failure_modes.has(id)), true);
  }
}

// ---------- data/MANIFEST.json ----------
{
  const file = join(DATA, 'MANIFEST.json');
  if (!existsSync(file)) errors.push('data/MANIFEST.json is missing (run `python -m validator.generate_manifest`)');
  else {
    const manifest = JSON.parse(readFileSync(file, 'utf8'));
    for (const kind of KINDS) {
      const listed = manifest.ids?.[kind];
      const want = new Set(Array.isArray(listed) ? listed : Object.keys(listed ?? {}));
      const added = [...ids[kind]].filter((id) => !want.has(id));
      const gone = [...want].filter((id) => !ids[kind].has(id));
      if (added.length) errors.push(`data/MANIFEST.json: ${kind} in data/ that are not listed (${added.length}): ${list(added)}`);
      if (gone.length) errors.push(`data/MANIFEST.json: listed ${kind} that are not in data/ (${gone.length}): ${list(gone)}`);
    }
  }
}

// ---------- result ----------
const print = (title, lines) => {
  if (lines.length) console.log(`${title}\n${lines.map((l) => `  - ${l}`).join('\n')}`);
};
print('check-public-data: archived snapshots (not checked strictly)', archived);
print('check-public-data: not covered (reported only)', reports);
if (errors.length === 0) {
  console.log('check-public-data: OK, every id in site/public exists in data/ and data/MANIFEST.json is current');
} else {
  print(`check-public-data: ${errors.length} problem(s)`, errors);
  console.log(
    'Fix: regenerate the file from the current data/ (embeddings: `python -m pipeline.cli.embed`; maturity: ' +
      '`python -m validator.generate_maturity`; manifest: `python -m validator.generate_manifest`; bench files: ' +
      '`bench/build_report.py`).',
  );
  if (WARN_ONLY) console.log('SAICA_PUBLIC_DATA_CHECK=warn: continuing.');
  else process.exit(1);
}
