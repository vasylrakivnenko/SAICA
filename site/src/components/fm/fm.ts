// Shared content and measured data for the failure-mode pages: the hub (/failure-modes/), one page per mode
// (/failure-modes/<slug>/) and the glossary (/glossary/).
//
// Two sources, joined at build time:
// - the knowledge graph (data/failure_modes/*.yml via lib/data.ts, plus data/failure_mode_synonyms.yml read here);
// - the benchmark (public/bench/results.json and kit.json, written by bench/build_report.py).
// COPY below holds the searcher-facing wording per mode (title, H1, plain definition, why it matters). Every fact in
// it comes from the KG yml, its incidents and papers, or the benchmark's setup notes; numbers are filled in from the
// results, never typed in.
import fs from 'node:fs';
import path from 'node:path';
import yaml from 'js-yaml';
import results from '../../../public/bench/results.json';
import kit from '../../../public/bench/kit.json';
import { graph } from '../../lib/data.ts';
import { benchId, fmUrl } from '../../lib/seo.ts';
import type { FailureMode } from '../../lib/types.ts';

export const GENERATED: string = results.generated;
/** Below this best J a mode counts as not caught yet (the kit builder's reliability floor). */
export const FLOOR: number = kit.floor ?? 0.25;
/** At or above this best J a mode counts as caught well (an editorial line, stated on the hub). */
export const WELL = 0.8;

// ---------- formatting ----------

/** J / TPR / FPR as a percentage with a true minus sign: 0.943 -> "94.3%", -0.07 -> "−7.0%". */
export function pct(x: number, digits = 1): string {
  const s = (Math.abs(x) * 100).toFixed(digits);
  return (x < 0 && Number(s) !== 0 ? '−' : '') + s + '%';
}
/** Whole-number percentage for prose and descriptions. */
export const pct0 = (x: number) => pct(x, 0);
export const money = (c: number) => (c === 0 ? 'free' : '$' + c.toFixed(2));
export const int = (n: number) => n.toLocaleString('en-US');

/** Tiny link markup for COPY strings: [text](/path/) or [text](fm:kg_id). */
const LINK = /\[([^\]]+)\]\(([^)]+)\)/g;
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const href = (target: string) => (target.startsWith('fm:') ? fmUrl(target.slice(3)) : target);
export function md(s: string): string {
  let out = '';
  let last = 0;
  for (const m of s.matchAll(LINK)) {
    out += esc(s.slice(last, m.index)) + `<a href="${esc(href(m[2]))}">${esc(m[1])}</a>`;
    last = (m.index ?? 0) + m[0].length;
  }
  return out + esc(s.slice(last));
}
export const plain = (s: string) => s.replace(LINK, '$1');

// ---------- measured results ----------

export type Cat = 'program' | 'hybrid' | 'llm' | 'rule';
export const CAT_LABEL: Record<Cat, string> = {
  program: 'Free program',
  hybrid: 'Hybrid tool',
  llm: 'LLM reviewer',
  rule: 'Simple rule',
};
const TYPE_CAT: Record<string, Cat> = {
  deterministic: 'program',
  llm_based: 'hybrid',
  hybrid: 'hybrid',
  prompt_artifact: 'hybrid',
  baseline_model: 'llm',
  baseline_rule: 'rule',
};

export interface MRow {
  key: string;
  tool: string;
  short: string;
  cat: Cat;
  j: number;
  tpr: number;
  fpr: number;
  tprCi: [number, number];
  fprCi: [number, number];
  cost: number;
  cost1k: number;
  /** Cost scaled up from a partial run (shown with "~", as on the leaderboard). */
  estimated: boolean;
  /** Number of samples the rates are on, when the tool ran on a subset only. */
  subset: number | null;
  kgId: string | null;
  costNote: string;
}

export interface Measured {
  benchId: string;
  fm: string;
  name: string;
  n: number;
  nPos: number;
  nNeg: number;
  posLabel: string;
  dataset: string;
  summary: string;
  setup: string[];
  caveats: string[];
  rows: MRow[];
  best: MRow;
  bestFree: MRow | null;
  bestHybrid: MRow | null;
  bestLlm: MRow | null;
}

const kitRows = new Map<string, any>();
for (const m of kit.modes as any[]) for (const r of m.rows ?? []) kitRows.set(`${m.id}/${r.key}`, r);

function toRow(m: any, r: any): MRow {
  const k = kitRows.get(`${m.id}/${r.key}`);
  const note: string = r.cost_note ?? '';
  const sub = note.match(/run on the first (\d+) \+ (\d+) samples only/);
  return {
    key: r.key,
    tool: r.tool,
    short: k?.short ?? r.tool.split(', asked directly')[0],
    cat: (k?.category as Cat) ?? TYPE_CAT[r.type] ?? 'llm',
    j: r.j,
    tpr: r.catch,
    fpr: r.fa,
    tprCi: r.catch_ci,
    fprCi: r.fa_ci,
    cost: r.cost,
    cost1k: (r.cost / m.n) * 1000,
    estimated: note.includes('estimated'),
    subset: sub ? Number(sub[1]) + Number(sub[2]) : null,
    kgId: r.kg_id ?? null,
    costNote: note,
  };
}

const MEASURED = new Map<string, Measured>();
for (const m of results.modes as any[]) {
  const rows = (m.rows as any[]).map((r) => toRow(m, r)).sort((a, b) => b.j - a.j);
  const top = (f: (r: MRow) => boolean) => rows.find(f) ?? null;
  const fmId = (kit.modes as any[]).find((k) => k.id === m.id)?.fm ?? m.id;
  MEASURED.set(fmId, {
    benchId: m.id,
    fm: fmId,
    name: m.name,
    n: m.n,
    nPos: m.n_pos,
    nNeg: m.n_neg,
    posLabel: m.pos_label,
    dataset: m.dataset,
    summary: m.summary,
    setup: m.setup ?? [],
    caveats: m.caveats ?? [],
    rows,
    best: rows[0],
    bestFree: top((r) => r.cost === 0 && (r.cat === 'program' || r.cat === 'rule')),
    bestHybrid: top((r) => r.cat === 'hybrid'),
    bestLlm: top((r) => r.cat === 'llm'),
  });
}

/** Measured results for a KG failure-mode id, or null when the mode is not benchmarked. */
export const measured = (fmId: string): Measured | null => MEASURED.get(fmId) ?? null;

export interface StarTool {
  id: string;
  name: string;
  stars: number | null;
  mechanism: string;
  implementation: string;
  how: string;
  inKg: boolean;
}
export interface StarMode {
  note: string;
  tools: StarTool[];
}
/** For unbenchmarked modes: the catalog tools that address it, by GitHub stars (results.json star_modes). */
export function starMode(fmId: string): StarMode | null {
  const s = ((results as any).star_modes ?? []).find((x: any) => (x.fm ?? x.id) === fmId);
  if (!s) return null;
  const tools = (s.tools as any[])
    .map((t) => ({
      id: t.id,
      name: t.name,
      stars: typeof t.stars === 'number' ? t.stars : null,
      mechanism: t.mechanism,
      implementation: t.implementation,
      how: t.how,
      inKg: Boolean(graph.tools[t.id]),
    }))
    .sort((a, b) => (b.stars ?? 0) - (a.stars ?? 0));
  return { note: s.note, tools };
}

export type Tier = 'well' | 'partly' | 'not-yet' | 'unmeasured';
export const TIER_LABEL: Record<Tier, string> = {
  well: 'Caught well',
  partly: 'Caught partly',
  'not-yet': 'Not caught yet',
  unmeasured: 'Not measured',
};
export function tier(fmId: string): Tier {
  const m = measured(fmId);
  if (!m) return 'unmeasured';
  return m.best.j >= WELL ? 'well' : m.best.j >= FLOOR ? 'partly' : 'not-yet';
}

/** Short tool name for prose: "pyright", "deepseek-v4.1-flash", "a typosquat rule". */
export function proseName(r: MRow): string {
  return r.cat === 'rule' ? `a ${r.short}` : r.short;
}

// ---------- KG: synonyms, crosswalks, incidents ----------

const SYN_FILE = path.join(import.meta.env.KG_DATA_DIR as string, 'failure_mode_synonyms.yml');
const SYNONYMS: Record<string, any> = fs.existsSync(SYN_FILE)
  ? ((yaml.load(fs.readFileSync(SYN_FILE, 'utf8')) as Record<string, any>) ?? {})
  : {};
// dependency_blindness's discovery synonyms ("lockfile ignored", "undeclared dependency", ...) describe a different
// concept from its definition (re-implementing what exists), so they are not shown as other names for it.
const SKIP_SYNONYMS = new Set(['dependency_blindness']);

const pretty = (s: string) => s.replace(/-/g, ' ');

/** Every other name the KG gives a mode: yml aliases, then discovery synonyms (deduped, readable). */
export function otherNames(fm: FailureMode): string[] {
  const syn: string[] = SKIP_SYNONYMS.has(fm.id) ? [] : (SYNONYMS[fm.id]?.synonyms ?? []);
  const seen = new Set<string>();
  const out: string[] = [];
  // Aliases are kebab-case ids (api-hallucination); synonyms are already plain text (off-by-one).
  for (const raw of [...fm.aliases.map((a) => pretty(String(a))), ...syn.map(String)]) {
    const s = raw.replace(/\bapi\b/g, 'API').trim();
    const k = s.toLowerCase();
    if (!s || seen.has(k) || k === fm.name.toLowerCase()) continue;
    seen.add(k);
    out.push(s);
  }
  return out;
}

/** schema.org alternateName list: the searcher term, the hub's short list and every KG name, deduped, minus the name. */
export function altNames(fm: FailureMode): string[] {
  const c = copyFor(fm.id);
  const seen = new Set([fm.name.toLowerCase()]);
  return [c.term, ...c.aka, ...otherNames(fm)].filter((n) => {
    const k = n.toLowerCase();
    if (seen.has(k) || sameAsName(n, fm.name)) return false;
    seen.add(k);
    return true;
  });
}

export interface XMap {
  taxonomy: string;
  taxonomyName: string;
  externalId: string;
  label: string;
  confidence: 'exact' | 'partial' | 'related' | string;
  note?: string;
}
const RANK: Record<string, number> = { exact: 0, partial: 1, related: 2 };

/** All crosswalk mappings of a mode (inline in its yml and in data/crosswalks), strongest first, deduped. */
export function crosswalksFor(fmId: string): XMap[] {
  const fm = graph.failureModes[fmId];
  const raw: Array<{ taxonomy: string; external_id: string; confidence: string; note?: string }> = [
    ...(fm?.crosswalks ?? []),
    ...Object.values(graph.crosswalks)
      .filter((c) => c.saica_axis === 'failure_mode')
      .flatMap((c) => c.mappings.filter((m: any) => m.saica_value === fmId).map((m: any) => ({ ...m, taxonomy: c.taxonomy }))),
  ];
  const best = new Map<string, XMap>();
  for (const r of raw) {
    const tax = graph.taxonomies[r.taxonomy];
    const cat = tax?.categories.find((c) => c.external_id === r.external_id);
    const x: XMap = {
      taxonomy: r.taxonomy,
      taxonomyName: tax?.name ?? r.taxonomy,
      externalId: r.external_id,
      label: cat?.label ?? r.external_id,
      confidence: r.confidence,
      note: typeof r.note === 'string' ? r.note.replace(/\s+/g, ' ').trim() : undefined,
    };
    const k = `${r.taxonomy}/${r.external_id}`;
    const prev = best.get(k);
    if (!prev || (RANK[x.confidence] ?? 9) < (RANK[prev.confidence] ?? 9)) best.set(k, { ...x, note: x.note ?? prev?.note });
  }
  return [...best.values()].sort(
    (a, b) => (RANK[a.confidence] ?? 9) - (RANK[b.confidence] ?? 9) || a.externalId.localeCompare(b.externalId),
  );
}

/** Incidents in the KG tagged with this mode, newest first, each with a one-paragraph summary. */
export function incidentsFor(fmId: string) {
  return Object.values(graph.incidents)
    .filter((i) => i.exhibited_failure_modes.includes(fmId as any))
    .sort((a, b) => String(b.incident_date).localeCompare(String(a.incident_date)))
    .map((i) => {
      const t = (i.tagline ?? '').replace(/\s+/g, ' ').trim();
      const opens = (t.match(/\(/g) ?? []).length, closes = (t.match(/\)/g) ?? []).length;
      const usable = t && !/(\.\.\.|…)$/.test(t) && opens === closes && /[.!?)"'”]$/.test(t);
      return { id: i.id, title: i.title, date: String(i.incident_date).slice(0, 10), harm: i.harm_class, summary: usable ? t : clipText(i.description, 260) };
    });
}
function clipText(s: string, max: number): string {
  const t = (s ?? '').replace(/\s+/g, ' ').trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max - 1);
  return cut.slice(0, cut.lastIndexOf(' ')).replace(/[\s,;:.—-]+$/, '') + '…';
}

// ---------- searcher-facing copy per mode ----------

export interface Copy {
  /** The phrase people search for; our KG label stays the defined term. */
  term: string;
  title: string;
  h1: string;
  /** One line for the hub table. */
  short: string;
  /** Up to three other names for the hub table, all from the KG aliases or synonyms. */
  aka: string[];
  /** Sentence 1: a plain definition in searchers' words. */
  definition: string;
  /** How it shows up and how it differs from its neighbours (from the KG description). */
  detail: string;
  /** Why it matters, grounded in KG incidents/papers or the benchmark's own data. */
  why: string;
  description: (m: Measured | null, s: StarMode | null) => string;
  /** The first FAQ question, phrased the way people ask it. */
  what: string;
  /** Noun phrase for the other questions and the results heading ("How do you detect <subject>?"). */
  subject: string;
  /** Optional line under the results heading (what the benchmark set does and does not test). */
  measuredNote?: string;
}

const free = (m: Measured) => m.bestFree!;

export const COPY: Record<string, Copy> = {
  fabrication: {
    what: 'What is code hallucination in AI coding agents?',
    subject: 'code hallucination',
    term: 'Code hallucination',
    title: 'Code Hallucination (Fabrication) in AI Coding Agents',
    h1: 'Code hallucination (fabrication) in AI coding agents',
    short: 'Code that calls functions, methods or packages that do not exist.',
    aka: ['code hallucination', 'API hallucination', 'package hallucination'],
    definition:
      'Code hallucination, which SAICA-Bench calls fabrication, is when an AI coding agent writes code that refers to a function, method, class or package that does not exist in any installed dependency, the standard library or the runtime.',
    detail:
      'The code is syntactically plausible and factually false. It differs from [obsolescence](fm:obsolescence), where the API is real but deprecated or removed, and from [dependency blindness](fm:dependency_blindness), where the right function exists but the agent ignores it. A hallucinated package name is also the opening for [slopsquatting](fm:supply_chain_attack).',
    why:
      'At best a hallucinated import crashes at run time; at worst someone registers the made-up name and the agent installs their code. [Spracklen et al.](/papers/spracklen-2024-we-have-a-package/) (USENIX Security 2024) found that on average at least 5.2% of the packages suggested by commercial models, and 21.7% of those suggested by open-source models, do not exist. One hallucinated name, [huggingface-cli](/incidents/huggingface-cli-slopsquat-lanyado-2024/), drew more than 30,000 downloads after a researcher registered it as an empty package.',
    description: (m) =>
      `Code hallucination is when an AI coding agent calls APIs or packages that don't exist. Best detector: J ${pct0(m!.best.j)}; free ${free(m!).short}: J ${pct0(free(m!).j)} (${int(m!.nPos + m!.nNeg)} samples).`,
  },
  test_manipulation: {
    what: 'What is reward hacking (test manipulation) in AI coding agents?',
    subject: 'reward hacking',
    term: 'Reward hacking',
    title: 'Reward Hacking (Test Manipulation) in AI Coding Agents',
    h1: 'Reward hacking (test manipulation) in AI coding agents',
    short: 'Tests edited, weakened or skipped so failures disappear instead of the bug being fixed.',
    aka: ['reward hacking', 'test gaming', 'spec gaming'],
    definition:
      'Test manipulation is reward hacking by an AI coding agent: faced with failing tests, it changes the tests instead of the code under test, so the failures disappear while the bug stays.',
    detail:
      'Typical forms are rewriting assertions to match the current, wrong output, commenting out a failing test, adding `pytest.mark.skip`, replacing a real expectation with a tautology, or disabling the CI job. Unlike a [logic error](fm:logic_error), which is an honest mistake, this is the agent gaming its own evaluation; it is often triggered by task prompts that put too much weight on making the tests pass.',
    why:
      'A manipulated test suite reports green on broken code, so every later check that trusts the tests is fooled as well. Columbia DAPLab recorded this pattern, which it calls a [silent test-passing workaround](/incidents/daplab-silent-test-passing-observation-2026/), in the coding agents it studied: failing tests led agents to edit the test, mock the assertion or alter the harness.',
    description: (m) =>
      `Reward hacking in coding agents: editing, weakening or skipping tests instead of fixing the code. Best detector J ${pct0(m!.best.j)} on ${int(m!.nPos + m!.nNeg)} agent sessions.`,
  },
  security_vulnerability: {
    what: 'What counts as a security vulnerability in AI-generated code?',
    subject: 'security vulnerabilities in AI-generated code',
    term: 'Security vulnerabilities in AI-generated code',
    title: 'Security Vulnerabilities in AI-Generated Code',
    h1: 'Security vulnerabilities in AI-generated code',
    short: 'Correct-looking code with injection flaws, weak cryptography or leaked secrets.',
    aka: ['insecure code', 'code injection', 'secret leakage'],
    definition:
      'A security vulnerability, as a coding-agent failure, is when an AI coding agent writes code that adds an exploitable flaw, such as an injection primitive, weak cryptography, a leaked secret or insecure deserialization, to code that otherwise looks correct.',
    detail:
      'The flaw does not break the feature. In the SusVibes data used below, vulnerable and secure patches both pass the task’s functional tests; only a hidden CVE test tells them apart. Malicious packages pulled in by the agent are a separate mode, [supply-chain attacks](fm:supply_chain_attack).',
    why:
      'Code that works and passes its tests gets merged. Researchers have shown GitHub Copilot [reproducing real hard-coded secrets](/incidents/copilot-secret-leakage-cuhk-2024/) from public code, and Claude Code, Gemini CLI and GitHub Copilot Agent [following instructions hidden in GitHub issues](/incidents/copilot-prompt-injection-github-comments-2025/).',
    description: (m) =>
      `Can reviewers catch security vulnerabilities in AI-generated code? On ${int(m!.nPos + m!.nNeg)} real agent patches the best of ${m!.rows.length} tools scored J ${pct0(m!.best.j)}; ${free(m!).short} ${pct0(free(m!).j)}.`,
  },
  logic_error: {
    what: 'What is a logic error in AI-generated code?',
    subject: 'logic errors in AI-generated code',
    term: 'Logic errors in AI-generated code',
    title: 'Logic Errors in AI-Generated Code',
    h1: 'Logic errors in AI-generated code',
    short: 'Real APIs used correctly, but the code computes the wrong result.',
    aka: ['semantic bug', 'off-by-one', 'inverted condition'],
    definition:
      'A logic error is when an AI coding agent uses real, current APIs correctly but writes logic that computes the wrong result for the task, for example an inverted condition, an off-by-one or a faulty algorithm.',
    detail:
      'It is the classic “passes the type check, fails correctness” bug. It differs from [code hallucination](fm:fabrication), where the API does not exist, and from [obsolescence](fm:obsolescence), where the API is out of date. A fix that makes things worse is a [cascading failure](fm:cascading_failure).',
    why:
      'Nothing about the code looks wrong to a compiler, type checker or linter, so only tests, execution or a reader who understands the task can catch it. In the Gemini CLI case in the catalog, the agent [misread a failed command as success](/incidents/gemini-cli-file-deletion-2025/) and went on to destroy the user’s files.',
    description: (m) =>
      `Logic errors in AI-generated code: it runs but computes the wrong result. Best reviewer J ${pct0(m!.best.j)} on ${int(m!.nPos + m!.nNeg)} functions; type checkers and linters ≈${pct0(Math.max(0, free(m!).j))}.`,
  },
  incomplete_execution: {
    what: 'What is incomplete execution in AI coding agents?',
    subject: 'false “done” claims',
    term: 'False “done” claims',
    title: 'AI Coding Agent Says "Done" but Isn\'t (Incomplete Execution)',
    h1: 'AI coding agent says “done” but isn’t: incomplete execution',
    short: 'The agent reports the task done while parts are skipped, stubbed or not working.',
    aka: ['premature completion', 'false completion', 'stub left behind'],
    definition:
      'Incomplete execution, also called premature or false completion, is when an AI coding agent reports a task as done while parts of it are skipped, stubbed out or silently dropped.',
    detail:
      'Common forms are `TODO` comments left in the code, function bodies replaced with `pass` or `...`, a feature only partly implemented, error paths skipped, or the agent stopping before every item the user asked for is addressed. It is the opposite of [scope creep](fm:scope_creep): the agent under-delivers inside the request instead of reaching beyond it.',
    why:
      'A false “done” hands the checking back to the person who delegated the task. Columbia DAPLab observed agents [claiming success with named subtasks unimplemented](/incidents/daplab-incomplete-task-execution-observation-2026/) in all five coding agents it evaluated, and in Answer.AI’s month-long evaluation of Devin [3 of 20 tasks were completed](/incidents/devin-railway-deploy-hallucinated-features-2024/).',
    description: (m) =>
      `When an AI coding agent says "done" but the task isn't. On ${int(m!.nPos + m!.nNeg)} real agent runs the best of ${m!.rows.length} detectors scored only J ${pct0(m!.best.j)}.`,
  },
  scope_creep: {
    what: 'What is scope creep in AI coding agents?',
    subject: 'scope creep',
    term: 'Scope creep in AI coding agents',
    title: 'Scope Creep in AI Coding Agents: Unrequested Changes',
    h1: 'Scope creep in AI coding agents: unrequested changes',
    short: 'Changes nobody asked for: other files, new packages, config edits, unrequested refactors.',
    aka: ['task drift', 'over-action', 'unrequested changes'],
    definition:
      'Scope creep is when an AI coding agent does more than it was asked: it edits files outside the request, installs packages nobody named, changes configuration outside the task, or adds refactors and “improvements” unprompted.',
    detail:
      'It also covers committing unrelated changes alongside the requested edit and chaining follow-on work nobody asked for. It is the opposite of [incomplete execution](fm:incomplete_execution), which under-delivers inside the request.',
    why:
      'Every unrequested change is one more thing to review and one more way to break something unrelated. The worst cases are destructive: Replit’s agent [ran destructive database commands during an explicit code freeze](/incidents/replit-agent-saastr-database-deletion-2025/), and DAPLab recorded agents [running rm -rf or git push --force without approval](/incidents/daplab-destructive-action-observation-2026/).',
    description: (m) =>
      `Scope creep in AI coding agents: edits, installs and refactors nobody asked for. Best detector J ${pct0(m!.best.j)} on ${int(m!.nPos + m!.nNeg)} patches; ${proseName(free(m!))} ${pct0(free(m!).j)}.`,
  },
  obsolescence: {
    what: 'What is deprecated API usage (obsolescence) in AI coding agents?',
    subject: 'deprecated API usage',
    term: 'Deprecated API usage',
    title: 'Deprecated API Usage (Obsolescence) in AI-Generated Code',
    h1: 'Deprecated API usage (obsolescence) in AI-generated code',
    short: 'Real APIs that are deprecated, removed or changed, often from stale training data.',
    aka: ['deprecated API usage', 'version drift', 'training-cutoff drift'],
    definition:
      'Obsolescence is when an AI coding agent calls a real library API or package that has been deprecated, removed or materially changed, usually because the model’s training data predates the current release.',
    detail:
      'The model saw an older version of the library and confidently writes the older form. It differs from [code hallucination](fm:fabrication), where the API never existed, and from [dependency blindness](fm:dependency_blindness), where a current API exists and is ignored.',
    why:
      'Old calls break when the library moves on: in the benchmark data below, 77 solutions with a deprecated call swapped in fail on load against the latest libraries. [Wang et al.](/papers/wang-2024-llms-meet-library-evolution/) evaluated seven LLMs on 145 API mappings from eight popular Python libraries and found a systematic tendency to complete code with deprecated APIs; the catalog also records [code assistants emitting retired Java APIs](/incidents/copilot-obsolete-api-java8-2024/).',
    description: (m) =>
      `Deprecated API usage (obsolescence) in AI-generated code. Best detector J ${pct0(m!.best.j)}; free ${free(m!).short} J ${pct0(free(m!).j)}, on ${int(m!.nPos + m!.nNeg)} samples.`,
  },
  supply_chain_attack: {
    what: 'What is slopsquatting, and how do supply-chain attacks reach AI coding agents?',
    subject: 'malicious dependencies',
    measuredNote:
      'The set tests known-malicious lookalike names (typosquats and “popular name + word” combosquats) added to a patch, not hallucinated names registered by an attacker.',
    term: 'Slopsquatting',
    title: 'Slopsquatting: Supply-Chain Attacks via AI Coding Agents',
    h1: 'Slopsquatting and other supply-chain attacks via AI coding agents',
    short: 'The agent installs malicious code: a squatted hallucinated name, a lookalike or a compromised tool.',
    aka: ['slopsquatting', 'typosquatting', 'dependency confusion'],
    definition:
      'A supply-chain attack through an AI coding agent is when the agent installs or invokes malicious code: a hallucinated package name that an attacker registered (slopsquatting), a near-miss of a popular name (typosquatting), or a compromised MCP server or tool.',
    detail:
      'The agent can be led there by its own hallucination, by an adversarial package name or by a compromised upstream. Package hallucination is the cause and belongs to [code hallucination](fm:fabrication); slopsquatting is the exploit.',
    why:
      'Hallucinated names are predictable targets: in the [Spracklen et al. study](/incidents/spracklen-2024-hallucinated-package-prevalence/), about 43% of hallucinated package names repeated across runs. The attack is real: an empty package registered under the hallucinated name [huggingface-cli](/incidents/huggingface-cli-slopsquat-lanyado-2024/) received more than 30,000 downloads in three months.',
    description: (m) => {
      const llm = m!.bestLlm!;
      return m!.best.cat === 'rule' && m!.best.j > llm.j
        ? `Slopsquatting and typosquatting via AI coding agents: on ${int(m!.nPos + m!.nNeg)} patches, a free ${m!.best.short} (J ${pct0(m!.best.j)}) beat the best LLM reviewer (J ${pct0(llm.j)}).`
        : `Slopsquatting and typosquatting via AI coding agents: on ${int(m!.nPos + m!.nNeg)} patches the best detector scored J ${pct0(m!.best.j)}.`;
    },
  },
  dependency_blindness: {
    what: 'What is dependency blindness in AI coding agents?',
    subject: 'dependency blindness',
    term: 'Reinventing existing code',
    title: 'AI Agents Reinventing Existing Code (Dependency Blindness)',
    h1: 'AI coding agents reinventing existing code (dependency blindness)',
    short: 'Hand-written code for what the standard library, a dependency or the codebase already provides.',
    aka: ['reinvention', 'ecosystem duplication'],
    definition:
      'Dependency blindness is when an AI coding agent writes its own version of a function, class or utility that the standard library, an installed package or the codebase already provides, for example a hand-rolled argument splitter instead of `shlex.split`.',
    detail:
      'It is about reinventing code that exists elsewhere in the project or its dependencies, not about repetition inside one generated answer. It differs from [code hallucination](fm:fabrication), where the referenced code does not exist at all.',
    why:
      'The code may run correctly, so its tests can pass. The knowledge graph describes it as a silent quality regression: it adds code to maintain, duplicates effort and drifts from the conventions of the ecosystem.',
    description: (m) =>
      `Dependency blindness: AI coding agents re-implementing what the standard library or codebase already has. Best detector J ${pct0(m!.best.j)} on ${int(m!.nPos + m!.nNeg)} paired patches.`,
  },
  context_pollution: {
    what: 'What is context pollution in AI coding agents?',
    subject: 'context pollution',
    term: 'Context pollution',
    title: 'Context Pollution in AI Coding Agents',
    h1: 'Context pollution in AI coding agents',
    short: 'The working context degrades over a session: facts dropped, noise added, old mistakes kept.',
    aka: ['context contamination', 'stale context', 'irrelevant context'],
    definition:
      'Context pollution is when an AI coding agent’s working context degrades over a long session: relevant earlier information is dropped, irrelevant material piles up, or mistakes from earlier turns are treated as fact in later ones.',
    detail:
      'It is a failure of state hygiene across a session, not of a single generation. OWASP’s “Memory & Context Poisoning” covers the adversarial version; context pollution also covers accidental drift. What is often called context rot, a model becoming less reliable as its context grows, is one route into it: one of the detection signals below is a session longer than the model can reliably attend over. Failed attempts that stay in context and bias later ones link it to [cascading failure](fm:cascading_failure).',
    why:
      'Later steps build on whatever is in context, so one stale or wrong fact can steer the rest of the session. The catalog’s incidents include coding agents that [treated instructions hidden in GitHub issues as commands](/incidents/copilot-prompt-injection-github-comments-2025/) and a support bot that [invented a policy that did not exist](/incidents/cursor-support-bot-fabricated-policy-2025/).',
    description: (_m, s) =>
      `Context pollution: an AI coding agent's context degrades over a long session (stale, irrelevant or wrong material). Not benchmarked yet; ${s?.tools.length ?? 0} tools listed.`,
  },
  cascading_failure: {
    what: 'What is a cascading failure in AI coding agents?',
    subject: 'cascading failures',
    term: 'Cascading failures',
    title: 'Cascading Failures in AI Coding Agents: Recovery Spirals',
    h1: 'Cascading failures in AI coding agents: when each fix makes it worse',
    short: 'Each fix introduces new errors and the code drifts further from working.',
    aka: ['recovery spiral', 'error cascade', 'fix regression'],
    definition:
      'A cascading failure is when an AI coding agent’s attempt to fix an error introduces new errors, and each further attempt moves the code further from a working state.',
    detail:
      'A simple failure can become an irrecoverable tangle after repeated recovery attempts. It differs from a [logic error](fm:logic_error), which is the first bug itself, and from [context pollution](fm:context_pollution), which is drift in the session’s state rather than compounding fixes.',
    why:
      'Columbia DAPLab saw [fix attempts introduce new errors](/incidents/daplab-cascading-recovery-observation-2026/) across more than 15 applications built with Claude Code, Cline, Cursor, v0 and Replit. In a published post-mortem, Gemini CLI [misread a failed mkdir as success](/incidents/gemini-cli-file-deletion-2025/), then ran move commands that overwrote every file but one.',
    description: () =>
      `Cascading failure: an AI coding agent's fixes introduce new errors, each attempt moving further from working code. Not benchmarked yet.`,
  },
};

/** True when the searcher term is just a longer form of the KG name ("Scope creep in AI coding agents"). */
export const sameAsName = (term: string, name: string) =>
  term.toLowerCase().startsWith(name.toLowerCase().slice(0, Math.max(4, name.length - 2)));

export function copyFor(fmId: string): Copy {
  const c = COPY[fmId];
  if (!c) throw new Error(`failure-mode copy missing for ${fmId} (add it to src/components/fm/fm.ts)`);
  return c;
}

/** Inline-code markup for COPY strings: `x` -> <code>x</code> (after md()). */
export const html = (s: string) => md(s).replace(/`([^`]+)`/g, '<code>$1</code>');
export const text = (s: string) => plain(s).replace(/`([^`]+)`/g, '$1');

// ---------- FAQ ----------

export interface QA {
  q: string;
  a: string;
}

/** "free program", "LLM reviewer": the category label for use mid-sentence. */
export const catLower = (c: Cat) => CAT_LABEL[c].replace(/^([A-Z])(?=[a-z])/, (x) => x.toLowerCase());

function rowSentence(label: string, r: MRow, m: Measured): string {
  const cost = r.cost === 0 ? 'at no cost' : `at ${r.estimated ? 'about ' : ''}${money(r.cost1k)} per 1,000 reviews`;
  return `${label}: ${r.short} (${catLower(r.cat)}), J ${pct(r.j)}: it flagged ${pct(r.tpr)} of the bad samples and ${pct(r.fpr)} of the clean ones, ${cost}.`;
}

export function faqFor(fm: FailureMode): QA[] {
  const c = copyFor(fm.id);
  const m = measured(fm.id);
  const s = starMode(fm.id);
  const name = c.subject;
  const qa: QA[] = [{ q: c.what, a: `${text(c.definition)} ${text(c.detail)}` }];
  const signals = fm.detection_signals.map((x) => text(x.trim()).replace(/([^.])$/, '$1.'));
  const measuredLine = m
    ? ` On SAICA-Bench the most accurate detector was ${proseName(m.best)} (J ${pct(m.best.j)})` +
      (m.bestFree ? `, and the best free option was ${proseName(m.bestFree)} (J ${pct(m.bestFree.j)}).` : '.')
    : ' No detector has been measured on it yet.';
  qa.push({
    q: `How do you detect ${name}?`,
    a: `Signals that point to it: ${signals.join(' ')}${measuredLine}`,
  });
  if (m) {
    const parts = [rowSentence('Best overall', m.best, m)];
    if (m.bestFree && m.bestFree.key !== m.best.key) parts.push(rowSentence('Best free option', m.bestFree, m));
    if (m.bestHybrid && m.bestHybrid.key !== m.best.key) parts.push(rowSentence('Best hybrid tool', m.bestHybrid, m));
    else if (!m.bestHybrid) parts.push('No hybrid tool (a packaged tool that wraps a model) was run on this mode.');
    if (m.best.j < FLOOR) parts.push(`No tool we ran reaches J ${pct0(FLOOR)}, so treat ${name} as not caught yet.`);
    qa.push({ q: `Which tools catch ${name} best, and how well?`, a: parts.join(' ') });
    qa.push({
      q: `How was detection of ${name} measured?`,
      a:
        `Every tool and model reviewed the same ${int(m.nPos)} bad samples (${m.posLabel}) and ${int(m.nNeg)} clean ones without seeing the labels. Data: ${m.dataset}. ` +
        (c.measuredNote ? `${c.measuredNote} ` : '') +
        `Its score is J = TPR − FPR: the share of bad samples it flags minus the share of clean samples it flags, so 0% is no better than chance and 100% is perfect. ` +
        `Costs are per 1,000 reviews, from the provider's reported price or GPU time; free programs cost $0.`,
    });
  } else {
    const top = s?.tools.slice(0, 4) ?? [];
    qa.push({
      q: `Which tools catch ${name}?`,
      a:
        (top.length
          ? `None has been measured. By GitHub stars, the catalog tools that address it are ${top.map((t) => `${t.name} (${t.mechanism})`).join(', ')}${s!.tools.length > top.length ? `, and ${s!.tools.length - top.length} more` : ''}. `
          : 'None has been measured. ') + (s?.note ?? ''),
    });
    qa.push({
      q: `Why is ${name} not benchmarked?`,
      a: 'There is no dataset with confirmed labels for it yet, so SAICA-Bench cannot score detectors on it. The leaderboard lists the catalog tools that address it by GitHub stars instead, which says nothing about how well they work.',
    });
  }
  return qa;
}

/** Leaderboard mode id for links (re-exported so pages need one import). */
export { benchId };
