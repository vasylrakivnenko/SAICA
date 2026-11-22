// Catalog-page helpers (tools, papers, incidents, recipes, taxonomies): short "what it is" labels for tools, the
// searchers' phrase for each failure mode, measured SAICA-Bench rows per tool, and title/description builders.
// URL helpers live in ./seo.ts; KG data in ./data.ts; measured numbers in public/bench/results.json.
import maturityData from '../../public/maturity.json';
import { graph } from './data.ts';
import { kgId, clip } from './seo.ts';
import { MODES, type Mode, type Row } from '../components/home/bench.ts';
import { andList, signedPct } from './format.ts';

/** What each catalogued tool is, in a few words (used in titles and descriptions). New tools fall back to kindOf(). */
const TOOL_KIND: Record<string, string> = {
  'agent-governance-toolkit': 'policy enforcement toolkit',
  agenta: 'LLMOps and evaluation platform',
  agno: 'multi-agent framework',
  'ai-infra-guard': 'AI red-teaming platform',
  'arize-phoenix': 'LLM tracing and evaluation platform',
  autogen: 'multi-agent framework',
  bandit: 'Python security linter',
  bifrost: 'AI gateway with guardrails',
  'browser-use': 'browser automation library',
  'context-hub': 'API docs service',
  context7: 'library docs MCP server',
  copilotkit: 'agent UI framework',
  daytona: 'sandboxed dev environment',
  deepeval: 'LLM evaluation framework',
  dependabot: 'dependency update bot',
  e2b: 'code execution sandbox',
  eslint: 'JavaScript and TypeScript linter',
  flowise: 'visual agent builder',
  garak: 'LLM vulnerability scanner',
  'guardrails-ai': 'LLM output validation framework',
  langgraph: 'agent orchestration framework',
  letta: 'stateful agent framework',
  litellm: 'LLM proxy and SDK',
  'llm-guard': 'LLM security toolkit',
  mastra: 'TypeScript agent framework',
  'mcp-toolbox': 'database MCP server',
  mlflow: 'ML and LLM evaluation platform',
  modal: 'serverless code sandbox',
  mypy: 'Python type checker',
  'nemo-guardrails': 'programmable guardrails framework',
  nono: 'agent sandbox',
  opik: 'LLM evaluation and tracing platform',
  'playwright-mcp': 'browser automation MCP server',
  'pr-agent': 'AI pull-request reviewer',
  promptfoo: 'LLM eval and red-teaming tool',
  'pydantic-ai': 'typed agent framework',
  pyright: 'Python type checker',
  pyrit: 'generative AI risk-testing tool',
  pytest: 'Python test framework',
  renovate: 'dependency update bot',
  ruff: 'Python linter',
  semgrep: 'static analysis tool',
  sentrux: 'code architecture sensor',
  smolagents: 'code-agent library',
  snyk: 'vulnerability scanner',
  socket: 'package supply-chain scanner',
  superagent: 'AI app security layer',
  trulens: 'LLM evaluation and tracing library',
  uqlm: 'LLM uncertainty scoring library',
};

const PARADIGM_KIND: Record<string, string> = {
  prevention: 'prevention tool',
  detection: 'detection tool',
  correction: 'correction tool',
  recovery: 'recovery tool',
};

/** Short noun phrase for what a tool is ("Python type checker"). */
export function kindOf(toolId: string): string {
  const t = graph.tools[toolId];
  return TOOL_KIND[toolId] ?? PARADIGM_KIND[t?.control_paradigm ?? ''] ?? 'supervision tool';
}

/** How people search for each failure mode (KG id -> phrase); the KG name stays the defined term. */
const FM_PHRASE: Record<string, string> = {
  fabrication: 'hallucinated APIs and imports',
  obsolescence: 'deprecated APIs',
  logic_error: 'logic errors',
  security_vulnerability: 'security vulnerabilities',
  incomplete_execution: 'false completion claims',
  test_manipulation: 'test manipulation (reward hacking)',
  scope_creep: 'scope creep',
  supply_chain_attack: 'slopsquatting and typosquatting',
  dependency_blindness: 'reinvented existing code',
  context_pollution: 'context pollution',
  cascading_failure: 'cascading failures',
};
/** Shorter forms for running text, where a phrase with its own "and" would garble a list. */
const FM_SHORT: Record<string, string> = {
  fabrication: 'hallucinated APIs',
  test_manipulation: 'test manipulation',
  supply_chain_attack: 'supply-chain attacks',
};
/** Searchers' phrase for a failure mode (KG id or leaderboard mode id); `short` for use inside lists. */
export const fmPhrase = (id: string, short = false): string =>
  (short ? FM_SHORT[kgId(id)] : undefined) ??
  FM_PHRASE[kgId(id)] ??
  (graph.failureModes[kgId(id)]?.name ?? id).toLowerCase();
/** KG display name for a failure mode (KG id or leaderboard mode id). */
export const fmName = (id: string): string => graph.failureModes[kgId(id)]?.name ?? id;

export { andList };

/** First candidate no longer than `max` characters (else the last one), for titles. */
export function fit(candidates: string[], max = 60): string {
  return candidates.find((c) => c.length <= max) ?? candidates[candidates.length - 1];
}

// ---------- Measured results (public/bench/results.json, through components/home/bench.ts) ----------

/** One results row of a catalog tool, with the mode it belongs to. */
export interface MeasuredRow {
  m: Mode;
  row: Row;
}

/** Every results row measured for a catalog tool, in the file's mode order; inside a mode ranked rows first,
 *  then by J. A row is one configuration on one set: read it with its run card. */
export function measuredFor(toolId: string): MeasuredRow[] {
  return MODES.flatMap((m) =>
    m.rows
      .filter((r) => r.kg_id === toolId)
      .sort((a, b) => Number(b.ranked) - Number(a.ranked) || b.j - a.j)
      .map((row) => ({ m, row })),
  );
}

/** The tool's best ranked row per mode (modes where it only has rows outside the ranking are left out). */
export function rankedBestPerMode(rows: MeasuredRow[]): MeasuredRow[] {
  const best = new Map<string, MeasuredRow>();
  for (const r of rows) if (r.row.ranked && !best.has(r.m.id)) best.set(r.m.id, r);
  return [...best.values()];
}

// ---------- Tool page title + description ----------

export function toolTitle(toolId: string): string {
  const t = graph.tools[toolId];
  const name = t?.name ?? toolId;
  const kind = kindOf(toolId);
  if (measuredFor(toolId).length > 0) {
    return fit([`${name}: ${kind}, measured on SAICA-Bench`, `${name}: measured on SAICA-Bench`]);
  }
  return fit([`${name}: ${kind} for AI coding agents`, `${name}: ${kind} for coding agents`, `${name}: ${kind}`]);
}

const VERB: Record<string, string> = { prevention: 'prevent', detection: 'catch', correction: 'fix', recovery: 'contain' };

export function toolDescription(toolId: string): string {
  const t = graph.tools[toolId];
  const name = t?.name ?? toolId;
  const kind = kindOf(toolId);
  const article = /^(?:[aeiou]|LLM|ML\b|MCP|SDK)/i.test(kind) ? 'an' : 'a';
  const raw = (t?.tagline ?? '').trim();
  const tagline = raw && !/[.!?]$/.test(raw) ? `${raw}.` : raw;
  const all = measuredFor(toolId);
  const best = rankedBestPerMode(all);
  if (best.length > 0) {
    // What one configuration scored on one set each; never a statement about the tool in general.
    const parts = best.map((r, i) => `${i === 0 ? 'J ' : ''}${signedPct(r.row.j, 0)} on ${fmPhrase(r.m.id, true)}`);
    return clip(`${name} is ${article} ${kind}. On SAICA-Bench, in the configuration we ran: ${andList(parts)}.`, 155);
  }
  if (all.length > 0) {
    return clip(`${name} is ${article} ${kind}. SAICA-Bench ran it outside its design scope, for reference only; it is not ranked there.`, 155);
  }
  // Not measured: what it is and what the catalog tags it for, then the upstream tagline.
  const fms = (t?.addresses_failure_modes ?? []).map((f) => fmPhrase(f, true));
  const list = fms.length > 2 ? `${fms.slice(0, 2).join(', ')} and other failures` : andList(fms);
  const lead = fms.length
    ? `${name} is ${article} ${kind} that can help ${VERB[t?.control_paradigm ?? ''] ?? 'address'} ${list} in AI coding agents.`
    : `${name} is ${article} ${kind} for supervising AI coding agents.`;
  return clip(`${lead} ${tagline}`, 155);
}

// ---------- Activity band (public/maturity.json, written by validator/generate_maturity.py) ----------
//
// A band (A to F) is a bin of a score that adds up stars, a recent upstream push and the number of integration
// surfaces: popularity and activity, not evidence. Until 2026-11-21 the bands were called "maturity tiers"
// 1A … 4, names borrowed from clinical evidence levels that the score never checked. The file's version 2
// carries `band`, `computed_band`, `scale` and `as_of`; version 1 has only the old `tier` names, which are
// mapped here so the pages read either file.

const LEGACY_BAND: Record<string, string> = { '1A': 'A', '1B': 'B', '2A': 'C', '2B': 'D', '3': 'E', '4': 'F' };
const toBand = (v: unknown): string => LEGACY_BAND[String(v)] ?? String(v ?? '');

export const BAND_COLORS: Record<string, string> = {
  A: 'bg-emerald-600 text-white',
  B: 'bg-emerald-500 text-white',
  C: 'bg-amber-400 text-stone-900',
  D: 'bg-amber-300 text-stone-900',
  E: 'bg-orange-400 text-stone-900',
  F: 'bg-stone-400 text-white',
};

export interface ActivityBand {
  /** The band shown (after a curator override, if any). */
  band: string;
  /** The band the score gives before an override. */
  computedBand: string;
  score: number;
  facets: Record<string, number>;
  notes: string[];
  isOverride: boolean;
  override: { justification: string; by?: string; at?: string } | null;
}

const maturity = maturityData as unknown as {
  as_of?: string;
  scale?: { description?: string };
  tools: Record<string, Record<string, any>>;
};

/** What a band is, in one paragraph (the generator's own text when the file has it). */
export const BAND_DESCRIPTION: string =
  maturity.scale?.description ??
  'Activity band A to F: a bin of a score that adds GitHub stars, a recent push to the upstream repository and ' +
    'the number of integration surfaces. It measures popularity and activity. It is not a level of evidence.';
/** The date recency was judged against, when the file states it. */
export const BAND_AS_OF: string | null = maturity.as_of ?? null;

export function activityBand(toolId: string): ActivityBand | null {
  const row = maturity.tools[toolId];
  if (!row) return null;
  return {
    band: toBand(row.band ?? row.tier),
    computedBand: toBand(row.computed_band ?? row.computed_tier),
    score: row.score,
    facets: row.facets ?? {},
    notes: row.notes ?? [],
    isOverride: Boolean(row.is_override),
    override: row.override ?? null,
  };
}

// ---------- Crosswalks: who drafted and who checked them ----------

/** What a page prints for one crosswalk file's `review_state` (schema/crosswalk.schema.json). The sentence for
 *  `llm_drafted_unreviewed` is fixed wording. Empty when the file states nothing. */
const REVIEW_NOTE: Record<string, string> = {
  llm_drafted_unreviewed: 'Mapping drafted by an AI model from the source text; not yet reviewed by a person.',
  human_reviewed: 'Mapping reviewed by a person against the source text.',
};
export const reviewNote = (state: string | undefined): string => (state ? (REVIEW_NOTE[state] ?? `Review state: ${state.replace(/_/g, ' ')}.`) : '');

/** The review notes of several taxonomies' crosswalks, one line per distinct note: the note alone when it holds
 *  for all of them, else prefixed with the taxonomies it holds for. */
export function reviewNotes(taxa: Array<{ name: string; states: Array<string | undefined> }>): string[] {
  const by = new Map<string, string[]>();
  for (const t of taxa) {
    for (const note of new Set(t.states.map(reviewNote).filter(Boolean))) by.set(note, [...(by.get(note) ?? []), t.name]);
  }
  return [...by.entries()].map(([note, names]) => (names.length === taxa.length ? note : `${andList(names)}: ${note}`));
}

// ---------- Incident records: what kind of record each one is ----------

/** Incident.kind (schema/incident.schema.json): only `event` is an incident in the plain sense. A record
 *  with no kind yet is not called an incident either. */
const INCIDENT_KIND: Record<string, { label: string; note: string }> = {
  event: { label: 'Incident', note: '' },
  study: {
    label: 'Study finding',
    note: 'This record is a measurement reported by a paper or a vendor, not a single dated incident.',
  },
  pattern: {
    label: 'Reported pattern',
    note: 'This record is a recurring behaviour with no single dated occurrence, not one incident.',
  },
  hypothetical: {
    label: 'Hypothetical scenario',
    note: 'This record is a scenario that its own source calls hypothetical; it did not happen.',
  },
};
const UNCLASSIFIED = {
  label: 'Not classified yet',
  note: 'This record has not been classified as an incident, a study finding or a reported pattern yet.',
};

export const isEvent = (incident: { kind?: string }): boolean => incident.kind === 'event';
export const incidentKind = (incident: { kind?: string }): { label: string; note: string } =>
  INCIDENT_KIND[incident.kind ?? ''] ?? UNCLASSIFIED;

// ---------- Duplicate paper records ----------

const norm = (v: unknown): string => String(v ?? '').trim().toLowerCase().replace(/\/+$/, '');
const completeness = (id: string): number => {
  const p = graph.papers[id];
  return [p.arxiv_id, p.doi, p.semantic_scholar_id, p.abstract, p.tldr, p.venue, p.citation_count].filter(
    (v) => v !== undefined && v !== null && v !== '',
  ).length;
};

/** Paper records that describe the same work (same URL, DOI, arXiv or Semantic Scholar id): duplicate id -> primary id.
 *  The primary is the most complete record. Duplicates still get a page, marked noindex and pointing to the primary. */
export const paperDuplicates: Record<string, string> = (() => {
  const byKey = new Map<string, string[]>();
  for (const p of Object.values(graph.papers)) {
    for (const [k, v] of [['url', p.url], ['doi', p.doi], ['arxiv', p.arxiv_id], ['s2', p.semantic_scholar_id]] as const) {
      if (!v) continue;
      const key = `${k}:${norm(v)}`;
      byKey.set(key, [...(byKey.get(key) ?? []), p.id]);
    }
  }
  const out: Record<string, string> = {};
  for (const ids of byKey.values()) {
    const group = [...new Set(ids)];
    if (group.length < 2) continue;
    const primary = group.slice().sort((a, b) => completeness(b) - completeness(a) || a.localeCompare(b))[0];
    for (const id of group) if (id !== primary && !out[id]) out[id] = primary;
  }
  return out;
})();
