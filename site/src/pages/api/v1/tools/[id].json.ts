import type { APIRoute } from 'astro';
import { graph } from '../../../../lib/data.ts';

export function getStaticPaths() {
  return Object.values(graph.tools).map((t) => ({ params: { id: t.id } }));
}

export const GET: APIRoute = ({ params }) => {
  const tool = graph.tools[String(params.id)];
  if (!tool) {
    return new Response(JSON.stringify({ error: 'not_found' }), {
      status: 404,
      headers: { 'content-type': 'application/json; charset=utf-8' },
    });
  }
  return new Response(JSON.stringify(tool, null, 2), {
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
};
