// The one set of text and number helpers for build-time code and for the page scripts that are bundled
// (KGGraph.ts, the leaderboard script on /, /taxonomy-study/, /prevention-log/). No imports, so it is safe in a
// browser bundle. The scripts on /ask/ and /assess/ are `is:inline` (they get build-time values through
// define:vars) and cannot import; they keep their own copy of escapeHtml.

/** Escape text for HTML content or for a quoted attribute value. */
export const escapeHtml = (s: unknown): string =>
  String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');

const MINUS = '−';

/** A rate as a percentage with a true minus sign: 0.943 gives "94.3%", -0.07 gives "-7.0%" (with U+2212). */
export function pct(x: number, digits = 1): string {
  const s = (Math.abs(x) * 100).toFixed(digits);
  return (x < 0 && Number(s) !== 0 ? MINUS : '') + s + '%';
}

/** J, which can be negative, always with its sign: "+94.3%", "-7.0%" (with U+2212), "0.0%". */
export function signedPct(x: number, digits = 1): string {
  const s = (Math.abs(x) * 100).toFixed(digits);
  return (Number(s) === 0 ? '' : x < 0 ? MINUS : '+') + s + '%';
}

/** A 95% interval of a rate: "88.5% to 95.2%"; of J (signed): "+88.5% to +95.2%". */
export function interval(ci: readonly number[] | null | undefined, digits = 1, signed = false): string {
  if (!ci || ci.length < 2 || ci[0] == null || ci[1] == null) return 'n/a';
  const f = signed ? signedPct : pct;
  return `${f(ci[0], digits)} to ${f(ci[1], digits)}`;
}

/** US dollars: "$0" for nothing, "$1.11" otherwise; "~" in front when the amount is an estimate. */
export const money = (usd: number, estimated = false): string =>
  usd === 0 ? '$0' : `${estimated ? '~' : ''}$${usd.toFixed(2)}`;

/** Whole number with thousands separators: 7339 gives "7,339". */
export const int = (n: number): string => n.toLocaleString('en-US');

/** A count that may have decimals, trimmed: 1.3889 gives "1.4", 26.8182 gives "26.8", 8 gives "8". */
export const num = (n: number, digits = 1): string => String(Number(n.toFixed(digits)));

/** "a", "a and b", "a, b and c". */
export function andList(items: readonly string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

/** "1 row" / "3 rows". */
export const plural = (n: number, one: string, many: string): string => `${int(n)} ${n === 1 ? one : many}`;
