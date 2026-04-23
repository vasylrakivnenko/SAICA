import type { APIRoute } from 'astro';
import { graph } from '../../../../lib/data.ts';

export function getStaticPaths() {
  return Object.values(graph.papers).map((p) => ({ params: { id: p.id } }));
}

export const GET: APIRoute = ({ params }) => {
  const p = graph.papers[String(params.id)];
  if (!p) {
    return new Response(JSON.stringify({ error: 'not_found' }), {
      status: 404,
      headers: { 'content-type': 'application/json; charset=utf-8' },
    });
  }
  return new Response(JSON.stringify(p, null, 2), {
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
};
