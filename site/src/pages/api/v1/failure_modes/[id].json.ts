import type { APIRoute } from 'astro';
import { graph } from '../../../../lib/data.ts';

export function getStaticPaths() {
  return Object.values(graph.failureModes).map((fm) => ({ params: { id: fm.id } }));
}

export const GET: APIRoute = ({ params }) => {
  const fm = graph.failureModes[String(params.id)];
  if (!fm) {
    return new Response(JSON.stringify({ error: 'not_found' }), {
      status: 404,
      headers: { 'content-type': 'application/json; charset=utf-8' },
    });
  }
  const enriched = {
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
    mitigating_tools: graph.toolsByFailureMode[fm.id] ?? [],
  };
  return new Response(JSON.stringify(enriched, null, 2), {
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
};
