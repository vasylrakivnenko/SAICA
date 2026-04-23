import type { APIRoute } from 'astro';
import { graph, counts, DISCLAIMER } from '../../../lib/data.ts';

// The full-graph snapshot — the contract Agent 5's Cytoscape viz will fetch.
export const GET: APIRoute = () => {
  const body = {
    kg_version: graph.kgVersion,
    kg_last_updated: graph.kgLastUpdated,
    counts: counts(),
    disclaimer: DISCLAIMER,
    nodes: {
      tools: graph.tools,
      failure_modes: graph.failureModes,
      papers: graph.papers,
      taxonomies: graph.taxonomies,
      crosswalks: graph.crosswalks,
      incidents: graph.incidents,
      recipes: graph.recipes,
    },
  };
  return new Response(JSON.stringify(body, null, 2), {
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
};
