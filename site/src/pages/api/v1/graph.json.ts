import type { APIRoute } from 'astro';
import { graphData } from '../../../lib/graph-data.ts';

// What the /graph/ page downloads. Not pretty-printed: it is read by a script, and the readable full graph is
// /api/v1/snapshot.json.
export const GET: APIRoute = () =>
  new Response(JSON.stringify(graphData()), {
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
