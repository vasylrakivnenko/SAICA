import type { APIRoute } from 'astro';
import { graph } from '../../../lib/data.ts';

export const GET: APIRoute = () =>
  new Response(
    JSON.stringify(Object.values(graph.taxonomies), null, 2),
    { headers: { 'content-type': 'application/json; charset=utf-8' } },
  );
