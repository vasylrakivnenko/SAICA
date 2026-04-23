// Thin shim: everything lives in types.generated.ts (auto-generated from the
// canonical Pydantic models in pipeline/models.py, via the committed
// schema/*.json). This file exists so existing imports of '../../lib/types'
// continue to resolve without any callsite changes.
export * from './types.generated.ts';
