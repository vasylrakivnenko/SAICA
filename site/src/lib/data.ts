// Single data-layer module: loads YAML at build time into an in-memory graph,
// coerces Date objects to ISO strings, builds derived indexes.
//
// All site pages and JSON endpoints import `graph` from here.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import yaml from 'js-yaml';
import type {
  Tool,
  FailureMode,
  Taxonomy,
  Paper,
  Crosswalk,
  Graph,
} from './types.ts';

const DATA_VERSION = '2026.04';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// site/src/lib -> site/src -> site -> repo root
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const DATA_DIR = path.join(REPO_ROOT, 'data');

function readYamlDir(subdir: string): Record<string, any>[] {
  const dir = path.join(DATA_DIR, subdir);
  if (!fs.existsSync(dir)) return [];
  const files = fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.yml') || f.endsWith('.yaml'));
  const out: Record<string, any>[] = [];
  for (const file of files) {
    const full = path.join(dir, file);
    const raw = fs.readFileSync(full, 'utf8');
    const doc = yaml.load(raw) as Record<string, any> | null;
    if (doc && typeof doc === 'object') {
      out.push(coerceDates(doc));
    }
  }
  return out;
}

// Recursively turn Date objects into ISO date strings (YYYY-MM-DD).
function coerceDates(value: any): any {
  if (value instanceof Date) {
    // js-yaml parses `YYYY-MM-DD` into a Date at UTC midnight; emit YYYY-MM-DD.
    const iso = value.toISOString();
    return iso.slice(0, 10);
  }
  if (Array.isArray(value)) return value.map(coerceDates);
  if (value && typeof value === 'object') {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(value)) out[k] = coerceDates(v);
    return out;
  }
  return value;
}

function hydrateTool(raw: Record<string, any>): Tool {
  return {
    id: String(raw.id),
    name: String(raw.name ?? raw.id),
    tagline: raw.tagline,
    description: String(raw.description ?? ''),
    first_released: String(raw.first_released ?? ''),
    last_updated: raw.last_updated,
    maturity_status: raw.maturity_status ?? 'experimental',
    published_by: raw.published_by,
    repository_url: raw.repository_url,
    documentation_url: raw.documentation_url,
    license: String(raw.license ?? ''),
    control_paradigm: raw.control_paradigm,
    temporal_phase: raw.temporal_phase,
    autonomy_level: raw.autonomy_level,
    addresses_failure_modes: Array.isArray(raw.addresses_failure_modes)
      ? raw.addresses_failure_modes
      : [],
    locus_of_control: Array.isArray(raw.locus_of_control) ? raw.locus_of_control : [],
    implements_techniques: Array.isArray(raw.implements_techniques)
      ? raw.implements_techniques
      : [],
    composes_with: Array.isArray(raw.composes_with) ? raw.composes_with : [],
    feeds_into: Array.isArray(raw.feeds_into) ? raw.feeds_into : [],
    supersedes: Array.isArray(raw.supersedes) ? raw.supersedes : [],
    runtime_requires: Array.isArray(raw.runtime_requires) ? raw.runtime_requires : [],
    supervises_targets: Array.isArray(raw.supervises_targets)
      ? raw.supervises_targets
      : [],
    cited_in: Array.isArray(raw.cited_in) ? raw.cited_in : [],
    documented_in: Array.isArray(raw.documented_in) ? raw.documented_in : [],
    evaluated_on: Array.isArray(raw.evaluated_on) ? raw.evaluated_on : [],
    security_notes: raw.security_notes,
    signed_manifest: raw.signed_manifest,
    openssf_scorecard_score: raw.openssf_scorecard_score ?? null,
    stars: typeof raw.stars === 'number' ? raw.stars : undefined,
    stars_updated_at: raw.stars_updated_at,
    contributors: Array.isArray(raw.contributors) ? raw.contributors : [],
    editorial_notes: raw.editorial_notes,
    inclusion_rationale: raw.inclusion_rationale,
  };
}

function hydrateFailureMode(raw: Record<string, any>): FailureMode {
  return {
    id: String(raw.id),
    name: String(raw.name ?? raw.id),
    tagline: raw.tagline,
    description: String(raw.description ?? ''),
    aliases: Array.isArray(raw.aliases) ? raw.aliases : [],
    related_modes: Array.isArray(raw.related_modes) ? raw.related_modes : [],
    prior_work: Array.isArray(raw.prior_work) ? raw.prior_work : [],
    detection_signals: Array.isArray(raw.detection_signals) ? raw.detection_signals : [],
    canonical_definition_source: raw.canonical_definition_source,
    crosswalks: Array.isArray(raw.crosswalks) ? raw.crosswalks : [],
  };
}

function hydrateTaxonomy(raw: Record<string, any>): Taxonomy {
  return {
    id: String(raw.id),
    name: String(raw.name ?? raw.id),
    owner: String(raw.owner ?? ''),
    version: String(raw.version ?? ''),
    first_published: raw.first_published,
    last_updated: raw.last_updated,
    url: raw.url,
    license: raw.license,
    paper_id: raw.paper_id,
    scope: raw.scope,
    categories: Array.isArray(raw.categories) ? raw.categories : [],
    notes: raw.notes,
    inclusion_rationale: raw.inclusion_rationale,
  };
}

function hydratePaper(raw: Record<string, any>): Paper {
  return {
    id: String(raw.id),
    authors: Array.isArray(raw.authors) ? raw.authors : [],
    year: Number(raw.year),
    title: String(raw.title ?? ''),
    venue: raw.venue,
    url: raw.url,
    doi: raw.doi,
    arxiv_id: raw.arxiv_id,
    semantic_scholar_id: raw.semantic_scholar_id,
    abstract: raw.abstract,
    tldr: raw.tldr,
    citation_count: typeof raw.citation_count === 'number' ? raw.citation_count : undefined,
    relevance_tags: Array.isArray(raw.relevance_tags) ? raw.relevance_tags : [],
    notes: raw.notes,
  };
}

function hydrateCrosswalk(raw: Record<string, any>): Crosswalk {
  return {
    id: String(raw.id),
    saica_axis: raw.saica_axis,
    taxonomy: String(raw.taxonomy ?? ''),
    authored_by: Array.isArray(raw.authored_by) ? raw.authored_by : [],
    reviewed_by: Array.isArray(raw.reviewed_by) ? raw.reviewed_by : [],
    last_reviewed: raw.last_reviewed,
    mappings: Array.isArray(raw.mappings) ? raw.mappings : [],
  };
}

function keyBy<T extends { id: string }>(items: T[]): Record<string, T> {
  const out: Record<string, T> = {};
  for (const it of items) out[it.id] = it;
  return out;
}

function buildGraph(): Graph {
  const tools = readYamlDir('tools').map(hydrateTool);
  const failureModes = readYamlDir('failure_modes').map(hydrateFailureMode);
  const taxonomies = readYamlDir('taxonomies').map(hydrateTaxonomy);
  const papers = readYamlDir('papers').map(hydratePaper);
  const crosswalks = readYamlDir('crosswalks').map(hydrateCrosswalk);

  // Derived index: failure_mode_id -> tool_ids[]
  const toolsByFailureMode: Record<string, string[]> = {};
  for (const fm of failureModes) toolsByFailureMode[fm.id] = [];
  for (const tool of tools) {
    for (const fmId of tool.addresses_failure_modes) {
      if (!toolsByFailureMode[fmId]) toolsByFailureMode[fmId] = [];
      toolsByFailureMode[fmId].push(tool.id);
    }
  }

  // Derived index: taxonomy_id -> external_id -> failure_mode_ids[]
  // Aggregates both per-FailureMode inline crosswalks and standalone Crosswalk nodes.
  const failureModesByTaxonomyCategory: Record<string, Record<string, string[]>> = {};
  for (const tax of taxonomies) {
    failureModesByTaxonomyCategory[tax.id] = {};
    for (const cat of tax.categories) {
      failureModesByTaxonomyCategory[tax.id][cat.external_id] = [];
    }
  }
  for (const fm of failureModes) {
    for (const cw of fm.crosswalks) {
      const t = cw.taxonomy;
      const e = cw.external_id;
      if (!failureModesByTaxonomyCategory[t]) failureModesByTaxonomyCategory[t] = {};
      if (!failureModesByTaxonomyCategory[t][e]) failureModesByTaxonomyCategory[t][e] = [];
      if (!failureModesByTaxonomyCategory[t][e].includes(fm.id)) {
        failureModesByTaxonomyCategory[t][e].push(fm.id);
      }
    }
  }
  for (const cw of crosswalks) {
    if (cw.saica_axis !== 'failure_mode') continue;
    for (const m of cw.mappings) {
      const t = cw.taxonomy;
      const e = m.external_id;
      if (!failureModesByTaxonomyCategory[t]) failureModesByTaxonomyCategory[t] = {};
      if (!failureModesByTaxonomyCategory[t][e]) failureModesByTaxonomyCategory[t][e] = [];
      if (!failureModesByTaxonomyCategory[t][e].includes(m.saica_value)) {
        failureModesByTaxonomyCategory[t][e].push(m.saica_value);
      }
    }
  }

  // Sort each tool list for stable output.
  for (const fmId of Object.keys(toolsByFailureMode)) {
    toolsByFailureMode[fmId].sort();
  }

  const kgLastUpdated = new Date().toISOString();

  return {
    tools: keyBy(tools),
    failureModes: keyBy(failureModes),
    taxonomies: keyBy(taxonomies),
    papers: keyBy(papers),
    crosswalks: keyBy(crosswalks),
    toolsByFailureMode,
    failureModesByTaxonomyCategory,
    kgVersion: DATA_VERSION,
    kgLastUpdated,
  };
}

// Eagerly loaded graph. Astro runs this once at build-time.
export const graph: Graph = buildGraph();

export const DISCLAIMER =
  'SAICA-KG is navigational, not evaluative. Ranked sets reflect aggregate criteria; no single tool is endorsed.';

export function rawYamlUrl(kind: string, id: string): string {
  // kind: "tools" | "failure_modes" | "papers" | "taxonomies" | "crosswalks"
  return `https://github.com/saica-kg/saica-kg/blob/main/data/${kind}/${id}.yml`;
}

export function counts(): {
  tools: number;
  failure_modes: number;
  papers: number;
  taxonomies: number;
  crosswalks: number;
} {
  // Crosswalks count: number of inline crosswalk edges across all FailureModes
  // plus individual mappings within Crosswalk nodes.
  let inlineCount = 0;
  for (const fm of Object.values(graph.failureModes)) {
    inlineCount += fm.crosswalks.length;
  }
  let bulkCount = 0;
  for (const cw of Object.values(graph.crosswalks)) {
    bulkCount += cw.mappings.length;
  }
  return {
    tools: Object.keys(graph.tools).length,
    failure_modes: Object.keys(graph.failureModes).length,
    papers: Object.keys(graph.papers).length,
    taxonomies: Object.keys(graph.taxonomies).length,
    crosswalks: inlineCount + bulkCount,
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
};

export function facetLabel(facet: keyof typeof FACET_LABELS, value: string): string {
  return FACET_LABELS[facet]?.[value] ?? value;
}

export function failureModeLabel(id: string): string {
  return graph.failureModes[id]?.name ?? id;
}

export function toolLabel(id: string): string {
  return graph.tools[id]?.name ?? id;
}

export function taxonomyLabel(id: string): string {
  return graph.taxonomies[id]?.name ?? id;
}

export function paperLabel(id: string): string {
  const p = graph.papers[id];
  if (!p) return id;
  const firstAuthor = p.authors[0] ?? 'Anon.';
  return `${firstAuthor} (${p.year}) — ${p.title}`;
}
