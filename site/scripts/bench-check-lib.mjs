// Shared by check-bench-wording.mjs and check-results-mutation.mjs: read built pages as visible text and know
// which sentences are the results file's own.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

/** Every .html file under a build output dir. */
export function htmlFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) htmlFiles(p, out);
    else if (name.endsWith('.html')) out.push(p);
  }
  return out;
}

/** "/findings/" for <dist>/findings/index.html. */
export const pagePath = (dist, file) =>
  '/' + relative(dist, file).split(sep).join('/').replace(/index\.html$/, '');

const ENTITIES = { quot: '"', lt: '<', gt: '>', nbsp: ' ', amp: '&', apos: "'" };
export const decode = (s) =>
  s
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(Number(d)))
    .replace(/&(quot|lt|gt|nbsp|apos|amp);/g, (_, n) => ENTITIES[n]);
export const squash = (s) => s.replace(/\s+/g, ' ').trim();

const INLINE = /<\/?(?:a|b|i|em|strong|span|code|abbr|sup|sub|small|mark)\b[^>]*>/gi;
/** Visible text of an HTML fragment: scripts, styles and tags removed; inline tags join their neighbours. */
export function visibleText(html) {
  return squash(
    decode(
      html
        .replace(/<script\b[\s\S]*?<\/script>|<style\b[\s\S]*?<\/style>|<!--[\s\S]*?-->/gi, ' ')
        .replace(INLINE, '')
        .replace(/<[^>]+>/g, ' '),
    ),
  );
}

/** Every string of 12 characters or more anywhere in the results file, longest first. A page that prints one of
 *  them prints the file's sentence, not a typed one. */
export function fileStrings(results) {
  const out = new Set();
  const visit = (v) => {
    if (typeof v === 'string') {
      const s = squash(v);
      if (s.length >= 12) out.add(s);
    } else if (Array.isArray(v)) v.forEach(visit);
    else if (v && typeof v === 'object') Object.values(v).forEach(visit);
  };
  visit(results);
  return [...out].sort((a, b) => b.length - a.length);
}

/** The text with every sentence of the results file cut out: what is left was typed or computed by the site. */
export function withoutFileStrings(text, strings) {
  let t = text;
  for (const s of strings) if (t.includes(s)) t = t.split(s).join(' ');
  return t;
}

/** Every element that carries attr="value": its tag, opening tag and inner HTML (the element must not nest its
 *  own tag name). Plain string search, no pattern built from the arguments. */
export function elementsWith(html, attr, value) {
  const needle = `${attr}="${value}"`;
  const out = [];
  for (let at = html.indexOf(needle); at >= 0; at = html.indexOf(needle, at + needle.length)) {
    const lt = html.lastIndexOf('<', at);
    const gt = html.indexOf('>', at);
    const tag = /^<([a-z0-9]+)/i.exec(html.slice(lt, lt + 40))?.[1];
    if (!tag || gt < 0) continue;
    const close = html.indexOf(`</${tag}>`, gt);
    if (close > 0) out.push({ tag, open: html.slice(lt, gt + 1), inner: html.slice(gt + 1, close) });
  }
  return out;
}

export const read = (file) => readFileSync(file, 'utf8');
