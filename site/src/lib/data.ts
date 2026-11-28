// Single data-layer module: loads the YAML knowledge graph (../data) at build time into an in-memory graph.
// All site pages and JSON endpoints import `graph` from here.
//
// What the loader guarantees, and checks while it runs:
// - Every key of a YAML file survives into the loaded node with its value unchanged. The loader only turns
//   dates into YYYY-MM-DD strings, fills the optional lists named in FILLED (types.ts) with [] and applies the
//   few scalar defaults written in the hydrate* functions below. A field added to the schema therefore reaches
//   the pages and /api/v1 with no change here; `assertSurvives` throws if a key is ever lost or rewritten.
// - Crosswalk mappings come from data/crosswalks/ only, as one normalised list: `crosswalkEdges`. The inline
//   `crosswalks:` blocks that some failure-mode files carry repeat those files and are not loaded (the one
//   deliberate exception to the rule above; an inline mapping the crosswalk files lack is reported).
// - Version and date come from data/MANIFEST.json, not from a literal or the build clock. Node counts are
//   counted from the loaded files and compared with the manifest (`manifestDrift`).

import fs from 'node:fs';
import path from 'node:path';
import yaml from 'js-yaml';
import { FILLED } from './types.ts';
import type {
  Tool,
  FailureMode,
  Taxonomy,
  Paper,
  Crosswalk,
  CrosswalkConfidence,
  CrosswalkEdge,
  Incident,
  NodeKind,
  Recipe,
  Graph,
} from './types.ts';

type Raw = Record<string, any>;

// Resolve in astro.config.mjs before bundling changes this module's location.
const DATA_DIR = import.meta.env.KG_DATA_DIR as string;
if (!DATA_DIR || !fs.existsSync(DATA_DIR)) {
  throw new Error('Catalog data directory is missing; check astro.config.mjs.');
}

function readYamlDir(subdir: NodeKind): Raw[] {
  const dir = path.join(DATA_DIR, subdir);
  if (!fs.existsSync(dir)) return [];
  // Sorted, so the order of nodes (and of every list built from them) does not depend on the file system.
  const files = fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.yml') || f.endsWith('.yaml'))
    .sort();
  const out: Raw[] = [];
  for (const file of files) {
    const doc = yaml.load(fs.readFileSync(path.join(dir, file), 'utf8')) as Raw | null;
    if (doc && typeof doc === 'object') out.push(coerceDates(doc));
  }
  return out;
}

// Recursively turn Date objects into ISO date strings (YYYY-MM-DD).
function coerceDates(value: any): any {
  if (value instanceof Date) {
    // js-yaml parses `YYYY-MM-DD` into a Date at UTC midnight; emit YYYY-MM-DD.
    return value.toISOString().slice(0, 10);
  }
  if (Array.isArray(value)) return value.map(coerceDates);
  if (value && typeof value === 'object') {
    const out: Raw = {};
    for (const [k, v] of Object.entries(value)) out[k] = coerceDates(v);
    return out;
  }
  return value;
}

/** Raw YAML -> loaded node: keep every key, make `id` a string, fill the kind's lists, apply `scalars`. */
function load<T>(kind: NodeKind, raw: Raw, scalars: Raw = {}): T {
  const node: Raw = { ...raw, id: String(raw.id), ...scalars };
  for (const key of FILLED[kind]) {
    if (raw[key] != null && !Array.isArray(raw[key])) {
      throw new Error(`data.ts: ${kind}/${raw.id}: field "${key}" must be a list`);
    }
    node[key] = raw[key] ?? [];
  }
  assertSurvives(kind, raw, node, new Set<string>(['id', ...Object.keys(scalars), ...FILLED[kind]]));
  return node as T;
}

/** The build-time check behind "every YAML key survives": each key of the file must be on the loaded node,
 *  with the very same value, unless it is a field the loader normalises and the file's value was missing or
 *  of another type (a default or a coercion). */
function assertSurvives(kind: string, raw: Raw, node: Raw, normalised: Set<string>): void {
  for (const key of Object.keys(raw)) {
    if (!(key in node)) {
      throw new Error(`data.ts: ${kind}/${raw.id}: field "${key}" was dropped by the loader`);
    }
    if (node[key] === raw[key]) continue;
    const before = raw[key];
    const after = node[key];
    const coerced =
      normalised.has(key) &&
      (before == null || typeof before !== typeof after || Array.isArray(before) !== Array.isArray(after));
    if (!coerced) throw new Error(`data.ts: ${kind}/${raw.id}: field "${key}" was changed by the loader`);
  }
}

const hydrateTool = (raw: Raw): Tool =>
  load<Tool>('tools', raw, {
    name: String(raw.name ?? raw.id),
    description: String(raw.description ?? ''),
    first_released: String(raw.first_released ?? ''),
    license: String(raw.license ?? ''),
    maturity_status: raw.maturity_status ?? 'experimental',
    openssf_scorecard_score: raw.openssf_scorecard_score ?? null,
  });

/** Inline crosswalk entries found in failure-mode files; only used to report what data/crosswalks/ lacks. */
interface InlineCrosswalk {
  fm: string;
  taxonomy: string;
  external_id: string;
}

function hydrateFailureMode(raw: Raw, inline: InlineCrosswalk[]): FailureMode {
  // Not loaded on purpose (see the header): mappings are read from data/crosswalks/ only.
  const { crosswalks: duplicate, ...rest } = raw;
  for (const cw of Array.isArray(duplicate) ? duplicate : []) {
    inline.push({ fm: String(raw.id), taxonomy: String(cw?.taxonomy), external_id: String(cw?.external_id) });
  }
  return load<FailureMode>('failure_modes', rest, {
    name: String(raw.name ?? raw.id),
    description: String(raw.description ?? ''),
  });
}

const hydrateTaxonomy = (raw: Raw): Taxonomy =>
  load<Taxonomy>('taxonomies', raw, {
    name: String(raw.name ?? raw.id),
    owner: String(raw.owner ?? ''),
    version: String(raw.version ?? ''),
  });

const hydratePaper = (raw: Raw): Paper =>
  load<Paper>('papers', raw, { year: Number(raw.year), title: String(raw.title ?? '') });

const hydrateCrosswalk = (raw: Raw): Crosswalk =>
  load<Crosswalk>('crosswalks', raw, { taxonomy: String(raw.taxonomy ?? '') });

const hydrateIncident = (raw: Raw): Incident =>
  load<Incident>('incidents', raw, {
    title: String(raw.title ?? raw.id),
    description: String(raw.description ?? ''),
    incident_date: String(raw.incident_date ?? ''),
  });

const hydrateRecipe = (raw: Raw): Recipe =>
  load<Recipe>('recipes', raw, {
    name: String(raw.name ?? raw.id),
    description: String(raw.description ?? ''),
  });

function keyBy<T extends { id: string }>(items: T[]): Record<string, T> {
  const out: Record<string, T> = {};
  for (const it of items) out[it.id] = it;
  return out;
}

// ---------- crosswalks ----------

/** Strength of a mapping, strongest first. Used wherever mappings are ordered or one is picked for a pair. */
export const CONFIDENCE_RANK: Record<CrosswalkConfidence, number> = {
  exact: 0,
  partial: 1,
  broader: 2,
  narrower: 3,
  related: 4,
};
export const confidenceRank = (c: string): number => CONFIDENCE_RANK[c as CrosswalkConfidence] ?? 9;

const byCodeUnit = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** data/crosswalks/*.yml as one flat list: one edge per (axis, SAICA value, taxonomy, category), with the
 *  taxonomy's name and the category's label joined in. A pair listed twice keeps its stronger mapping. */
function buildCrosswalkEdges(crosswalks: Crosswalk[], taxonomies: Record<string, Taxonomy>): CrosswalkEdge[] {
  const byKey = new Map<string, CrosswalkEdge>();
  for (const cw of crosswalks) {
    const tax = taxonomies[cw.taxonomy];
    for (const m of cw.mappings) {
      const cat = tax?.categories.find((c) => c.external_id === m.external_id);
      const note = typeof m.note === 'string' ? m.note.replace(/\s+/g, ' ').trim() : '';
      const edge: CrosswalkEdge = {
        crosswalk: cw.id,
        axis: cw.saica_axis,
        saica_value: String(m.saica_value),
        taxonomy: cw.taxonomy,
        taxonomy_name: tax?.name ?? cw.taxonomy,
        external_id: String(m.external_id),
        external_label: cat?.label ?? String(m.external_id),
        confidence: m.confidence,
        ...(note ? { note } : {}),
      };
      const key = [edge.axis, edge.saica_value, edge.taxonomy, edge.external_id].join('\u0000');
      const prev = byKey.get(key);
      if (!prev) byKey.set(key, edge);
      else if (confidenceRank(edge.confidence) < confidenceRank(prev.confidence)) {
        byKey.set(key, edge.note || !prev.note ? edge : { ...edge, note: prev.note });
      } else if (!prev.note && edge.note) prev.note = edge.note;
    }
  }
  return [...byKey.values()].sort(
    (a, b) =>
      byCodeUnit(a.saica_value, b.saica_value) ||
      confidenceRank(a.confidence) - confidenceRank(b.confidence) ||
      byCodeUnit(a.taxonomy, b.taxonomy) ||
      byCodeUnit(a.external_id, b.external_id),
  );
}

// ---------- manifest ----------

interface Manifest {
  generated_at: string;
  kg_version: string;
  counts?: Record<string, number>;
  ids?: Record<string, string[] | Record<string, unknown>>;
}

function readManifest(): Manifest {
  const file = path.join(DATA_DIR, 'MANIFEST.json');
  const hint = 'run `python -m validator.generate_manifest`';
  let doc: Manifest;
  try {
    doc = JSON.parse(fs.readFileSync(file, 'utf8')) as Manifest;
  } catch (err) {
    throw new Error(`data/MANIFEST.json is missing or is not valid JSON (${String(err)}); ${hint}.`);
  }
  if (typeof doc?.kg_version !== 'string' || typeof doc?.generated_at !== 'string') {
    throw new Error(`data/MANIFEST.json has no kg_version / generated_at; ${hint}.`);
  }
  return doc;
}

// ---------- removed nodes ----------

/** A node removed from the knowledge graph, as listed in data/TOMBSTONES.yml. */
export interface Tombstone {
  id: string;
  /** tool | failure_mode | paper | taxonomy | crosswalk | incident | recipe */
  kind: string;
  removed_on: string;
  reason: string;
  successor: string | null;
}

function readTombstones(): Tombstone[] {
  const file = path.join(DATA_DIR, 'TOMBSTONES.yml');
  if (!fs.existsSync(file)) return [];
  const doc = coerceDates(yaml.load(fs.readFileSync(file, 'utf8')) ?? {});
  const rows: Raw[] = Array.isArray(doc.tombstones) ? doc.tombstones : [];
  return rows
    .filter((t) => t && t.id != null && t.kind != null)
    .map((t) => ({
      id: String(t.id),
      kind: String(t.kind),
      removed_on: String(t.removed_on ?? ''),
      reason: String(t.reason ?? '').replace(/\s+/g, ' ').trim(),
      successor: t.successor == null ? null : String(t.successor),
    }));
}

// ---------- graph ----------

function buildGraph(): { graph: Graph; edges: CrosswalkEdge[]; drift: string[] } {
  const inline: InlineCrosswalk[] = [];
  const tools = readYamlDir('tools').map(hydrateTool);
  const failureModes = readYamlDir('failure_modes').map((raw) => hydrateFailureMode(raw, inline));
  const taxonomies = readYamlDir('taxonomies').map(hydrateTaxonomy);
  const papers = readYamlDir('papers').map(hydratePaper);
  const crosswalks = readYamlDir('crosswalks').map(hydrateCrosswalk);
  const incidents = readYamlDir('incidents').map(hydrateIncident);
  const recipes = readYamlDir('recipes').map(hydrateRecipe);

  // Derived index: failure_mode_id -> tool_ids[] (sorted, for stable output).
  const toolsByFailureMode: Record<string, string[]> = {};
  for (const fm of failureModes) toolsByFailureMode[fm.id] = [];
  for (const tool of tools) {
    for (const fmId of tool.addresses_failure_modes) (toolsByFailureMode[fmId] ??= []).push(tool.id);
  }
  for (const fmId of Object.keys(toolsByFailureMode)) toolsByFailureMode[fmId].sort();

  const edges = buildCrosswalkEdges(crosswalks, keyBy(taxonomies));
  const known = new Set(
    edges.filter((e) => e.axis === 'failure_mode').map((e) => `${e.saica_value}/${e.taxonomy}/${e.external_id}`),
  );
  for (const cw of inline) {
    if (!known.has(`${cw.fm}/${cw.taxonomy}/${cw.external_id}`)) {
      console.warn(
        `[data] failure_modes/${cw.fm}: inline crosswalk ${cw.taxonomy}/${cw.external_id} is not in data/crosswalks/ and is not shown`,
      );
    }
  }

  const manifest = readManifest();
  const graph: Graph = {
    tools: keyBy(tools),
    failureModes: keyBy(failureModes),
    taxonomies: keyBy(taxonomies),
    papers: keyBy(papers),
    crosswalks: keyBy(crosswalks),
    incidents: keyBy(incidents),
    recipes: keyBy(recipes),
    toolsByFailureMode,
    kgVersion: manifest.kg_version,
    kgLastUpdated: manifest.generated_at,
  };

  // The manifest stamps the version and date published in /api/v1/snapshot.json, so say when it is behind data/.
  const drift: string[] = [];
  const kinds: Array<[NodeKind, Record<string, unknown>]> = [
    ['tools', graph.tools],
    ['failure_modes', graph.failureModes],
    ['papers', graph.papers],
    ['taxonomies', graph.taxonomies],
    ['crosswalks', graph.crosswalks],
    ['incidents', graph.incidents],
    ['recipes', graph.recipes],
  ];
  for (const [kind, nodes] of kinds) {
    const listed = manifest.ids?.[kind];
    const want = new Set(Array.isArray(listed) ? listed : Object.keys(listed ?? {}));
    const have = new Set(Object.keys(nodes));
    const added = [...have].filter((id) => !want.has(id));
    const gone = [...want].filter((id) => !have.has(id));
    if (added.length) drift.push(`${kind}: in data/ but not in the manifest: ${added.join(', ')}`);
    if (gone.length) drift.push(`${kind}: in the manifest but not in data/: ${gone.join(', ')}`);
  }
  if (drift.length) {
    console.warn(
      `[data] data/MANIFEST.json (${manifest.generated_at}) is behind data/; kg_version and kg_last_updated may be stale. ` +
        `Run \`python -m validator.generate_manifest\`.\n  ${drift.join('\n  ')}`,
    );
  }

  return { graph, edges, drift };
}

// Eagerly loaded. Astro runs this once at build time.
const built = buildGraph();
export const graph: Graph = built.graph;

/** Every crosswalk mapping in data/crosswalks/, normalised and deduplicated: the only place the site reads
 *  crosswalks from. Sorted by SAICA value, then strongest mapping first. */
export const crosswalkEdges: CrosswalkEdge[] = built.edges;

/** Mappings of one failure mode into other taxonomies, strongest first. */
export const crosswalksOf = (failureModeId: string): CrosswalkEdge[] =>
  crosswalkEdges.filter((e) => e.axis === 'failure_mode' && e.saica_value === failureModeId);

/** Mappings from failure modes into one taxonomy, grouped by the taxonomy's category id, strongest first. */
export function crosswalksInto(taxonomyId: string): Record<string, CrosswalkEdge[]> {
  const out: Record<string, CrosswalkEdge[]> = {};
  for (const e of crosswalkEdges) {
    if (e.axis !== 'failure_mode' || e.taxonomy !== taxonomyId) continue;
    (out[e.external_id] ??= []).push(e);
  }
  for (const list of Object.values(out)) {
    list.sort(
      (a, b) =>
        confidenceRank(a.confidence) - confidenceRank(b.confidence) || byCodeUnit(a.saica_value, b.saica_value),
    );
  }
  return out;
}

/** Nodes removed from data/ whose id is not in use again: their old page URL gets a "removed" notice
 *  (pages/[kind]/[id].astro) instead of a 404. */
export const tombstones: Tombstone[] = readTombstones().filter((t) => {
  const live: Record<string, Record<string, unknown>> = {
    tool: graph.tools,
    failure_mode: graph.failureModes,
    paper: graph.papers,
    taxonomy: graph.taxonomies,
    crosswalk: graph.crosswalks,
    incident: graph.incidents,
    recipe: graph.recipes,
  };
  return !live[t.kind]?.[t.id];
});

/** How the mappings into one taxonomy were produced and checked (fields of its crosswalk files). */
export interface CrosswalkReview {
  crosswalk: string;
  /** `llm_drafted_unreviewed`, `human_reviewed`, or undefined when the file does not say. */
  state?: string;
  reviewedBy: string[];
  /** Date the external ids and labels were last compared with the source (not a review of the mappings). */
  sourceCheckedOn?: string;
}
export const crosswalkReviews = (taxonomyId: string): CrosswalkReview[] =>
  Object.values(graph.crosswalks)
    .filter((c) => c.saica_axis === 'failure_mode' && c.taxonomy === taxonomyId)
    .map((c) => ({
      crosswalk: c.id,
      state: c.review_state,
      reviewedBy: c.reviewed_by,
      sourceCheckedOn: c.source_checked_on,
    }));

/** Categories of a taxonomy that its crosswalk leaves without a mapping on purpose: category id -> reason. */
export function unmappedIn(taxonomyId: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const c of Object.values(graph.crosswalks)) {
    if (c.saica_axis !== 'failure_mode' || c.taxonomy !== taxonomyId) continue;
    for (const u of c.unmapped) out[String(u.category)] = String(u.reason ?? '').replace(/\s+/g, ' ').trim();
  }
  return out;
}

/** Where data/MANIFEST.json disagrees with the files in data/ (empty when the manifest is current). */
export const manifestDrift: string[] = built.drift;

/** Published as `disclaimer` in /api/v1/snapshot.json. */
export const DISCLAIMER =
  'SAICA-KG is a catalog: definitions, tools, incidents, papers and crosswalks. A failure-mode tag on a tool ' +
  'says what the tool is built to catch or prevent; it is a claim, not a test result. Measured results are in ' +
  'https://saica.ai/bench/results.json.';

export function rawYamlUrl(kind: string, id: string): string {
  // kind: "tools" | "failure_modes" | "papers" | "taxonomies" | "crosswalks"
  //       | "incidents" | "recipes"
  return `https://github.com/vasylrakivnenko/SAICA/blob/main/data/${kind}/${id}.yml`;
}

/** Node counts of the loaded graph. Crosswalks are reported both ways: files (nodes) and mappings in them. */
export function counts(): {
  tools: number;
  failure_modes: number;
  papers: number;
  taxonomies: number;
  crosswalks: { nodes: number; mappings: number };
  incidents: number;
  recipes: number;
} {
  return {
    tools: Object.keys(graph.tools).length,
    failure_modes: Object.keys(graph.failureModes).length,
    papers: Object.keys(graph.papers).length,
    taxonomies: Object.keys(graph.taxonomies).length,
    crosswalks: { nodes: Object.keys(graph.crosswalks).length, mappings: crosswalkEdges.length },
    incidents: Object.keys(graph.incidents).length,
    recipes: Object.keys(graph.recipes).length,
  };
}

// Small human-friendly label helpers for enums.
export const FACET_LABELS = {
  control_paradigm: {
    prevention: 'Prevention',
    detection: 'Detection',
    correction: 'Correction',
    recovery: 'Recovery',
  } as Record<string, string>,
  temporal_phase: {
    pre_generation: 'Pre-generation',
    in_generation: 'In-generation',
    post_generation: 'Post-generation',
  } as Record<string, string>,
  autonomy_level: {
    fully_autonomous: 'Fully autonomous',
    graduated_hitl: 'Graduated HITL',
    full_hitl: 'Full HITL',
  } as Record<string, string>,
  locus_of_control: {
    model: 'Model',
    prompt: 'Prompt',
    context: 'Context',
    environment: 'Environment',
    human: 'Human',
  } as Record<string, string>,
  maturity_status: {
    experimental: 'Experimental',
    stable: 'Stable',
    at_risk: 'At risk',
    deprecated: 'Deprecated',
    abandoned: 'Abandoned',
  } as Record<string, string>,
  // How the supervising check itself is carried out (schema: Tool.implementation).
  implementation: {
    deterministic: 'Free tool',
    deterministic_paid: 'Paid tool', // a deterministic tool with a proprietary licence (see implementationKey)
    llm_based: 'LLM-based tool',
    hybrid: 'Hybrid',
    prompt_artifact: 'Prompt',
  } as Record<string, string>,
};

/** One line per implementation type, for tool pages (wording follows schema/tool.schema.json). */
export const IMPLEMENTATION_NOTE: Record<string, string> = {
  deterministic: 'a program; the check makes no model calls',
  llm_based: 'a model makes the decision',
  hybrid: 'a program at the core, with model-based checks shipped alongside',
  prompt_artifact: 'not a program: skills, rules or docs the agent reads',
};

/** Implementation facet value for display: deterministic tools under a proprietary licence are shown as paid. */
export function implementationKey(t: { implementation?: string | null; license?: string | null }): string {
  return t.implementation === 'deterministic' && (t.license ?? '').toLowerCase() === 'proprietary'
    ? 'deterministic_paid'
    : (t.implementation ?? '');
}

export function facetLabel(facet: keyof typeof FACET_LABELS, value: string): string {
  return FACET_LABELS[facet]?.[value] ?? value;
}

export function failureModeLabel(id: string): string {
  return graph.failureModes[id]?.name ?? id;
}

export function paperLabel(id: string): string {
  const p = graph.papers[id];
  if (!p) return id;
  const firstAuthor = p.authors[0] ?? 'Anon.';
  return `${firstAuthor} (${p.year}) — ${p.title}`;
}

/** GitHub stars as the short tag shown after a tool's name on every page: "870 ★ Stars", "1.2k ★ Stars", "57k ★ Stars".
 * The leaderboard's inline script (pages/index.astro) repeats this formula; keep the two the same. */
export function starsShort(n: number): string {
  const k = n >= 10000 ? `${Math.round(n / 1000)}k` : n >= 1000 ? `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k` : String(n);
  return `${k} ★ Stars`;
}
