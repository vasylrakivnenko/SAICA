// Shared content for the failure-mode pages: the hub (/failure-modes/), one page per mode (/failure-modes/<slug>/)
// and the glossary (/glossary/).
//
// Two sources, joined at build time:
// - the knowledge graph (data/failure_modes/*.yml via lib/data.ts, plus data/failure_mode_synonyms.yml read here);
// - the benchmark (public/bench/results.json, only through components/home/bench.ts).
// COPY below holds the searcher-facing wording per mode (title, H1, plain definition, why it matters). Every fact in
// it comes from the KG yml, its incidents and papers. It states no benchmark result: numbers, names of reviewers and
// what was measured are printed from the results file by descriptionFor() and faqFor() below.
import fs from 'node:fs';
import path from 'node:path';
import yaml from 'js-yaml';
import { confidenceRank, crosswalksOf, graph } from '../../lib/data.ts';
import { benchId, fmUrl, kgId } from '../../lib/seo.ts';
import { incidentKind, isEvent } from '../../lib/catalog.ts';
import { andList, escapeHtml, int, money as usd, pct, signedPct } from '../../lib/format.ts';
import {
  GENERATED, METHOD, STAR_MODES,
  bestClause, groupOf, modeByFm, samplesOf, topShortcut,
  type Mode,
} from '../home/bench.ts';
import { FLOOR, CLASSIC, type ClassicSummary, type Row } from '../home/bench.ts';
import type { CrosswalkConfidence, FailureMode } from '../../lib/types.ts';

/** Date of the results file (re-exported so pages need one import). */
export { GENERATED };

/** Tiny link markup for COPY strings: [text](/path/) or [text](fm:kg_id). */
const LINK = /\[([^\]]+)\]\(([^)]+)\)/g;
const esc = escapeHtml;
const href = (target: string) => (target.startsWith('fm:') ? fmUrl(target.slice(3)) : target);
/** Link targets this markup accepts: a path on this site, a fragment, an https URL or fm:<kg id>. md() is also
 *  applied to text from the KG yml files, so any other target (javascript:, data:, //host) stays plain text. */
const SAFE_TARGET = /^(?:\/(?!\/)|#|https:\/\/|fm:)/;
export function md(s: string): string {
  let out = '';
  let last = 0;
  for (const m of s.matchAll(LINK)) {
    const link = SAFE_TARGET.test(m[2]) ? `<a href="${esc(href(m[2]))}">${esc(m[1])}</a>` : esc(m[1]);
    out += esc(s.slice(last, m.index)) + link;
    last = (m.index ?? 0) + m[0].length;
  }
  return out + esc(s.slice(last));
}
export const plain = (s: string) => s.replace(LINK, '$1');

// ---------- measured results ----------

/** Measured results for a KG failure-mode id (the mode object of results.json), or null when it is not benchmarked. */
export const measured = (fmId: string): Mode | null => modeByFm(fmId) ?? null;

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
  const s = STAR_MODES.find((x) => (x.fm ?? x.id) === fmId);
  if (!s) return null;
  const tools = s.tools
    .map((t) => ({
      id: t.id,
      name: t.name,
      stars: typeof t.stars === 'number' ? t.stars : null,
      mechanism: t.mechanism ?? '',
      implementation: t.implementation ?? '',
      how: t.how ?? '',
      inKg: Boolean(graph.tools[t.id]),
    }))
    .sort((a, b) => (b.stars ?? 0) - (a.stars ?? 0));
  return { note: s.note ?? '', tools };
}

// ---------- KG: synonyms, crosswalks, incidents ----------

const SYN_FILE = path.join(import.meta.env.KG_DATA_DIR as string, 'failure_mode_synonyms.yml');
const SYNONYMS: Record<string, any> = fs.existsSync(SYN_FILE)
  ? ((yaml.load(fs.readFileSync(SYN_FILE, 'utf8')) as Record<string, any>) ?? {})
  : {};
// (dependency_blindness's synonyms were rewritten on 2026-11-21 to match its definition, so no mode is skipped now.)
const SKIP_SYNONYMS = new Set<string>();

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
  confidence: CrosswalkConfidence;
  note?: string;
}
/** All crosswalk mappings of a mode (from data/crosswalks via lib/data.ts `crosswalkEdges`), strongest first. */
export function crosswalksFor(fmId: string): XMap[] {
  return crosswalksOf(fmId)
    .map((e) => ({
      taxonomy: e.taxonomy,
      taxonomyName: e.taxonomy_name,
      externalId: e.external_id,
      label: e.external_label,
      confidence: e.confidence,
      note: e.note,
    }))
    .sort(
      (a, b) => confidenceRank(a.confidence) - confidenceRank(b.confidence) || a.externalId.localeCompare(b.externalId),
    );
}

/** Incident records in the KG tagged with this mode, newest first, each with a one-paragraph summary.
 *  `event` says whether the record is an incident in the plain sense (Incident.kind === 'event'); a study
 *  finding, a reported pattern or a hypothetical scenario is listed apart on the page, under `kindLabel`, and
 *  so is a record with no kind yet (`classified` false). */
export function incidentsFor(fmId: string) {
  return Object.values(graph.incidents)
    .filter((i) => i.exhibited_failure_modes.includes(fmId as any))
    .sort((a, b) => String(b.incident_date).localeCompare(String(a.incident_date)))
    .map((i) => {
      const t = (i.tagline ?? '').replace(/\s+/g, ' ').trim();
      const opens = (t.match(/\(/g) ?? []).length, closes = (t.match(/\)/g) ?? []).length;
      const usable = t && !/(\.\.\.|…)$/.test(t) && opens === closes && /[.!?)"'”]$/.test(t);
      return {
        id: i.id,
        title: i.title,
        date: String(i.incident_date).slice(0, 10),
        harm: i.harm_class,
        summary: usable ? t : clipText(i.description, 260),
        event: isEvent(i),
        classified: Boolean(i.kind),
        kindLabel: incidentKind(i).label,
      };
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
  /** Why it matters, grounded in KG incidents and papers. */
  why: string;
  /** First sentence of the meta description: what the failure is. No benchmark result (see descriptionFor). */
  lead: string;
  /** The first FAQ question, phrased the way people ask it. */
  what: string;
  /** Noun phrase for the other questions and the results heading ("How do you detect <subject>?"). */
  subject: string;
}

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
      'At best a hallucinated import crashes at run time; at worst someone registers the made-up name and the agent installs their code. [Spracklen et al.](/papers/spracklen-2024-we-have-a-package/) (USENIX Security 2025) found that on average 5.2% of the packages recommended by commercial models, and 21.7% of those recommended by open-source models, do not exist. One hallucinated name, [huggingface-cli](/incidents/huggingface-cli-slopsquat-lanyado-2024/), drew between 15,000 and 30,000 downloads (the two sources differ) after a researcher registered it as an empty package.',
    lead:
      "Code hallucination is when an AI coding agent calls APIs or packages that don't exist.",
  },
  test_manipulation: {
    what: 'What is test manipulation in AI coding agents?',
    subject: 'test manipulation',
    term: 'Test manipulation',
    title: 'Test Manipulation in AI Coding Agents: Test Edits That Hide Failures',
    h1: 'Test manipulation in AI coding agents: test edits that hide failures',
    short: 'Tests edited, weakened or skipped so failures disappear instead of the bug being fixed.',
    aka: ['test gaming', 'spec gaming', 'reward hacking'],
    definition:
      'Test manipulation is when an AI coding agent, faced with failing tests, changes the tests instead of the code under test, so the failures disappear while the bug stays. It is one form of reward hacking.',
    detail:
      'Typical forms are rewriting assertions to match the current, wrong output, commenting out a failing test, adding `pytest.mark.skip`, replacing a real expectation with a tautology, or disabling the CI job. Unlike a [logic error](fm:logic_error), which is an honest mistake, this is the agent gaming its own evaluation; it is often triggered by task prompts that put too much weight on making the tests pass.',
    why:
      'A manipulated test suite reports green on broken code, so every later check that trusts the tests is fooled as well.',
    lead:
      'Test manipulation: an AI coding agent edits, weakens or skips tests so failures disappear instead of fixing the code.',
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
      'Code that works and passes its tests gets merged. A study found GitHub Copilot [emitting hard-coded credentials seen in training](/incidents/copilot-secret-leakage-cuhk-2024/): 2,702 well-formed ones from 900 prompts, two of them confirmed to be working keys. And three AI agents that run on GitHub (Claude Code Security Review, Gemini CLI Action and GitHub Copilot Agent) were [made to run commands hidden in pull-request titles, issues and comments](/incidents/copilot-prompt-injection-github-comments-2025/).',
    lead:
      'Security vulnerabilities in AI-generated code: flaws added to code that otherwise looks correct.',
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
    lead:
      'Logic errors in AI-generated code: it runs but computes the wrong result.',
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
      'A false “done” hands the checking back to the person who delegated the task. In Answer.AI’s month-long evaluation of Devin, [3 of 20 tasks were completed](/incidents/devin-railway-deploy-hallucinated-features-2024/).',
    lead:
      'When an AI coding agent says "done" but the task is not.',
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
      'Every unrequested change is one more thing to review and one more way to break something unrelated. The worst cases are destructive: Replit’s agent [ran destructive database commands during an explicit code freeze](/incidents/replit-agent-saastr-database-deletion-2025/).',
    lead:
      'Scope creep in AI coding agents: edits, installs and refactors nobody asked for.',
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
      'Old calls break when the library moves on. [Wang et al.](/papers/wang-2024-llms-meet-library-evolution/) gave seven code LLMs completion prompts built on 145 deprecated APIs from eight Python libraries: of the completions that used either the old API or its replacement, 25% to 38% used the deprecated one.',
    lead:
      'Deprecated API usage (obsolescence) in AI-generated code.',
  },
  supply_chain_attack: {
    what: 'What is slopsquatting, and how do supply-chain attacks reach AI coding agents?',
    subject: 'malicious dependencies',
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
      'Hallucinated names are predictable targets: in the [Spracklen et al. study](/incidents/spracklen-2024-hallucinated-package-prevalence/), when a prompt that had produced a hallucinated package was run ten more times, 43% of the hallucinated names came back in all ten runs. The opening has been demonstrated: an empty package that a researcher registered under the hallucinated name [huggingface-cli](/incidents/huggingface-cli-slopsquat-lanyado-2024/) was downloaded between 15,000 and 30,000 times in about three months (the two sources differ).',
    lead:
      'Slopsquatting and typosquatting via AI coding agents.',
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
    lead:
      'Dependency blindness: AI coding agents re-implementing what the standard library or codebase already has.',
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
      'Later steps build on whatever is in context, so one stale or wrong fact can steer the rest of the session. The catalog’s incidents include AI agents on GitHub that [ran commands hidden in pull-request titles, issues and comments](/incidents/copilot-prompt-injection-github-comments-2025/) and a support bot that [invented a policy that did not exist](/incidents/cursor-support-bot-fabricated-policy-2025/).',
    lead:
      "Context pollution: an AI coding agent's context degrades over a long session (stale, irrelevant or wrong material).",
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
      'In a published post-mortem, Gemini CLI [misread a failed mkdir as success](/incidents/gemini-cli-file-deletion-2025/), then ran move commands that overwrote every file but one.',
    lead:
      "Cascading failure: an AI coding agent's fixes introduce new errors, each attempt moving further from working code.",
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

// ---------- text built from the results file ----------

/** "failure planted on purpose", "real agent output": the provenance group of a set, for mid-sentence use. */
const groupPhrase = (m: Mode): string => (groupOf(m)?.label ?? m.group).replace(/^./, (c) => c.toLowerCase());

/** Meta description: what the failure is (COPY lead), then what was measured, by the file's naming rules. */
export function descriptionFor(fmId: string, m: Mode | null, s: StarMode | null): string {
  const c = copyFor(fmId);
  if (m) return `${c.lead} SAICA-Bench, ${groupPhrase(m)}: ${bestClause(m)}.`;
  return `${c.lead} Not benchmarked yet${s && s.tools.length ? `; ${int(s.tools.length)} catalog tools listed` : ''}.`;
}

// ---------- FAQ ----------

export interface QA {
  q: string;
  a: string;
}

export function faqFor(fm: FailureMode): QA[] {
  const c = copyFor(fm.id);
  const m = measured(fm.id);
  const s = starMode(fm.id);
  const name = c.subject;
  const qa: QA[] = [{ q: c.what, a: `${text(c.definition)} ${text(c.detail)}` }];
  const signals = fm.detection_signals.map((x) => text(x.trim()).replace(/([^.])$/, '$1.'));
  qa.push({
    q: `How do you detect ${name}?`,
    a:
      `Signals that point to it: ${signals.join(' ')}` +
      (m ? ` On SAICA-Bench: ${m.ranking}` : ' No detector has been measured on it yet.'),
  });
  if (m) {
    const parts = [m.ranking];
    const tool = m.best_catalog_tool;
    if (!tool) parts.push('No tool of the catalog ran a check of its own on this set.');
    else if (!m.below_floor) parts.push(`The best catalog tool that ran its own check is ${tool.short}, at J ${signedPct(tool.j)}.`);
    const shortcut = topShortcut(m);
    if (shortcut) {
      parts.push(
        `A rule with no understanding of the failure scores J ${signedPct(shortcut.j)} on the same set (${shortcut.short}), so read the scores against that, not against 0.`,
      );
    }
    parts.push(METHOD.setting);
    qa.push({ q: `Which reviewers catch ${name} on SAICA-Bench, and how well?`, a: parts.join(' ') });
    qa.push({
      q: `How was detection of ${name} measured?`,
      a:
        `On ${int(samplesOf(m))} scored samples: ${int(m.n_pos)} ${m.pos_label} and ${int(m.n_neg)} clean ones. ` +
        `Where the bad samples come from: ${groupPhrase(m)} (${m.provenance.author}). Label: ${m.provenance.label_source}. ` +
        `Data: ${m.dataset}. ${METHOD.metric}`,
    });
  } else {
    const top = s?.tools.slice(0, 4) ?? [];
    qa.push({
      q: `Which tools catch ${name}?`,
      a:
        (top.length
          ? `None has been measured. By GitHub stars, the catalog tools that address it are ${andList(top.map((t) => `${t.name} (${t.mechanism})`))}${s!.tools.length > top.length ? `, and ${s!.tools.length - top.length} more` : ''}. `
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

// ---------- classic layout of the failure-mode pages ----------
// Three cards (best overall, best free option, best LLM-based tool), one table of all results and a tier label per
// mode, as on the pages before results v2. Numbers and names come from the results file through bench.ts.

export { FLOOR, pct, int };
/** At or above this best J a mode counts as caught well (an editorial line, stated on the hub). */
export const WELL = 0.8;
/** Whole-number percentage for prose and descriptions. */
export const pct0 = (x: number) => pct(x, 0);
export const money = (c: number) => (c === 0 ? 'free' : usd(c));

export type Cat = 'program' | 'hybrid' | 'llm' | 'rule';
export const CAT_LABEL: Record<Cat, string> = {
  program: 'Free tool',
  hybrid: 'LLM-based tool',
  llm: 'LLM, zero-shot',
  rule: 'Baseline rule',
};
const TYPE_CAT: Record<string, Cat> = {
  deterministic: 'program',
  llm_based: 'hybrid',
  hybrid: 'hybrid',
  prompt_artifact: 'hybrid',
  baseline_model: 'llm',
  baseline_rule: 'rule',
};
/** "free tool", "LLM-based tool": the category label for use mid-sentence. */
export const catLower = (c: Cat) => CAT_LABEL[c].replace(/^([A-Z])(?=[a-z])/, (x) => x.toLowerCase());

export interface MRow {
  key: string;
  tool: string;
  short: string;
  cat: Cat;
  j: number;
  jCi: [number, number];
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
  /** Fewer than 95% readable answers in one class (shown with a dagger). */
  incomplete: boolean;
  unreadable: number;
  kgId: string | null;
  costNote: string;
  /** Model rows: thinking setting ("medium", "on", "off", "none"); null for tools and rules. */
  thinking: string | null;
  thinkingNote: string | null;
  /** GitHub stars and repository of a catalog tool, shown as a tag after its name. */
  stars: number | null;
  starsAt: string | null;
  repo: string | null;
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
  /** True when the best row is clearly ahead of the runner-up; otherwise it leads a tied group of `tied` rows. */
  winner: boolean;
  tied: number;
  bestFree: MRow | null;
  bestHybrid: MRow | null;
  bestLlm: MRow | null;
  /** What a rule with no understanding of the failure scores on this set. */
  shortcut: { short: string; j: number } | null;
}

function toRow(r: Row): MRow {
  return {
    key: r.key,
    tool: r.tool,
    short: r.short,
    cat: TYPE_CAT[r.type] ?? 'llm',
    j: r.j,
    jCi: r.j_ci,
    tpr: r.catch,
    fpr: r.fa,
    tprCi: r.catch_ci,
    fprCi: r.fa_ci,
    cost: r.cost,
    cost1k: r.cost1k,
    estimated: Boolean(r.cost_estimated),
    subset: r.subset_n ? r.subset_n.pos + r.subset_n.neg : null,
    incomplete: Boolean(r.incomplete),
    unreadable: r.unreadable ?? 0,
    kgId: r.kg_id ?? null,
    costNote: r.cost_note ?? '',
    thinking: r.thinking ?? null,
    thinkingNote: r.thinking_note ?? null,
    stars: typeof r.stars === 'number' ? r.stars : null,
    starsAt: r.stars_updated_at ?? null,
    repo: r.repository_url ?? null,
  };
}

function toMeasured(s: ClassicSummary): Measured {
  const m = s.m;
  const rows = s.listed.map(toRow);
  const ranked = s.listed.filter((r) => r.ranked).map(toRow);
  const top = (f: (r: MRow) => boolean) => ranked.find(f) ?? null;
  return {
    benchId: m.id,
    fm: kgId(m.id),
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
    best: toRow(s.best),
    winner: Boolean(m.winner),
    tied: m.top_group?.length ?? 1,
    // a free tool inside its design scope, else the best baseline rule we wrote for the benchmark
    bestFree: s.free ? toRow(s.free) : (rows.find((r) => r.cat === 'rule') ?? null),
    bestHybrid: top((r) => r.cat === 'hybrid'),
    bestLlm: top((r) => r.cat === 'llm'),
    shortcut: s.shortcut ? { short: s.shortcut.short, j: s.shortcut.j } : null,
  };
}
const CLASSIC_MEASURED = new Map<string, Measured>(CLASSIC.map((s) => [kgId(s.m.id), toMeasured(s)]));
/** Measured results for a KG failure-mode id in the classic shape, or null when the mode is not benchmarked. */
export const classicMeasured = (fmId: string): Measured | null => CLASSIC_MEASURED.get(kgId(fmId)) ?? null;

export type Tier = 'well' | 'partly' | 'not-yet' | 'unmeasured';
export const TIER_LABEL: Record<Tier, string> = {
  well: 'Caught well',
  partly: 'Caught partly',
  'not-yet': 'Not caught yet',
  unmeasured: 'Not measured',
};
export function tier(fmId: string): Tier {
  const m = classicMeasured(fmId);
  if (!m) return 'unmeasured';
  return m.best.j >= WELL ? 'well' : m.best.j >= FLOOR ? 'partly' : 'not-yet';
}
/** Short tool name for prose: "pyright", "deepseek-v4.1-flash", "a typosquat rule". */
export function proseName(r: MRow): string {
  return r.cat === 'rule' ? `a ${r.short}` : r.short;
}
