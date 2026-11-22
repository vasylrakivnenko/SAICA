import type { APIRoute } from 'astro';
import { graph } from '../../../lib/data.ts';
import { jsonResponse, taxonomyOut } from '../../../lib/api.ts';

// Taxonomies, each with the mappings from SAICA failure modes into its categories.
export const GET: APIRoute = () => jsonResponse(Object.values(graph.taxonomies).map(taxonomyOut));
