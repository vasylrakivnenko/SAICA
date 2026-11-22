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
import { andList, pct, signedPct } from '../../lib/format';

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
