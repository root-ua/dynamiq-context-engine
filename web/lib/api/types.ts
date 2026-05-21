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
  high_sensitivity?: boolean;
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

export type ProposalStatus = "pending" | "approved" | "rejected" | "superseded";

export interface PendingFact {
  id: UUID;
  workspace_id: UUID;
  subject_id: UUID;
  predicate_id: UUID;
  object_id: UUID;
  fact: string;
  props: Record<string, unknown>;
  valid_from: ISO;
  valid_to: ISO | null;
  source_id: UUID | null;
  source_kind: string | null;
  confidence: number;
  prov_activity_id: UUID | null;
  status: ProposalStatus;
  reason: string | null;
  reviewed_by: UUID | null;
  reviewed_at: ISO | null;
  approved_edge_id: UUID | null;
  created_at: ISO;
}

export interface ExtractionPolicy {
  id: UUID;
  entity_type_id: UUID | null;
  relation_type_id: UUID | null;
  min_confidence: number;
  auto_reject_below: number;
  created_at: ISO;
  updated_at: ISO;
}

/** PROV-O JSON-LD document. Opaque to TS; passed straight to a viewer. */
export type ProvenanceDoc = Record<string, unknown>;

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

// ---------------------------------------------------------------------------
// Sensitivity labels & policy
// ---------------------------------------------------------------------------

export interface Label {
  id: UUID;
  workspace_id: UUID;
  slug: string;
  name: string;
  description: string | null;
  color: string | null;
  path: string;
  created_at: ISO;
  updated_at: ISO;
}

export type LabelPolicyAction = "drop" | "warn" | "block";

export type LabelPolicyRule =
  | { kind: "mutually_exclusive"; labels: string[] }
  | { kind: "requires_role"; labels: string[]; roles: string[] }
  | { kind: string; [k: string]: unknown };

export interface LabelPolicy {
  id: UUID;
  workspace_id: UUID;
  name: string;
  rule: LabelPolicyRule;
  action: LabelPolicyAction;
  enabled: boolean;
}

// ---------------------------------------------------------------------------
// Kinetic actions
// ---------------------------------------------------------------------------

export interface ActionType {
  id: UUID;
  workspace_id: UUID;
  slug: string;
  name: string;
  description: string | null;
  source_kind: string | null;
  input_schema: Record<string, unknown>;
  required_role: "viewer" | "editor" | "admin" | "owner";
  idempotency_required: boolean;
  requires_approval: boolean;
  side_effects: string[];
  enabled: boolean;
}

export type ActionStatus =
  | "pending"
  | "approved"
  | "executing"
  | "completed"
  | "failed"
  | "rejected";

export interface ActionInvocation {
  id: UUID;
  workspace_id: UUID;
  action_type_id: UUID;
  action_type_slug: string;
  principal_user_id: UUID | null;
  idempotency_key: string;
  input: Record<string, unknown>;
  status: ActionStatus;
  result: Record<string, unknown> | null;
  error_message: string | null;
  prov_activity_id: UUID | null;
  emitted_edge_id: UUID | null;
  started_at: ISO;
  completed_at: ISO | null;
}

// ---------------------------------------------------------------------------
// Document revisions
// ---------------------------------------------------------------------------

export interface DocumentRevision {
  id: UUID;
  workspace_id: UUID;
  document_id: UUID;
  created_by: UUID | null;
  created_at: ISO;
  note: string | null;
}

// ---------------------------------------------------------------------------
// Data export
// ---------------------------------------------------------------------------

export type ExportStatus = "queued" | "running" | "completed" | "failed";

export interface ExportJob {
  id: UUID;
  workspace_id: UUID | null;
  scope: "workspace" | "user";
  status: ExportStatus;
  download_url: string | null;
  download_expires_at: ISO | null;
  byte_size: number | null;
  error_message: string | null;
  created_at: ISO;
  completed_at: ISO | null;
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

// ---------------------------------------------------------------------------
// Integrations — Google Docs (v1)
// ---------------------------------------------------------------------------

export interface GoogleDriveConnectionSummary {
  id: UUID;
  workspace_id: UUID;
  user_id: UUID;
  account_email: string;
  scopes: string[];
  selection: {
    folders: Array<{ id: string; name: string }>;
    files: Array<{ id: string; name: string }>;
  };
  created_at: ISO;
  updated_at: ISO;
  revoked_at: ISO | null;
}

export interface DriveTreeNode {
  id: string;
  name: string;
  mime_type: string;
  is_folder: boolean;
  is_doc: boolean;
}

export interface DriveTree {
  parent: string;
  children: DriveTreeNode[];
}

export interface GoogleDocsSyncJob {
  id: UUID;
  workspace_id: UUID;
  connection_id: UUID;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  total_docs: number;
  processed_docs: number;
  failed_docs: number;
  skipped_docs: number;
  error: string | null;
  created_at: ISO;
  started_at: ISO | null;
  completed_at: ISO | null;
}

export interface GoogleDocSyncState {
  id: UUID;
  google_doc_id: string;
  doc_title: string | null;
  status: "pending" | "syncing" | "completed" | "failed" | "skipped";
  error: string | null;
  episode_id: UUID | null;
  last_synced_at: ISO | null;
}
