// The slice of the knowledge graph that the /graph/ page draws (components/KGGraph.ts), served as
// /api/v1/graph.json: only the fields the page reads, only the papers it can draw, and one crosswalk link per
// (failure mode, taxonomy) pair. The full graph is /api/v1/snapshot.json, about ten times larger.
//
// Build-time only (it imports data.ts). KGGraph.ts imports the GraphData type from here, nothing else.
import { confidenceRank, crosswalkEdges, graph } from './data.ts';
import type { CrosswalkConfidence } from './types.ts';

export interface GraphData {
  kg_version: string;
  kg_last_updated: string;
  nodes: {
    tools: Record<string, GraphTool>;
    failure_modes: Record<string, GraphFailureMode>;
    taxonomies: Record<string, GraphTaxonomy>;
    papers: Record<string, GraphPaper>;
  };
  /** One entry per (failure mode, taxonomy) pair that has at least one mapping in data/crosswalks/. */
  crosswalks: GraphCrosswalk[];
}
export interface GraphTool {
  id: string;
  name: string;
  control_paradigm: string;
  temporal_phase: string;
  autonomy_level: string;
  addresses_failure_modes: string[];
  composes_with: string[];
  feeds_into: string[];
  supersedes: string[];
  cited_in: string[];
  stars: number | null;
  stars_updated_at: string | null;
}
export interface GraphFailureMode {
  id: string;
  name: string;
  description: string;
  aliases: string[];
  prior_work: string[];
}
export interface GraphTaxonomy {
  id: string;
  name: string;
  owner: string;
  categories: number;
}
export interface GraphPaper {
  id: string;
  title: string;
  authors: string[];
  year: number;
}
export interface GraphCrosswalk {
  failure_mode: string;
  taxonomy: string;
  /** The strongest of the pair's mappings. */
  confidence: CrosswalkConfidence;
  /** How many categories of the taxonomy the failure mode is mapped to. */
  mappings: number;
}

export function graphData(): GraphData {
  const tools = Object.values(graph.tools);
  const failureModes = Object.values(graph.failureModes);

  // Papers the page can draw: those a tool or a failure mode points to.
  const paperIds = new Set<string>();
  for (const t of tools) for (const id of [...t.cited_in, ...t.documented_in]) paperIds.add(id);
  for (const fm of failureModes) for (const id of fm.prior_work) paperIds.add(id);

  const pairs = new Map<string, GraphCrosswalk>();
  for (const e of crosswalkEdges) {
    if (e.axis !== 'failure_mode' || !graph.failureModes[e.saica_value] || !graph.taxonomies[e.taxonomy]) continue;
    const key = `${e.saica_value}\u0000${e.taxonomy}`;
    const pair = pairs.get(key);
    if (!pair) pairs.set(key, { failure_mode: e.saica_value, taxonomy: e.taxonomy, confidence: e.confidence, mappings: 1 });
    else {
      pair.mappings += 1;
      if (confidenceRank(e.confidence) < confidenceRank(pair.confidence)) pair.confidence = e.confidence;
    }
  }

  const keyed = <T extends { id: string }>(items: T[]): Record<string, T> =>
    Object.fromEntries(items.map((it) => [it.id, it]));

  return {
    kg_version: graph.kgVersion,
    kg_last_updated: graph.kgLastUpdated,
    nodes: {
      tools: keyed(
        tools.map((t) => ({
          id: t.id,
          name: t.name,
          control_paradigm: t.control_paradigm,
          temporal_phase: t.temporal_phase,
          autonomy_level: t.autonomy_level,
          addresses_failure_modes: t.addresses_failure_modes,
          composes_with: t.composes_with,
          feeds_into: t.feeds_into,
          supersedes: t.supersedes,
          cited_in: t.cited_in,
          stars: typeof t.stars === 'number' ? t.stars : null,
          stars_updated_at: t.stars_updated_at ?? null,
        })),
      ),
      failure_modes: keyed(
        failureModes.map((fm) => ({
          id: fm.id,
          name: fm.name,
          description: fm.description,
          aliases: fm.aliases,
          prior_work: fm.prior_work,
        })),
      ),
      taxonomies: keyed(
        Object.values(graph.taxonomies).map((tx) => ({
          id: tx.id,
          name: tx.name,
          owner: tx.owner,
          categories: tx.categories.length,
        })),
      ),
      papers: keyed(
        [...paperIds]
          .sort()
          .map((id) => graph.papers[id])
          .filter(Boolean)
          .map((p) => ({ id: p.id, title: p.title, authors: p.authors, year: p.year })),
      ),
    },
    crosswalks: [...pairs.values()],
  };
}
