import type { APIRoute } from 'astro';
import { graph } from '../../../lib/data.ts';
import { failureModeOut, jsonResponse } from '../../../lib/api.ts';

// Failure modes, each with its crosswalk mappings (taxonomy name, category label, confidence) and tagged tools.
export const GET: APIRoute = () => jsonResponse(Object.values(graph.failureModes).map(failureModeOut));
