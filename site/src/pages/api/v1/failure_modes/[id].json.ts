import type { APIRoute } from 'astro';
import { graph } from '../../../../lib/data.ts';
import { failureModeOut, jsonResponse } from '../../../../lib/api.ts';

export function getStaticPaths() {
  return Object.values(graph.failureModes).map((fm) => ({ params: { id: fm.id } }));
}

export const GET: APIRoute = ({ params }) => {
  const fm = graph.failureModes[String(params.id)];
  return fm ? jsonResponse(failureModeOut(fm)) : jsonResponse({ error: 'not_found' }, 404);
};
