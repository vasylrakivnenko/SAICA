import type { APIRoute } from 'astro';
import { graph } from '../../../../lib/data.ts';

export function getStaticPaths() {
  return Object.values(graph.incidents).map((i) => ({ params: { id: i.id } }));
}

export const GET: APIRoute = ({ params }) => {
  const incident = graph.incidents[String(params.id)];
  if (!incident) {
    return new Response(JSON.stringify({ error: 'not_found' }), {
      status: 404,
      headers: { 'content-type': 'application/json; charset=utf-8' },
    });
  }
  return new Response(JSON.stringify(incident, null, 2), {
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
};
