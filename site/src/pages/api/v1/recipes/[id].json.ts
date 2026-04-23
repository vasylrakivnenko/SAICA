import type { APIRoute } from 'astro';
import { graph } from '../../../../lib/data.ts';

export function getStaticPaths() {
  return Object.values(graph.recipes).map((r) => ({ params: { id: r.id } }));
}

export const GET: APIRoute = ({ params }) => {
  const recipe = graph.recipes[String(params.id)];
  if (!recipe) {
    return new Response(JSON.stringify({ error: 'not_found' }), {
      status: 404,
      headers: { 'content-type': 'application/json; charset=utf-8' },
    });
  }
  return new Response(JSON.stringify(recipe, null, 2), {
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
};
