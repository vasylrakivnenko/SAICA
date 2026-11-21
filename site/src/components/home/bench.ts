// Build-time summaries of /bench/results.json for the static (crawlable) parts of /, /findings/, /benchmark/ and
// /about/. Everything here is computed from the results file, so the pages update when bench/build_report.py reruns.
// URLs go through ../../lib/seo.ts (fmUrl, toolUrl, leaderboardUrl).
import results from '../../../public/bench/results.json';
import kit from '../../../public/bench/kit.json';
import { fmUrl, toolUrl, leaderboardUrl, abs } from '../../lib/seo';
import { graph } from '../../lib/data';

export interface Row {
  key: string;
  tool: string;
  type: string;
  j: number;
  catch: number;
  fa: number;
  cost: number;
  cost_note?: string | null;
  kg_id?: string | null;
  repository_url?: string | null;
}
export interface Mode {
  id: string;
  name: string;
  n: number;
  n_pos: number;
  n_neg: number;
  pos_label: string;
  dataset: string;
  summary: string;
  setup: string[];
  caveats: string[];
  rows: Row[];
}
export interface StarMode {
  id: string;
  name: string;
  description?: string;
  note?: string;
  tools: Array<{ id: string; name: string; stars?: number; repository_url?: string | null }>;
}

export const MODES = results.modes as unknown as Mode[];
export const STAR_MODES = (results.star_modes ?? []) as unknown as StarMode[];
export const OVERVIEW = results.overview as unknown as {
  modes: Array<{ id: string; name: string }>;
  rows: Array<{ tool: string; type: string; avg: number; n_modes: number; cells: Record<string, { j: number; tool: string; short?: string; fa: number; cost1k: number }> }>;
  best: Record<string, { j: number; tool: string; short?: string; type: string }>;
  findings: Array<[string, string]>;
  caveats: string[];
};
export const TYPE_LABEL = results.type_label as Record<string, string>;
export const GENERATED: string = results.generated;
/** "20 November 2026" */
export const GENERATED_LONG = new Date(GENERATED + 'T00:00:00Z').toLocaleDateString('en-GB', {
  day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC',
});

/** Same colour variables as the leaderboard (.lb in pages/index.astro). */
export const TYPE_VAR: Record<string, string> = {
  deterministic: '--t-free', llm_based: '--t-ai', hybrid: '--t-hybrid', prompt_artifact: '--t-skill',
  baseline_model: '--t-base', baseline_rule: '--t-rule',
};

export const pct = (x: number, d = 1) => (x * 100).toFixed(d) + '%';
export const money = (c: number) => (c === 0 ? '$0' : '$' + c.toFixed(2));
export const cost1k = (r: Row, m: Mode) => (r.cost / m.n) * 1000;
export const costLabel = (r: Row, m: Mode) =>
  (r.cost_note && r.cost_note.includes('estimated') ? '~' : '') + money(cost1k(r, m));
export const isFree = (r: Row) => r.cost === 0;
/** A supervision tool from the catalog (not a plain model asked directly, not a one-line rule). */
export const isTool = (r: Row) => !['baseline_model', 'baseline_rule'].includes(r.type);
/** Tool page for a catalog id, or null when the catalog has no such tool (no page to link to). */
export const toolPage = (id?: string | null): string | null => (id && graph.tools[id] ? toolUrl(id) : null);
export const toolHref = (r: Row): string | null => toolPage(r.kg_id);

// Short display names: the overview's for each mode's winner, else the kit builder's, else the tool label trimmed.
const KIT_SHORT: Record<string, Record<string, string>> = Object.fromEntries(
  (kit.modes as Array<{ id: string; rows?: Array<{ key: string; short?: string }> }>).map((m) => [
    m.id,
    Object.fromEntries((m.rows ?? []).filter((r) => r.short).map((r) => [r.key, r.short as string])),
  ]),
);
export function shortName(m: Mode, r: Row): string {
  const b = OVERVIEW.best?.[m.id];
  if (b && b.tool === r.tool && b.short) return b.short;
  return KIT_SHORT[m.id]?.[r.key] ?? r.tool.replace(', asked directly', '').split(' (')[0].split(':')[0];
}

export interface ModeSummary {
  m: Mode;
  url: string; // failure-mode page
  tab: string; // leaderboard tab
  method: string; // benchmark card
  rows: Row[]; // by J, best first
  best: Row;
  free: Row | null; // best $0 entry (free program or simple rule)
  tools: Row[]; // catalog tools only, by J
  samples: number;
}
export const SUMMARIES: ModeSummary[] = MODES.map((m) => {
  const rows = [...m.rows].sort((a, b) => b.j - a.j);
  return {
    m,
    url: fmUrl(m.id),
    tab: leaderboardUrl(m.id),
    method: `/benchmark/#${m.id}`,
    rows,
    best: rows[0],
    free: rows.find(isFree) ?? null,
    tools: rows.filter(isTool),
    samples: m.n_pos + m.n_neg,
  };
});
/** Modes where nothing we ran reaches J 25%: the unsolved ones. */
export const HARD = SUMMARIES.filter((s) => s.best.j < 0.25);
export const TOTAL_SAMPLES = SUMMARIES.reduce((a, s) => a + s.samples, 0);

// How many distinct things were measured: models asked directly, catalog tools, simple rules.
const modelName = (t: string) => t.split(',')[0].split(' on one ')[0].split(' (')[0].trim();
export const COUNTS = (() => {
  const models = new Set<string>(), tools = new Set<string>(), rules = new Set<string>();
  for (const m of MODES)
    for (const r of m.rows) {
      if (r.type === 'baseline_model') models.add(modelName(r.tool));
      else if (r.type === 'baseline_rule') rules.add(r.key);
      else tools.add(r.kg_id ?? r.tool.split(/[ (:]/)[0].toLowerCase());
    }
  return { models: models.size, tools: tools.size, rules: rules.size, results: MODES.reduce((a, m) => a + m.rows.length, 0) };
})();

/** "a, b and c" */
export const andList = (xs: string[]) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);

// Public datasets the benchmark samples come from (matched against each mode's `dataset` text).
export const SOURCES = [
  { name: 'Delulu', match: 'Delulu', by: 'Microsoft', url: 'https://huggingface.co/datasets/microsoft/delulu' },
  { name: 'Patronus TRACE', match: 'TRACE', by: 'Patronus AI', url: 'https://huggingface.co/datasets/PatronusAI/trace-dataset' },
  { name: 'SusVibes', match: 'SusVibes', by: 'LeiLiLab', license: 'MIT', url: 'https://github.com/LeiLiLab/susvibes' },
  { name: 'Collu-Bench', match: 'Collu-Bench', by: 'lt-asset', license: 'BSD-3-Clause-Clear', url: 'https://huggingface.co/datasets/lt-asset/collu-bench' },
  { name: 'SWE-rebench-OpenHands-Trajectories', match: 'SWE-rebench-OpenHands-Trajectories', by: 'Nebius', license: 'CC-BY-4.0', url: 'https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories' },
  { name: "Wang et al.'s deprecated-API map (ICSE'25)", match: 'Wang et al.', by: 'Wang et al.', url: 'https://github.com/cs-wangchong/LLM-Deprecated-API' },
  { name: 'OpenSSF malicious-packages', match: 'OpenSSF malicious-packages', by: 'OpenSSF', url: 'https://github.com/ossf/malicious-packages' },
].map((s) => ({ ...s, modes: MODES.filter((m) => m.dataset.includes(s.match)) }));

export const AUTHOR = {
  '@type': 'Person',
  name: 'Vasyl Rakivnenko',
  affiliation: { '@type': 'Organization', name: 'Stanford University' },
  url: abs('/about/'),
};
