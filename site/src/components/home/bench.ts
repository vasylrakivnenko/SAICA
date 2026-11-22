// The one build-time view of the published benchmark results (public/bench/results.json, written by
// bench/build_report.py). Every page and component that prints a benchmark number, name, count, tier or sentence
// takes it from here. Nothing in this file is a typed-in result: values are read from the file or computed from
// its fields, and the ready sentences are the file's own (overview.findings, overview.caveats, mode.ranking,
// mode.tuning_disclosure, method.*, threats[]). When the file is rebuilt the pages follow without an edit;
// `node scripts/check-results-mutation.mjs` proves that on a changed copy of the file.
//
// Reading rules that the file sets (results.method.best), kept by every selector below:
// - a mode's best reviewer is mode.best_reviewer, the best RANKED row; never rows[0];
// - baseline rules, shortcut baselines and rows outside a tool's design scope are not ranked and are never
//   named as best;
// - one winner is named only when mode.winner is set; otherwise the rows of mode.top_group are named together;
// - when mode.below_floor is true no reviewer is named at all.
//
// URLs go through ../../lib/seo.ts; number formats through ../../lib/format.ts.
import results from '../../../public/bench/results.json';
import { fmUrl, toolUrl, leaderboardUrl, abs, kgId } from '../../lib/seo';
import { graph } from '../../lib/data';
import { andList, money, pct, signedPct } from '../../lib/format';

// ---------- shape of results.json (version 2) ----------

export interface RunCard {
  version?: string;
  model?: string;
  judge_model?: string;
  provider?: string;
  input?: string;
  flag_rule?: string;
  temperature?: number;
  max_tokens?: number;
  deviations?: string[];
  runs?: number;
  failed_runs?: number;
  failed_share?: number;
  failed_causes?: Record<string, number>;
  [key: string]: unknown;
}

export interface Row {
  key: string;
  /** Full label of the configuration that ran. */
  tool: string;
  /** Display name. */
  short: string;
  /** deterministic | llm_based | hybrid | prompt_artifact | baseline_model | baseline_rule (labels: type_label). */
  type: string;
  /** model | catalog_tool | uncatalogued_tool | baseline_rule | shortcut_baseline (labels: kind_label). */
  kind: string;
  /** "own check" | "our rubric" | null. */
  check: string | null;
  /** "in the catalog" | "benchmarked, not in the catalog" | null. */
  catalog: string | null;
  j: number;
  j_ci: [number, number];
  catch: number;
  catch_ci: [number, number];
  fa: number;
  fa_ci: [number, number];
  n_pos: number;
  n_neg: number;
  n_pos_readable: number;
  n_neg_readable: number;
  /** Answers with no verdict: left out of the rates, counted here. */
  unreadable: number;
  unreadable_pos: number;
  unreadable_neg: number;
  unreadable_causes: Record<string, number>;
  /** Under 95% readable answers in one class. */
  incomplete: boolean;
  subset_n: { pos: number; neg: number } | null;
  /** USD per 1,000 reviews. */
  cost1k: number;
  /** USD for the whole run of this row (list or reported price). */
  cost: number;
  cost_basis: string;
  cost_estimated: boolean;
  /** USD really spent on this row's run. */
  spend: number;
  cost_note: string;
  /** False alarms per 100 clean changes. */
  fa_per_100: number;
  /** Precision at each prevalence of results.prevalences (keys are the prevalences as text). */
  ppv: Record<string, number>;
  scope: string;
  scope_note?: string;
  ranked: boolean;
  unranked_reason?: string;
  rank?: number;
  in_top_group?: boolean;
  vs_best?: { n: number; diff: number; lo: number; hi: number; separable: boolean; unit: string };
  role?: string;
  description?: string;
  judge?: string;
  kg_id?: string;
  repository_url?: string;
  stars?: number;
  stars_updated_at?: string;
  run_card?: RunCard;
}

/** The short form of a row that the file repeats in best_reviewer / best_catalog_tool / best_free_program. */
export interface RowRef {
  key: string;
  tool: string;
  short: string;
  type: string;
  kind: string;
  j: number;
  j_ci: [number, number];
  catch: number;
  fa: number;
  cost1k: number;
}

export interface StratumRow {
  tpr: number;
  fpr: number;
  j: number;
  j_lo: number;
  j_hi: number;
  tp: number;
  fp: number;
  n_pos: number;
  n_neg: number;
  unreadable?: number;
}
export interface Stratum {
  description?: string;
  n_pos?: number;
  n_neg?: number;
  rows?: Record<string, StratumRow>;
}

export interface Mode {
  id: string;
  /** Name of the failure mode (the knowledge-graph tag). */
  name: string;
  /** What the set scores, when that is narrower than the mode's name. */
  title: string;
  n: number;
  n_pos: number;
  n_neg: number;
  n_not_scored: number;
  prevalence: number;
  pos_label: string;
  dataset: string;
  dataset_version: string;
  summary: string;
  provenance: { positives: string; author: string; label_source: string; agent_output: boolean; negatives: string };
  /** natural_agent | natural_other | constructed (labels: overview.groups). */
  group: string;
  unit: string;
  cluster: { unit: string; n_clusters: number } | null;
  sources: Array<{ name: string; url: string; public_since?: string; note?: string }>;
  setup: string[];
  caveats: string[];
  rows: Row[];
  shortcut_audit: string;
  tuning_disclosure: string | null;
  best_reviewer: RowRef;
  top_group: string[];
  winner: string | null;
  /** well | partly | not-yet (labels: results.tiers). */
  tier: string;
  tier_label: string;
  floor: number;
  below_floor: boolean;
  /** One ready sentence that follows the naming rules above. */
  ranking: string;
  best_catalog_tool: RowRef | null;
  catalog_top_group: string[];
  best_free_program: RowRef | null;
  spend: number;
  strata?: Record<string, Stratum> | null;
  tables?: Record<string, unknown> | null;
}

export interface StarMode {
  id: string;
  fm?: string;
  name: string;
  description?: string;
  note?: string;
  tools: Array<{
    id: string;
    name: string;
    stars?: number;
    stars_updated_at?: string;
    repository_url?: string | null;
    implementation?: string;
    mechanism?: string;
    how?: string;
    runs_on_finished_change?: boolean | null;
  }>;
}

export interface OverviewCell {
  key: string;
  j: number;
  j_ci: [number, number];
  tool: string;
  short: string;
  fa: number;
  cost1k: number;
  unreadable: number;
  ranked: boolean;
}
export interface OverviewRow {
  tool: string;
  type: string;
  kind: string | null;
  cells: Record<string, OverviewCell>;
}
export interface Group {
  id: string;
  label: string;
  description: string;
  modes: string[];
}
export interface Threat {
  id: string;
  threat: string;
  modes: string[];
  status: string;
  note: string;
}
export interface UnionEstimate {
  what: string;
  status: string;
  assumption: string;
  above_floor_note?: string;
  rows: Array<{
    model: string;
    n_prompts: number;
    any_flag: number;
    expected_false_alarms_per_clean_change: number;
    cost1k_all_prompts: number;
    above_floor?: { n_prompts: number; any_flag: number };
  }>;
}

interface Results {
  version: string;
  generated: string;
  commit?: string;
  cite_as: string;
  partial: boolean;
  missing_modes: Record<string, unknown>;
  floor: number;
  tiers: Array<{ id: string; min: number | null; label: string }>;
  prevalences: number[];
  cheap_cost1k: number;
  type_label: Record<string, string>;
  kind_label: Record<string, string>;
  method: Record<string, string> & { units?: unknown };
  threats: Threat[];
  modes: Mode[];
  star_modes?: StarMode[];
  overview: {
    modes: Array<{ id: string; name: string; group: string }>;
    groups: Group[];
    rows: OverviewRow[];
    findings: Array<[string, string]>;
    caveats: string[];
    union_false_alarm?: UnionEstimate;
    counts: Record<string, number>;
  };
}

const R = results as unknown as Results;

// ---------- top level ----------

export const VERSION: string = R.version;
export const CITE_AS: string = R.cite_as;
/** UTC date of the build of the results file, YYYY-MM-DD. */
export const GENERATED: string = R.generated;
/** The same date in words, e.g. "22 November 2026". */
export const GENERATED_LONG = new Date(GENERATED + 'T00:00:00Z').toLocaleDateString('en-GB', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'UTC',
});
/** True only for a build made with --allow-missing: pages show a banner. */
export const PARTIAL: boolean = Boolean(R.partial);
export const MISSING_MODES: string[] = Object.keys(R.missing_modes ?? {});
/** Below this J no reviewer is named (the file's one floor constant). */
export const FLOOR: number = R.floor;
export const TIERS = R.tiers;
/** Prevalences at which each row's precision is given (row.ppv). */
export const PREVALENCES: number[] = R.prevalences;
export const TYPE_LABEL: Record<string, string> = R.type_label;
export const KIND_LABEL: Record<string, string> = R.kind_label;
/** Ready sentences about the method: setting, metric, unreadable, intervals, paired, best, tiers, cost, cheap. */
export const METHOD = R.method as Record<string, string>;
export const THREATS: Threat[] = R.threats ?? [];
export const STAR_MODES: StarMode[] = R.star_modes ?? [];
export const FINDINGS = R.overview.findings;
export const CAVEATS = R.overview.caveats;
export const UNION = R.overview.union_false_alarm ?? null;
/** Counts the file states about itself: modes, constructed, natural, agent_output, rows, ranked_rows, samples… */
export const COUNTS: Record<string, number> = R.overview.counts;
export const OVERVIEW_ROWS: OverviewRow[] = R.overview.rows;

/** Same colour variables as the leaderboard (.lb in pages/index.astro), by row type. */
export const TYPE_VAR: Record<string, string> = {
  deterministic: '--t-free',
  llm_based: '--t-ai',
  hybrid: '--t-hybrid',
  prompt_artifact: '--t-skill',
  baseline_model: '--t-base',
  baseline_rule: '--t-rule',
};

// ---------- modes ----------

const BY_ID = new Map(R.modes.map((m) => [m.id, m]));
export const modeById = (id: string): Mode | undefined => BY_ID.get(id);
/** Measured mode for a knowledge-graph failure-mode id (or a leaderboard mode id), if it is benchmarked. */
export const modeByFm = (fmId: string): Mode | undefined => R.modes.find((m) => kgId(m.id) === kgId(fmId));

/** Every measured mode in the file's neutral order: by provenance group, then by name (overview.modes). */
export const MODES: Mode[] = R.overview.modes.map((o) => BY_ID.get(o.id)).filter((m): m is Mode => Boolean(m));
/** The provenance groups with their modes. Results are always shown one block per group, never as one ranking. */
export const GROUPS: Array<Group & { list: Mode[] }> = R.overview.groups.map((g) => ({
  ...g,
  list: g.modes.map((id) => BY_ID.get(id)).filter((m): m is Mode => Boolean(m)),
}));
export const groupOf = (m: Mode): Group | undefined => R.overview.groups.find((g) => g.id === m.group);

/** URLs that belong to a mode. */
export const modeLinks = (m: Mode) => ({
  page: fmUrl(m.id),
  tab: leaderboardUrl(m.id),
  method: `/benchmark/#${m.id}`,
});
/** "False 'done' claims (Incomplete execution)" when the set scores something narrower than the mode's name. */
export const modeTitle = (m: Mode): string => (m.title && m.title !== m.name ? `${m.title} (${m.name})` : m.name);
/** Scored samples of a mode. */
export const samplesOf = (m: Mode): number => m.n_pos + m.n_neg;

// ---------- rows ----------

export const rowByKey = (m: Mode, key: string): Row | undefined => m.rows.find((r) => r.key === key);
/** The ranked rows of a mode, best first (the file's own rank). */
export const rankedRows = (m: Mode): Row[] =>
  m.rows.filter((r) => r.ranked).sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity));
const UNRANKED_ORDER = ['catalog_tool', 'uncatalogued_tool', 'model', 'baseline_rule', 'shortcut_baseline'];
/** Rows that are shown for reference and never ranked: tools outside their design scope, baseline rules,
 *  shortcut baselines (in that order, highest J first inside each). */
export const unrankedRows = (m: Mode): Row[] =>
  m.rows
    .filter((r) => !r.ranked)
    .sort((a, b) => UNRANKED_ORDER.indexOf(a.kind) - UNRANKED_ORDER.indexOf(b.kind) || b.j - a.j);
/** The shortcut baseline with the highest J: what a rule with no understanding of the failure scores. */
export const topShortcut = (m: Mode): Row | null =>
  m.rows.filter((r) => r.kind === 'shortcut_baseline').sort((a, b) => b.j - a.j)[0] ?? null;
export const isBaseline = (r: Row): boolean => r.kind === 'baseline_rule' || r.kind === 'shortcut_baseline';

/** Tool page for a catalog id, or null when the catalog has no such tool (no page to link to). */
export const toolPage = (id?: string | null): string | null => (id && graph.tools[id] ? toolUrl(id) : null);
export const rowHref = (r: { kg_id?: string }): string | null => toolPage(r.kg_id);

/** Short tags that say what a row is: kind, type of tool, whose check it ran, judge model. All from the file. */
export function rowTags(r: Row): string[] {
  const tags: string[] = [];
  if (r.kind === 'uncatalogued_tool' && r.catalog) tags.push(r.catalog);
  else tags.push(KIND_LABEL[r.kind] ?? r.kind);
  if (r.kind === 'catalog_tool' || r.kind === 'uncatalogued_tool') tags.push(TYPE_LABEL[r.type] ?? r.type);
  if (r.check) tags.push(r.check);
  if (r.judge) tags.push(`judge model ${r.judge}`);
  if (r.role && r.kind !== 'shortcut_baseline') tags.push(r.role);
  else if (r.role && r.role !== 'shortcut') tags.push(r.role);
  if (r.scope && r.scope !== 'in design scope') tags.push(r.scope);
  return tags;
}

// ---------- who is best (the naming rules in one place) ----------

export type BestState = 'winner' | 'top-group' | 'below-floor';
export const bestState = (m: Mode): BestState => (m.below_floor ? 'below-floor' : m.winner ? 'winner' : 'top-group');
/** Rows that may be named for a mode: the winner, or the whole top group; none under the floor. */
export function namedRows(m: Mode): Row[] {
  if (m.below_floor) return [];
  const keys = m.winner ? [m.winner] : m.top_group;
  return keys.map((k) => rowByKey(m, k)).filter((r): r is Row => Boolean(r));
}
/** Who is best, in a few words, by the file's rules: one name, "top group of 4: a, b and 2 more", or
 *  "no reviewer reaches J 25%". Never a baseline or a row outside the ranking. */
export function bestLabel(m: Mode, limit = 3): string {
  if (m.below_floor) return `no reviewer reaches J ${pct(m.floor, 0)}`;
  const rows = namedRows(m);
  if (m.winner && rows.length === 1) return rows[0].short;
  const names = rows.map((r) => r.short);
  const shown = names.length > limit ? [...names.slice(0, limit - 1), `${names.length - (limit - 1)} more`] : names;
  return `top group of ${names.length}: ${andList(shown)}`;
}
/** The highest J of a mode's ranked rows with its 95% interval: "+94.3% (95% interval +91.7% to +96.7%)". */
export const highestJ = (m: Mode, digits = 1): string =>
  `${signedPct(m.best_reviewer.j, digits)} (95% interval ${signedPct(m.best_reviewer.j_ci[0], digits)} to ${signedPct(m.best_reviewer.j_ci[1], digits)})`;

/** One clause for meta descriptions and one-line summaries, by the same rules. */
export function bestClause(m: Mode): string {
  const j = signedPct(m.best_reviewer.j, 0);
  if (m.below_floor) return `no reviewer reaches J ${pct(m.floor, 0)} (highest ${j})`;
  if (m.winner) return `best reviewer ${m.best_reviewer.short}, J ${j}`;
  return `highest J ${j}, ${m.top_group.length} reviewers tied`;
}

// ---------- counts computed from the rows ----------

const distinct = (xs: string[]) => new Set(xs).size;
const allRows = R.modes.flatMap((m) => m.rows);
/** How many different things were run, counted from the rows (models by name, tools by catalog id or name). */
export const RAN = {
  models: distinct(allRows.filter((r) => r.kind === 'model').map((r) => r.short)),
  tools: distinct(
    allRows.filter((r) => r.kind === 'catalog_tool' || r.kind === 'uncatalogued_tool').map((r) => r.kg_id ?? r.short),
  ),
  catalogTools: distinct(allRows.filter((r) => r.kind === 'catalog_tool').map((r) => r.kg_id ?? r.short)),
  baselines: distinct(allRows.filter(isBaseline).map((r) => r.key)),
  /** Simple rules written for the benchmark (shortcut baselines not counted). */
  rules: distinct(allRows.filter((r) => r.kind === 'baseline_rule').map((r) => r.key)),
};
export const TOTAL_SAMPLES: number = COUNTS.samples ?? R.modes.reduce((a, m) => a + samplesOf(m), 0);

// ---------- sources ----------

/** Public datasets the samples come from, each with the modes that use it (mode.sources in the file). */
export const SOURCES = (() => {
  const byName = new Map<string, { name: string; url: string; public_since?: string; note?: string; modes: Mode[] }>();
  for (const m of MODES) {
    for (const s of m.sources ?? []) {
      const have = byName.get(s.name);
      if (have) have.modes.push(m);
      else byName.set(s.name, { ...s, modes: [m] });
    }
  }
  return [...byName.values()];
})();

// ---------- per-mode summaries (also read by pages/tool-coverage.astro of the kit track) ----------

export interface ModeSummary {
  m: Mode;
  /** Failure-mode page. */
  url: string;
  /** Leaderboard tab. */
  tab: string;
  /** Benchmark card. */
  method: string;
  /** Ranked rows, best first. */
  rows: Row[];
  /** The best ranked row (mode.best_reviewer). Name it only through bestLabel(): it may be one of a tied group. */
  best: RowRef;
  /** Best free catalog program that ran its own check inside its design scope, or null. */
  free: RowRef | null;
  samples: number;
}
export const SUMMARIES: ModeSummary[] = MODES.map((m) => ({
  m,
  ...{ url: modeLinks(m).page, tab: modeLinks(m).tab, method: modeLinks(m).method },
  rows: rankedRows(m),
  best: m.best_reviewer,
  free: m.best_free_program,
  samples: samplesOf(m),
}));

export const AUTHOR = {
  '@type': 'Person',
  name: 'Vasyl Rakivnenko',
  affiliation: { '@type': 'Organization', name: 'Stanford University' },
  url: abs('/about/'),
};

// Number formats for the pages that import everything from here.
export { andList, int, interval, money, num, pct, plural, signedPct } from '../../lib/format';

// ---------- classic layout ----------
// The leaderboard grid, the quality-vs-cost charts, the short findings and the per-mode tables of the pages
// (/, /findings/, /failure-modes/, /benchmark/). One matrix, one number per cell; intervals, unreadable counts and
// run cards stay in results.json and in tooltips. Everything below is computed from the results file.

const OVR = R.overview as unknown as {
  modes: Array<{ id: string; name: string }>;
  rows: Array<OverviewRow & { tool: string; type: string; kind: string | null; avg: number; n_modes: number; all_modes?: boolean }>;
  best: Record<string, { j: number; tool: string; short: string; type: string; key: string; winner: boolean; below_floor: boolean; top_group: string[] }>;
  wrapper_comparisons?: Array<{ verdict: string; judge_model?: string }>;
};

/** USD per 1,000 reviews of a row. */
export const cost1k = (r: { cost1k: number }, _m?: Mode): number => r.cost1k;
export const costLabel = (r: { cost1k: number; cost_estimated?: boolean }, _m?: Mode): string => money(r.cost1k, Boolean(r.cost_estimated));
export const isFree = (r: { cost1k: number }): boolean => r.cost1k === 0;
/** A supervision tool (not a plain zero-shot model, not a rule). */
export const isTool = (r: { kind: string }): boolean => r.kind === 'catalog_tool' || r.kind === 'uncatalogued_tool';
export const toolHref = rowHref;
export const shortName = (_m: Mode, r: { short?: string; tool: string }): string =>
  r.short ?? r.tool.replace(', zero-shot', '').split(' (')[0].split(':')[0];
/** Rows a mode's table lists: every reviewer and simple rule, highest J first. Shortcut baselines are not listed;
 *  the table names the top one in a line below it. */
export const listedRows = (m: Mode): Row[] => m.rows.filter((r) => r.kind !== 'shortcut_baseline').sort((a, b) => b.j - a.j);
/** Rows with fewer than 95% readable answers in one class (marked with a dagger where they are shown). */
export const INCOMPLETE_ROWS: number = R.modes.reduce((a, m) => a + m.rows.filter((r) => r.incomplete).length, 0);

export interface ClassicSummary extends Omit<ModeSummary, 'best' | 'free'> {
  /** The highest-J ranked row (one of a tied group unless m.winner is set). */
  best: Row;
  /** Best free catalog program inside its design scope, or null. */
  free: Row | null;
  /** Every listed row, highest J first. */
  listed: Row[];
  /** Tools only (catalog or not), highest J first. */
  tools: Row[];
  /** Highest-J shortcut baseline, or null. */
  shortcut: Row | null;
}
export const CLASSIC: ClassicSummary[] = SUMMARIES.map((s) => ({
  ...s,
  best: rowByKey(s.m, s.best.key) as Row,
  free: s.free ? (rowByKey(s.m, s.free.key) ?? null) : null,
  listed: listedRows(s.m),
  tools: listedRows(s.m).filter(isTool),
  shortcut: topShortcut(s.m),
})).sort((a, b) => b.best.j - a.best.j);
/** Mode ids in the order of the results file (the order of the leaderboard tabs). */
export const FILE_ORDER: string[] = R.modes.map((m) => m.id);
/** Modes where nothing we ran reaches the floor (J 25%). */
export const HARD: ClassicSummary[] = CLASSIC.filter((s) => s.m.below_floor);

const NUMBER_WORD = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'];
const countWord = (n: number): string => NUMBER_WORD[n] ?? String(n);
const jr = (x: number): string => signedPct(x, 0);

function classicFindings(): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  const n = MODES.length;
  // 1. who leads
  const modelLead = MODES.filter((m) => OVR.best[m.id]?.type === 'baseline_model');
  const winners = MODES.filter((m) => m.winner);
  out.push([
    `A zero-shot model has the highest J in ${modelLead.length === n ? `all ${n}` : `${modelLead.length} of ${n}`} modes.`,
    winners.length
      ? ` It is clearly ahead of the runner-up only in ${andList(winners.map((m) => m.name))}; in the other modes the leaders are tied.`
      : ' In no mode is one reviewer clearly ahead of the runner-up: the leaders are tied.',
  ]);
  // 2. the three strongest models that ran everywhere
  const cheapEverywhere = (r: (typeof OVR.rows)[number]) => Object.values(r.cells).every((c) => c.cost1k <= R.cheap_cost1k);
  const top3 = OVR.rows.filter((r) => r.type === 'baseline_model' && r.n_modes === n && cheapEverywhere(r)).sort((a, b) => b.avg - a.avg).slice(0, 3);
  if (top3.length === 3) {
    const close = MODES.filter((m) => {
      const js = top3.map((r) => r.cells[m.id]?.j).filter((j): j is number => j != null);
      return js.length === 3 && Math.max(...js) - Math.min(...js) <= 0.1;
    }).length;
    const maxCost = Math.max(...top3.flatMap((r) => Object.values(r.cells).map((c) => c.cost1k)));
    out.push([
      `The three strongest cheap models are close: within 10 points of each other in ${close} of ${n} modes.`,
      ` Average J: ${top3.map((r) => `${r.tool} ${jr(r.avg)}`).join(', ')}. None costs more than ${money(maxCost)} per 1,000 reviews in any mode.`,
    ]);
  }
  // 3. the sets of real agent output
  const real = CLASSIC.filter((s) => s.m.group === 'natural_agent');
  if (real.length) {
    const over = real.map((s) => s.rows.filter((r) => r.j >= FLOOR).length);
    const ranked = real.map((s) => s.rows.length);
    const none = real.every((s) => s.m.below_floor);
    out.push([
      none
        ? `${countWord(real.length)} mode${real.length === 1 ? '' : 's'} nobody handles yet: ${andList(real.map((s) => `${s.m.name} (best J ${jr(s.best.j)})`))}.`
        : `Real agent output is the hard part: the best reviewer reaches J ${andList(real.map((s) => `${jr(s.best.j)} on ${s.m.name} (${s.best.short})`))}.`,
      none
        ? ` No model, program or judge we ran reaches J ${pct(FLOOR, 0)} there. These are the only sets of real agent output; the others have planted or model-written failures.`
        : ` Reviewers at J ${pct(FLOOR, 0)} or more: ${andList(real.map((s, k) => `${over[k]} of ${ranked[k]} on ${s.m.name}`))}. The other sets have planted or model-written failures.`,
    ]);
  }
  // 4. free programs
  const free = CLASSIC.filter((s) => s.free && s.free.j >= 0.5);
  if (free.length)
    out.push([
      `Free programs pay off where the failure is a checkable fact: ${free.map((s) => `${s.free!.short} on ${s.m.name} (${jr(s.free!.j)})`).join('; ')}.`,
      ' In the other modes no free program we ran inside its design scope reaches J 50%.',
    ]);
  // 5. packaged tools against the same model used zero-shot
  const wc = OVR.wrapper_comparisons ?? [];
  if (wc.length) {
    const count = (v: string) => wc.filter((w) => w.verdict === v).length;
    const worse = count('worse'), better = count('better'), same = wc.length - worse - better;
    const judges = [...new Set(wc.map((w) => w.judge_model).filter(Boolean))];
    out.push([
      better === 0
        ? `Wrapping the model in a review tool did not help: in ${wc.length} comparisons on the same samples no tool beat the same model used zero-shot (${worse} worse, ${same} tied).`
        : `Wrapping the model in a review tool rarely helped: in ${wc.length} comparisons on the same samples a tool beat the same model used zero-shot ${better} times (${worse} worse, ${same} tied).`,
      judges.length === 1 ? ` Every tool ran with ${judges[0]} as its judge model.` : '',
    ]);
  }
  // 6. small and non-reasoning models (the sentence the results file computes)
  const small = FINDINGS.find(([lead]) => /flags more than|under 20%/.test(lead));
  if (small) out.push([`Small and non-reasoning models fall short: ${small[0]}`, '']);
  return out;
}

function classicCaveats(): string[] {
  const out = [
    'J compares tools within a mode. Across modes it only roughly reflects difficulty: each dataset was built differently (real agent runs, model-written code, planted or hand-built failures), so a high J on a planted-failure mode is not as hard-won as a low one on real agent runs.',
    'Averages weight every mode equally and cover only the modes a tool ran (the number is in brackets).',
    `Each model was told which failure to look for. Rates are on the answers that carry a verdict` +
      (INCOMPLETE_ROWS ? `; ${INCOMPLETE_ROWS} entries with fewer than 95% readable answers are marked † in their mode’s tab.` : '.'),
  ];
  const withShortcut = CLASSIC.filter((s) => s.shortcut && s.shortcut.j >= FLOOR);
  if (withShortcut.length) {
    const ex = [...withShortcut].sort((a, b) => b.shortcut!.j - b.best.j - (a.shortcut!.j - a.best.j))[0];
    out.push(
      `A rule that understands nothing about the failure scores J ${pct(FLOOR, 0)} or more on ${withShortcut.length} of ${MODES.length} datasets ` +
        `(on ${ex.m.name}: ${jr(ex.shortcut!.j)}, against ${jr(ex.best.j)} for the best reviewer), so J 0% is not the real zero. Each mode's tab names its rule.`,
    );
  }
  out.push(
    'Same prompt style for every model, temperature 0 (gpt-6-luna: its default), one run each. “Tied” means the 95% interval of the difference from the leader includes 0. Simple rules are shown for reference and are never named best.',
  );
  return out;
}

const bestJ = (id: string): number => OVR.best[id]?.j ?? -1;
/** The Overview tab: reviewer x mode grid, modes from the best caught to the least. */
export const OVERVIEW = {
  modes: [...OVR.modes].sort((a, b) => bestJ(b.id) - bestJ(a.id)).map(({ id, name }) => ({ id, name })),
  // only what the grid and the chart print; the average is the mean of the row's cells
  rows: OVR.rows.filter((r) => r.kind !== 'shortcut_baseline').map((r) => {
    const cells = Object.fromEntries(
      Object.entries(r.cells).map(([id, c]) => [id, { j: c.j, tool: c.tool, short: c.short, fa: c.fa, cost1k: c.cost1k }]),
    );
    const js = Object.values(cells).map((c) => c.j);
    return { tool: r.tool, type: r.type, cells, avg: js.reduce((a, b) => a + b, 0) / js.length, n_modes: js.length };
  }),
  best: Object.fromEntries(
    Object.entries(OVR.best).map(([id, b]) => [id, { j: b.j, tool: b.tool, short: b.short, type: b.type, winner: b.winner, top_group: b.top_group }]),
  ),
  findings: classicFindings(),
  caveats: classicCaveats(),
};
