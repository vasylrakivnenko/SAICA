import type { APIRoute } from 'astro';
import { graph } from '../../../../lib/data.ts';
import { jsonResponse, taxonomyOut } from '../../../../lib/api.ts';

export function getStaticPaths() {
  return Object.values(graph.taxonomies).map((t) => ({ params: { id: t.id } }));
}

export const GET: APIRoute = ({ params }) => {
  const tax = graph.taxonomies[String(params.id)];
  return tax ? jsonResponse(taxonomyOut(tax)) : jsonResponse({ error: 'not_found' }, 404);
};
