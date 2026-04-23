import type { APIRoute } from 'astro';
import { graph } from '../../../../lib/data.ts';

export function getStaticPaths() {
  return Object.values(graph.taxonomies).map((t) => ({ params: { id: t.id } }));
}

export const GET: APIRoute = ({ params }) => {
  const tax = graph.taxonomies[String(params.id)];
  if (!tax) {
    return new Response(JSON.stringify({ error: 'not_found' }), {
      status: 404,
      headers: { 'content-type': 'application/json; charset=utf-8' },
    });
  }
  const crosswalksByCategory = graph.failureModesByTaxonomyCategory[tax.id] ?? {};
  return new Response(
    JSON.stringify({ ...tax, saica_crosswalks: crosswalksByCategory }, null, 2),
    { headers: { 'content-type': 'application/json; charset=utf-8' } },
  );
};
