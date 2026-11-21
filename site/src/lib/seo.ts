// Shared URL + metadata helpers for SEO. Every internal link to a failure-mode or tool page, and every absolute URL in
// metadata, goes through these so the site has one canonical form: https://saica.ai, trailing slash, hyphenated slugs.

export const SITE = 'https://saica.ai';
export const SITE_NAME = 'SAICA-Bench';
export const OG_IMAGE = '/og.png';

// Leaderboard (bench/results.json) mode ids -> knowledge-graph failure-mode ids, and back.
export const BENCH_TO_KG: Record<string, string> = {
  'test-manipulation': 'test_manipulation',
  security: 'security_vulnerability',
  supply_chain: 'supply_chain_attack',
};
export const KG_TO_BENCH: Record<string, string> = Object.fromEntries(
  Object.entries(BENCH_TO_KG).map(([b, k]) => [k, b]),
);
export const kgId = (benchModeId: string): string => BENCH_TO_KG[benchModeId] ?? benchModeId;
export const benchId = (kgFailureModeId: string): string => KG_TO_BENCH[kgFailureModeId] ?? kgFailureModeId;

/** URL slug for a failure mode: KG id with hyphens (scope_creep -> scope-creep). */
export const fmSlug = (kgFailureModeId: string): string => kgFailureModeId.replace(/_/g, '-');
/** Canonical path of a failure-mode page. Accepts a KG id or a leaderboard mode id. */
export const fmUrl = (id: string): string => `/failure-modes/${fmSlug(kgId(id))}/`;
/** Canonical path of a tool page (KG tool id). */
export const toolUrl = (toolId: string): string => `/tools/${toolId}/`;
/** Leaderboard tab for a failure mode (leaderboard mode id or KG id). */
export const leaderboardUrl = (id: string): string => `/#${benchId(id)}`;

/** Absolute URL on the production site, with a trailing slash for page paths. */
export function abs(path: string): string {
  const u = new URL(path, SITE);
  if (!/\.[a-z0-9]+$/i.test(u.pathname) && !u.pathname.endsWith('/')) u.pathname += '/';
  return u.toString();
}

/** Trim to at most `max` characters on a word boundary, with an ellipsis when cut. */
export function clip(text: string, max = 155): string {
  const s = (text ?? '').replace(/\s+/g, ' ').trim();
  if (s.length <= max) return s;
  const cut = s.slice(0, max - 1);
  const sp = cut.lastIndexOf(' ');
  return (sp > max * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,;:.—-]+$/, '') + '…';
}

/** Serialise JSON-LD for a <script type="application/ld+json"> without letting "<" end the tag early. */
export const jsonLd = (data: unknown): string => JSON.stringify(data).replace(/</g, '\\u003c');

export function breadcrumbs(items: Array<[name: string, path: string]>) {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map(([name, path], i) => ({ '@type': 'ListItem', position: i + 1, name, item: abs(path) })),
  };
}
