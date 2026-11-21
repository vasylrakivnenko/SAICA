// Catalog-page helpers (tools, papers, incidents, recipes, taxonomies): short "what it is" labels for tools, the
// searchers' phrase for each failure mode, measured SAICA-Bench rows per tool, and title/description builders.
// URL helpers live in ./seo.ts; KG data in ./data.ts; measured numbers in public/bench/results.json.
import results from '../../public/bench/results.json';
import { graph } from './data.ts';
import { kgId, clip } from './seo.ts';

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

/** "a, b and c" */
export function andList(items: string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

/** First candidate no longer than `max` characters (else the last one), for titles. */
export function fit(candidates: string[], max = 60): string {
  return candidates.find((c) => c.length <= max) ?? candidates[candidates.length - 1];
}

// ---------- Measured results (public/bench/results.json) ----------

interface BenchRow {
  kg_id?: string;
  tool: string;
  type: string;
  j: number;
  catch: number;
  fa: number;
  cost: number;
  cost_note?: string;
}
interface BenchMode {
  id: string;
  name: string;
  n: string | number;
  rows: BenchRow[];
}
const bench = results as unknown as { generated: string; type_label: Record<string, string>; modes: BenchMode[] };

export interface MeasuredRow {
  /** Leaderboard mode id (e.g. "security"). */
  modeId: string;
  /** KG failure-mode id (e.g. "security_vulnerability"). */
  fmId: string;
  /** Configuration label as on the leaderboard ("mypy --check-untyped-defs"). */
  config: string;
  typeLabel: string;
  j: number;
  tpr: number;
  fpr: number;
  /** Cost per 1,000 reviews in USD (run cost / reviews in the mode * 1000). */
  cost1k: number;
  estimated: boolean;
}

export const benchGenerated = bench.generated;

/** Every leaderboard row measured for a KG tool, in leaderboard mode order, best J first within a mode. */
export function measuredFor(toolId: string): MeasuredRow[] {
  const out: MeasuredRow[] = [];
  for (const m of bench.modes) {
    const n = Number(m.n);
    const rows = m.rows
      .filter((r) => r.kg_id === toolId)
      .map((r) => ({
        modeId: m.id,
        fmId: kgId(m.id),
        config: r.tool,
        typeLabel: bench.type_label[r.type] ?? r.type,
        j: r.j,
        tpr: r.catch,
        fpr: r.fa,
        cost1k: n > 0 ? (r.cost / n) * 1000 : 0,
        estimated: (r.cost_note ?? '').includes('estimated'),
      }))
      .sort((a, b) => b.j - a.j);
    out.push(...rows);
  }
  return out;
}

/** Best row per failure mode, best J first. */
export function bestPerMode(rows: MeasuredRow[]): MeasuredRow[] {
  const best = new Map<string, MeasuredRow>();
  for (const r of rows) if (!best.has(r.modeId) || r.j > best.get(r.modeId)!.j) best.set(r.modeId, r);
  return [...best.values()].sort((a, b) => b.j - a.j);
}

export const pct = (x: number): string => `${(x * 100).toFixed(1)}%`;
export const money = (usd: number, estimated = false): string =>
  usd === 0 ? '$0' : `${estimated ? '~' : ''}$${usd.toFixed(2)}`;

// ---------- Tool page title + description ----------

export function toolTitle(toolId: string): string {
  const t = graph.tools[toolId];
  const name = t?.name ?? toolId;
  const kind = kindOf(toolId);
  if (measuredFor(toolId).length > 0) {
    return fit([`${name}: measured results on AI coding agent failures`, `${name}: measured on AI coding agent failures`]);
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
  const best = bestPerMode(measuredFor(toolId));
  if (best.length > 0) {
    const parts = best.map((r, i) => `${i === 0 ? 'J ' : ''}${pct(r.j)} on ${fmPhrase(r.fmId, true)}`);
    const free = best.every((r) => r.cost1k === 0) ? ', at no cost' : '';
    return clip(`${name} is ${article} ${kind}. Measured on SAICA-Bench against AI coding agent failures: ${andList(parts)}${free}.`, 155);
  }
  // Not measured: what it is and what the catalog tags it for, then the upstream tagline.
  const fms = (t?.addresses_failure_modes ?? []).map((f) => fmPhrase(f, true));
  const list = fms.length > 2 ? `${fms.slice(0, 2).join(', ')} and other failures` : andList(fms);
  const lead = fms.length
    ? `${name} is ${article} ${kind} that can help ${VERB[t?.control_paradigm ?? ''] ?? 'address'} ${list} in AI coding agents.`
    : `${name} is ${article} ${kind} for supervising AI coding agents.`;
  return clip(`${lead} ${tagline}`, 155);
}

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
