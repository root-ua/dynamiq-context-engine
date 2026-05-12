/**
 * Hand-maintained TypeScript mirrors of the FastAPI Pydantic models.
 * Regenerate automatically once backend is running:
 *    `pnpm api:generate`
 *
 * Until then this file is the source of truth for client-side typing.
 */

export type UUID = string;
export type ISO = string;

export interface Workspace {
  id: UUID;
  slug: string;
  name: string;
  settings: Record<string, unknown>;
  created_at: ISO;
}

export interface EntityType {
  id: UUID;
  workspace_id: UUID | null;
  name: string;
  slug: string;
  extends_id: UUID | null;
  hierarchy: string;
  schema: Record<string, unknown>;
  ui_hints: Record<string, unknown>;
  description: string | null;
  system: boolean;
}

export interface RelationType {
  id: UUID;
  workspace_id: UUID | null;
  name: string;
  slug: string;
  description: string | null;
  domain_type_id: UUID | null;
  range_type_id: UUID | null;
  cardinality_subject: "one" | "many";
  cardinality_object: "one" | "many";
  inverse_of_id: UUID | null;
  symmetric: boolean;
  transitive: boolean;
  temporal: boolean;
  high_stakes: boolean;
  ui_hints: Record<string, unknown>;
  system: boolean;
}

export interface OntologySnapshot {
  types: EntityType[];
  relations: RelationType[];
}

export interface Entity {
  id: UUID;
  workspace_id: UUID;
  type_id: UUID;
  type_slug: string | null;
  iri: string;
  canonical: string;
  aliases: string[];
  summary: string | null;
  props: Record<string, unknown>;
  merged_into_id: UUID | null;
  created_by: UUID | null;
  created_at: ISO;
  updated_at: ISO;
}

export interface Edge {
  id: UUID;
  workspace_id: UUID;
  subject_id: UUID;
  predicate_id: UUID;
  predicate_slug: string | null;
  object_id: UUID;
  fact: string;
  props: Record<string, unknown>;
  valid_from: ISO;
  valid_to: ISO | null;
  sys_from: ISO;
  sys_to: ISO | null;
  source_id: UUID | null;
  source_kind: string | null;
  confidence: number | null;
  invalidated_by: UUID | null;
  created_by: UUID | null;
  created_at: ISO;
}

export interface Document {
  id: UUID;
  workspace_id: UUID;
  entity_id: UUID;
  title: string;
  type_slug: string;
  updated_at: ISO;
}

export interface Episode {
  id: UUID;
  workspace_id: UUID;
  source_kind: string;
  source_ref: string | null;
  occurred_at: ISO;
  ingested_at: ISO;
  content_text: string | null;
  processing_status: "pending" | "processing" | "completed" | "failed";
  processing_error: string | null;
}

export interface SearchHit {
  kind: "entity" | "edge" | "episode" | "block";
  id: UUID;
  title: string;
  snippet: string;
  score: number;
  payload: Record<string, unknown>;
}

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
}

export interface GraphNode {
  id: UUID;
  type: string;
  canonical: string;
  iri: string;
  distance: number;
}

export interface GraphEdge {
  id: UUID;
  subject_id: UUID;
  object_id: UUID;
  predicate: string;
  fact: string;
  valid_from: ISO;
  valid_to: ISO | null;
}

export interface GraphPayload {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface McpTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface AuditEntry {
  id: number;
  actor_kind: "user" | "agent" | "system";
  actor_id: UUID | null;
  action: string;
  target_kind: string;
  target_id: UUID | null;
  diff: Record<string, unknown> | null;
  created_at: ISO;
}

export interface OntologyProposal {
  rationale: string;
  entity_types: Array<{
    slug: string;
    name: string;
    extends: string | null;
    description: string;
    properties: Array<{
      name: string;
      label: string;
      type: string;
      enum_values?: string[] | null;
      required?: boolean;
    }>;
  }>;
  relation_types: Array<{
    slug: string;
    name: string;
    description: string;
    domain: string;
    range: string;
    cardinality_subject: "one" | "many";
    cardinality_object: "one" | "many";
    temporal: boolean;
    symmetric: boolean;
    transitive: boolean;
    high_stakes: boolean;
  }>;
}
