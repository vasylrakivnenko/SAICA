// Shapes served under /api/v1 for the node kinds that carry crosswalks. The list endpoint and the per-id
// endpoint of a kind call the same function, so both always have the same fields, and every crosswalk comes
// from the one normalised list (`crosswalkEdges` in data.ts), with its confidence.
import { crosswalksInto, crosswalksOf, graph } from './data.ts';
import type { FailureMode, Taxonomy } from './types.ts';

export const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });

/** A failure mode with every mapping into other taxonomies and the ids of the tools tagged with it. */
export function failureModeOut(fm: FailureMode) {
  return {
    ...fm,
    crosswalks: crosswalksOf(fm.id),
    mitigating_tools: graph.toolsByFailureMode[fm.id] ?? [],
  };
}

/** A taxonomy with every mapping from SAICA failure modes into its categories.
 *  `saica_crosswalks` (category id -> failure-mode ids, strongest first) is the older, id-only view of
 *  `crosswalks`; it is kept so existing readers do not break. */
export function taxonomyOut(tax: Taxonomy) {
  const byCategory = crosswalksInto(tax.id);
  // In the taxonomy's own category order; a mapping to an id the taxonomy does not list goes last.
  const order = [...new Set([...tax.categories.map((c) => c.external_id), ...Object.keys(byCategory)])];
  const saica_crosswalks: Record<string, string[]> = {};
  for (const externalId of order) saica_crosswalks[externalId] = (byCategory[externalId] ?? []).map((e) => e.saica_value);
  return { ...tax, crosswalks: order.flatMap((externalId) => byCategory[externalId] ?? []), saica_crosswalks };
}
