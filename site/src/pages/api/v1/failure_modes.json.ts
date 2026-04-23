import type { APIRoute } from 'astro';
import { graph } from '../../../lib/data.ts';

// Failure modes with crosswalks expanded to include taxonomy name + external label.
export const GET: APIRoute = () => {
  const enriched = Object.values(graph.failureModes).map((fm) => ({
    ...fm,
    crosswalks: fm.crosswalks.map((cw) => {
      const tax = graph.taxonomies[cw.taxonomy];
      const cat = tax?.categories.find((c) => c.external_id === cw.external_id);
      return {
        ...cw,
        taxonomy_name: tax?.name,
        external_label: cat?.label,
      };
    }),
  }));
  return new Response(JSON.stringify(enriched, null, 2), {
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
};
