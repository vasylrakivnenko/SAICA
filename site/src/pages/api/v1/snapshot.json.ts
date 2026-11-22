import type { APIRoute } from 'astro';
import { graph, counts, crosswalkEdges, DISCLAIMER } from '../../../lib/data.ts';
import { jsonResponse } from '../../../lib/api.ts';

// The full knowledge graph in one file: every node as loaded from data/, plus the crosswalk mappings as one
// flat list. `kg_version` and `kg_last_updated` are read from data/MANIFEST.json (lib/data.ts), so two builds
// of the same data give the same file. The /graph/ page reads the much smaller /api/v1/graph.json.
export const GET: APIRoute = () =>
  jsonResponse({
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
    crosswalk_edges: crosswalkEdges,
  });
