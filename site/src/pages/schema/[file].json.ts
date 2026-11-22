import type { APIRoute } from 'astro';
import fs from 'node:fs';
import path from 'node:path';

// The JSON Schemas of the knowledge-graph node kinds, served at the URLs their `$id` fields name
// (https://saica.ai/schema/<kind>.schema.json). Each file is copied unchanged from ../schema at build time,
// so the `$id` of a schema resolves to the schema itself.
const SCHEMA_DIR = path.join(import.meta.env.KG_DATA_DIR as string, '..', 'schema');

export function getStaticPaths() {
  return fs
    .readdirSync(SCHEMA_DIR)
    .filter((f) => f.endsWith('.schema.json'))
    .sort()
    .map((f) => ({ params: { file: f.replace(/\.json$/, '') } }));
}

export const GET: APIRoute = ({ params }) =>
  new Response(fs.readFileSync(path.join(SCHEMA_DIR, `${params.file}.json`), 'utf8'), {
    headers: { 'content-type': 'application/schema+json; charset=utf-8' },
  });
