// Runs the kit builder's real page script (site/src/components/KitBuilder.astro) under node with a stub DOM.
// usage: node kb_harness.mjs <KitBuilder.astro> <kit.json>  < settings.json  > results.json
// settings: [{modes: [ids] | null, type, local, maxCost, pairs}]; null modes = the page's default selection.
import { readFileSync } from 'node:fs';

const [astroPath, kitPath] = process.argv.slice(2);
const source = readFileSync(astroPath, 'utf8');
const open = '<script is:inline define:vars={{ kit, siteUrl }}>';
const start = source.indexOf(open);
const end = source.indexOf('</script>', start);
if (start < 0 || end < 0) throw new Error('page script not found in ' + astroPath);
// The text comes from a file of this repository and is run in this test process only, never in a page.
// nosemgrep: javascript.lang.security.audit.unknown-value-with-script-tag.unknown-value-with-script-tag
const script = source.slice(start + open.length, end);
const kit = JSON.parse(readFileSync(kitPath, 'utf8'));

const node = () => ({
  textContent: '', hidden: true, checked: false, disabled: false, value: '', className: '', children: [],
  append(...k) { this.children.push(...k); }, replaceChildren(...k) { this.children = k; }, addEventListener() {},
  setAttribute() {}, remove() {}, click() {},
});
const byId = new Map();
globalThis.document = {
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, node()); return byId.get(id); },
  createElement: () => node(),
  querySelectorAll: () => [],
  body: node(),
};
globalThis.localStorage = { getItem: () => null, setItem: () => {} };
globalThis.__SAICA_KB_TEST__ = {};
new Function('kit', 'siteUrl', script)(kit, 'https://saica.example');
const api = globalThis.__SAICA_KB_TEST__;
if (!api.choose) throw new Error('the page script did not expose its test hook');

const settings = JSON.parse(readFileSync(0, 'utf8'));
const defaultModes = [...api.state.modes];
const out = settings.map((s) => {
  api.state.modes = new Set(s.modes ?? defaultModes);
  api.state.type = s.type ?? 'any';
  api.state.local = !!s.local;
  api.state.maxCost = s.maxCost ?? 'inf';
  api.state.pairs = !!s.pairs;
  api.render();
  const picks = {};
  for (const m of kit.modes) {
    const c = api.choose(m);
    picks[m.id] = { kind: c.kind, key: c.kind === 'pick' ? c.tool.key : null, pair: c.pair ? [c.pair.a, c.pair.b] : null };
  }
  return { picks, checks: api.buildChecks(), prompt: api.buildPrompt(), summary: byId.get('kb-summary').textContent, union: byId.get('kb-union').textContent };
});
process.stdout.write(JSON.stringify(out));
