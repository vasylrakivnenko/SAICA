// Post-build check: no built page makes a benchmark statement the results file does not support.
//   node scripts/check-bench-wording.mjs [out dir] [results.json]
//   (defaults: dist and public/bench/results.json; `npm run check:wording` after a build)
//
// 1. Retired wording. Claims of the pre-v2 pages must not come back ("best in 8 of 9", the "4 of 4" wrapper
//    comparison, an "upper bound", a "Best tool" heading, the "mostly yes, and cheaply" lead).
//    The layout of those pages is back by the owner's choice (2026-11-22): one grid with an Average column, the
//    tier names "Caught well / partly / Not caught yet" and the word "unsolved" are allowed again; the caveats
//    under the grid say what an average and a tier do not mean.
//    A sentence printed verbatim from the results file is not typed wording and is left out of this search:
//    the file may say "in 4 of 4 comparisons" about a count it computed.
// 2. Who is named best. Every element marked data-best-for="<mode>" must follow the file: nobody is named
//    where the mode is under the floor, the winner where the file names one, a top group otherwise, and never
//    a baseline rule, a shortcut baseline or any other unranked row.
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { elementsWith, fileStrings, htmlFiles, pagePath, read, visibleText, withoutFileStrings } from './bench-check-lib.mjs';

const DIST = process.argv[2] ? resolve(process.argv[2]) : fileURLToPath(new URL('../dist/', import.meta.url));
const RESULTS = process.argv[3] ? resolve(process.argv[3]) : fileURLToPath(new URL('../public/bench/results.json', import.meta.url));
if (!existsSync(resolve(DIST, 'index.html'))) throw new Error(`no build output at ${DIST}`);
const results = JSON.parse(readFileSync(RESULTS, 'utf8'));
const strings = fileStrings(results);

const RETIRED = [
  [/\bbest in \d+ of \d+\b/i, 'a count of modes "won"'],
  [/\b\d+ of \d+\b[^.|]{0,40}\bmodes?\b[^.|]{0,40}\b(?:wins?|won|is the best|are the best)\b/i, 'a count of modes "won"'],
  [/\bbelow [^.|]{0,60}\bin 4 of 4\b|\b4 of 4 modes\b/i, 'the old wrapper comparison'],
  [/\bupper bound\b/i, '"upper bound"'],
  [/\bbest (?:measured )?tool\b|\bbest product\b/i, '"best tool" (say best reviewer or best catalog tool)'],
  [/short answer: mostly yes/i, 'the old findings lead'],
];
// Sentences that state the rule itself ("no average over modes is shown") are allowed.
const ALLOWED = [/\bno average (?:over|across) modes\b/gi, /\bno (?:ranking or )?average across failure modes\b/gi];

const problems = [];
const add = (page, msg) => problems.push(`${page}: ${msg}`);

for (const file of htmlFiles(DIST)) {
  const page = pagePath(DIST, file);
  const html = read(file);

  // 1. retired wording, outside the file's own sentences
  let typed = withoutFileStrings(visibleText(html), strings);
  for (const ok of ALLOWED) typed = typed.replace(ok, ' ');
  for (const [re, what] of RETIRED) {
    const m = typed.match(re);
    if (m) add(page, `${what}: "...${typed.slice(Math.max(0, m.index - 50), m.index + m[0].length + 50)}..."`);
  }

  // 2. who is named best
  for (const m of results.modes) {
    const names = (rows) => [...new Set(rows.flatMap((r) => [r.short, r.tool]).filter(Boolean))];
    const unranked = names(m.rows.filter((r) => !r.ranked));
    const ranked = names(m.rows.filter((r) => r.ranked));
    const winner = m.winner ? m.rows.find((r) => r.key === m.winner) : null;
    for (const el of elementsWith(html, 'data-best-for', m.id)) {
      const text = visibleText(el.inner);
      const named = (list) => list.filter((n) => text.includes(n) && !ranked.some((r) => r !== n && r.includes(n) && text.includes(r)));
      if (m.below_floor) {
        const who = named([...ranked, ...unranked]);
        if (who.length) add(page, `${m.id} is under the floor but a best reviewer is named: ${who.join(', ')}`);
        continue;
      }
      const bad = named(unranked.filter((n) => !ranked.includes(n)));
      if (bad.length) add(page, `${m.id}: an unranked row is named as best reviewer: ${bad.join(', ')}`);
      if (winner && !text.includes(winner.short)) add(page, `${m.id}: the file's winner ${winner.short} is not named ("${text}")`);
      if (!winner && m.top_group.length > 1 && !/top group/i.test(text)) add(page, `${m.id}: no winner in the file, but the cell does not say "top group" ("${text}")`);
    }
  }
}

if (problems.length) {
  console.error(`check-bench-wording: ${problems.length} problem(s) in ${DIST}`);
  for (const p of problems) console.error('  ' + p);
  process.exit(1);
}
console.log(`check-bench-wording: OK (${htmlFiles(DIST).length} pages, results ${results.version}, ${results.modes.length} modes)`);
