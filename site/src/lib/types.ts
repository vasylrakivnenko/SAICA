// Typed domain model for SAICA-KG nodes.
// Mirrors schema/*.json with conservative defaults for optional arrays.

export type ControlParadigm = 'prevention' | 'detection' | 'correction' | 'recovery';
export type TemporalPhase = 'pre_generation' | 'in_generation' | 'post_generation';
export type AutonomyLevel = 'fully_autonomous' | 'graduated_hitl' | 'full_hitl';
export type LocusOfControl = 'model' | 'prompt' | 'context' | 'environment' | 'human';
export type MaturityStatus = 'experimental' | 'stable' | 'at_risk' | 'deprecated' | 'abandoned';
export type FailureModeId = string;
export type CrosswalkConfidence = 'exact' | 'partial' | 'broader' | 'narrower' | 'related';

export interface Tool {
  id: string;
  name: string;
  tagline?: string;
  description: string;
  first_released: string;
  last_updated?: string;
  maturity_status: MaturityStatus;
  published_by?: string;
  repository_url?: string;
  documentation_url?: string;
  license: string;
  control_paradigm: ControlParadigm;
  temporal_phase: TemporalPhase;
  autonomy_level: AutonomyLevel;
  addresses_failure_modes: FailureModeId[];
  locus_of_control: LocusOfControl[];
  implements_techniques: string[];
  composes_with: string[];
  feeds_into: string[];
  supersedes: string[];
  runtime_requires: string[];
  supervises_targets: string[];
  cited_in: string[];
  documented_in: string[];
  evaluated_on: string[];
  security_notes?: string;
  signed_manifest?: boolean;
  openssf_scorecard_score?: number | null;
  stars?: number;
  stars_updated_at?: string;
  contributors: string[];
  editorial_notes?: string;
  inclusion_rationale?: string;
}

export interface CrosswalkEntry {
  taxonomy: string;
  external_id: string;
  confidence: CrosswalkConfidence;
  note?: string;
}

export interface FailureMode {
  id: string;
  name: string;
  tagline?: string;
  description: string;
  aliases: string[];
  related_modes: string[];
  prior_work: string[];
  detection_signals: string[];
  canonical_definition_source?: string;
  crosswalks: CrosswalkEntry[];
}

export interface TaxonomyCategory {
  external_id: string;
  label: string;
  description?: string;
  parent_id?: string;
}

export interface Taxonomy {
  id: string;
  name: string;
  owner: string;
  version: string;
  first_published?: string;
  last_updated?: string;
  url?: string;
  license?: string;
  paper_id?: string;
  scope?: string;
  categories: TaxonomyCategory[];
  notes?: string;
  inclusion_rationale?: string;
}

export interface Paper {
  id: string;
  authors: string[];
  year: number;
  title: string;
  venue?: string;
  url?: string;
  doi?: string;
  arxiv_id?: string;
  semantic_scholar_id?: string;
  abstract?: string;
  tldr?: string;
  citation_count?: number;
  relevance_tags: string[];
  notes?: string;
}

export interface CrosswalkMapping {
  saica_value: string;
  external_id: string;
  confidence: CrosswalkConfidence;
  note?: string;
}

export interface Crosswalk {
  id: string;
  saica_axis: 'failure_mode' | 'control_paradigm' | 'temporal_phase' | 'autonomy_level' | 'locus_of_control';
  taxonomy: string;
  authored_by: string[];
  reviewed_by: string[];
  last_reviewed?: string;
  mappings: CrosswalkMapping[];
}

export interface Graph {
  tools: Record<string, Tool>;
  failureModes: Record<string, FailureMode>;
  taxonomies: Record<string, Taxonomy>;
  papers: Record<string, Paper>;
  crosswalks: Record<string, Crosswalk>;
  // Derived indexes:
  toolsByFailureMode: Record<string, string[]>;
  failureModesByTaxonomyCategory: Record<string, Record<string, string[]>>; // taxonomyId -> externalId -> failureModeIds
  kgVersion: string;
  kgLastUpdated: string; // ISO
}
