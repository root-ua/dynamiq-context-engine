import { api, getToken } from "./client";
import type {
  ActionInvocation,
  ActionType,
  AuditEntry,
  Document,
  DocumentRevision,
  Edge,
  Entity,
  EntityType,
  Episode,
  ExportJob,
  ExtractionPolicy,
  GraphPayload,
  Label,
  LabelPolicy,
  LabelPolicyAction,
  LabelPolicyRule,
  McpTool,
  OntologyProposal,
  OntologySnapshot,
  PendingFact,
  ProvenanceDoc,
  RelationType,
  SearchResponse,
  Workspace,
} from "./types";

// ---------------------------------------------------------------------------
// Auth / identity
// ---------------------------------------------------------------------------

export const meApi = {
  get: (workspaceId?: string | null) =>
    api<{ user_id: string; email: string | null; workspace_id: string | null }>(
      "/api/me",
      { workspaceId },
    ),
};

// ---------------------------------------------------------------------------
// Build info (git sha + alembic schema version)
// ---------------------------------------------------------------------------

export interface VersionInfo {
  version: string;
  commit: string | null;
  deployed_at: string | null;
  schema_version: string | null;
}

export const versionApi = {
  get: () => api<VersionInfo>("/api/version"),
};

// ---------------------------------------------------------------------------
// Workspaces
// ---------------------------------------------------------------------------

export const workspacesApi = {
  list: () => api<Workspace[]>("/api/workspaces"),
  create: (data: {
    slug: string;
    name: string;
    ontology_mode: "strict" | "flexible" | "auto";
  }) => api<Workspace>("/api/workspaces", { method: "POST", body: data }),
  get: (id: string) =>
    api<Workspace>(`/api/workspaces/${id}`, { workspaceId: id }),
  update: (
    id: string,
    patch: {
      name?: string;
      ontology_mode?: string;
      high_sensitivity?: boolean;
    },
  ) =>
    api<Workspace>(`/api/workspaces/${id}`, {
      method: "PATCH",
      body: patch,
      workspaceId: id,
    }),
  remove: (id: string, slug: string) =>
    api<void>(`/api/workspaces/${id}`, {
      method: "DELETE",
      body: { slug },
      workspaceId: id,
    }),
  seedDemo: (id: string) =>
    api<{
      entities_created: number;
      entities_updated: number;
      edges_created: number;
      edges_invalidated: number;
      documents_created: number;
      episodes_created: number;
      agent_sessions_created: number;
      home_document_id: string | null;
    }>(`/api/workspaces/${id}/seed-demo`, {
      method: "POST",
      workspaceId: id,
    }),
};

export const accountApi = {
  revokeAllSessions: () =>
    api<void>("/api/auth/revoke-all-sessions", { method: "POST" }),
  deleteAccount: () => api<void>("/api/me", { method: "DELETE" }),
};

// ---------------------------------------------------------------------------
// Members + invites
// ---------------------------------------------------------------------------

export type WorkspaceRole = "owner" | "admin" | "editor" | "viewer";

export interface WorkspaceMember {
  user_id: string;
  email: string | null;
  name: string | null;
  role: WorkspaceRole;
  joined_at: string;
}

export interface WorkspaceInvite {
  id: string;
  workspace_id: string;
  invited_email: string | null;
  invited_by: string;
  role: WorkspaceRole;
  token: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
  url?: string;
}

export interface InvitePreview {
  workspace_id: string;
  workspace_slug: string;
  workspace_name: string;
  role: WorkspaceRole;
  invited_by_email: string | null;
  invited_by_name: string | null;
  invited_email: string | null;
}

export const membersApi = {
  list: (workspaceId: string) =>
    api<WorkspaceMember[]>(`/api/workspaces/${workspaceId}/members`, {
      workspaceId,
    }),
  updateRole: (workspaceId: string, userId: string, role: WorkspaceRole) =>
    api<{ status: string }>(
      `/api/workspaces/${workspaceId}/members/${userId}`,
      {
        method: "PATCH",
        body: { role },
        workspaceId,
      },
    ),
  remove: (workspaceId: string, userId: string) =>
    api<void>(`/api/workspaces/${workspaceId}/members/${userId}`, {
      method: "DELETE",
      workspaceId,
    }),

  listInvites: (workspaceId: string) =>
    api<WorkspaceInvite[]>(`/api/workspaces/${workspaceId}/invites`, {
      workspaceId,
    }),
  createInvite: (
    workspaceId: string,
    data: {
      role: Exclude<WorkspaceRole, "owner">;
      invited_email?: string | null;
      ttl_days?: number;
    },
  ) =>
    api<WorkspaceInvite>(`/api/workspaces/${workspaceId}/invites`, {
      method: "POST",
      body: data,
      workspaceId,
    }),
  revokeInvite: (workspaceId: string, inviteId: string) =>
    api<void>(`/api/workspaces/${workspaceId}/invites/${inviteId}`, {
      method: "DELETE",
      workspaceId,
    }),
};

export const invitesApi = {
  preview: (token: string) =>
    api<InvitePreview>(`/api/invites/${token}/preview`),
  accept: (token: string) =>
    api<{ workspace_id: string }>(`/api/invites/${token}/accept`, {
      method: "POST",
    }),
};

// ---------------------------------------------------------------------------
// Ontology
// ---------------------------------------------------------------------------

export const ontologyApi = {
  snapshot: (workspaceId: string) =>
    api<OntologySnapshot>("/api/ontology/snapshot", { workspaceId }),
  listTypes: (workspaceId: string) =>
    api<EntityType[]>("/api/ontology/types", { workspaceId }),
  createType: (
    workspaceId: string,
    data: {
      name: string;
      slug?: string;
      extends?: string | null;
      schema?: Record<string, unknown>;
      ui_hints?: Record<string, unknown>;
      description?: string | null;
    },
  ) =>
    api<EntityType>("/api/ontology/types", {
      method: "POST",
      body: data,
      workspaceId,
    }),
  updateType: (
    workspaceId: string,
    ref: string,
    patch: Partial<{
      name: string;
      schema: Record<string, unknown>;
      ui_hints: Record<string, unknown>;
      description: string | null;
      extends: string | null;
    }>,
  ) =>
    api<EntityType>(`/api/ontology/types/${encodeURIComponent(ref)}`, {
      method: "PATCH",
      body: patch,
      workspaceId,
    }),
  deleteType: (workspaceId: string, ref: string) =>
    api<void>(`/api/ontology/types/${encodeURIComponent(ref)}`, {
      method: "DELETE",
      workspaceId,
    }),

  listRelations: (workspaceId: string) =>
    api<RelationType[]>("/api/ontology/relations", { workspaceId }),
  createRelation: (
    workspaceId: string,
    data: {
      name: string;
      slug?: string;
      description?: string | null;
      domain?: string;
      range?: string;
      cardinality_subject?: "one" | "many";
      cardinality_object?: "one" | "many";
      inverse_of?: string | null;
      symmetric?: boolean;
      transitive?: boolean;
      temporal?: boolean;
      high_stakes?: boolean;
    },
  ) =>
    api<RelationType>("/api/ontology/relations", {
      method: "POST",
      body: data,
      workspaceId,
    }),
  updateRelation: (
    workspaceId: string,
    ref: string,
    patch: Partial<{
      name: string;
      description: string | null;
      domain: string;
      range: string;
      cardinality_subject: "one" | "many";
      cardinality_object: "one" | "many";
      symmetric: boolean;
      transitive: boolean;
      temporal: boolean;
      high_stakes: boolean;
    }>,
  ) =>
    api<RelationType>(`/api/ontology/relations/${encodeURIComponent(ref)}`, {
      method: "PATCH",
      body: patch,
      workspaceId,
    }),
  deleteRelation: (workspaceId: string, ref: string) =>
    api<void>(`/api/ontology/relations/${encodeURIComponent(ref)}`, {
      method: "DELETE",
      workspaceId,
    }),

  propose: (
    workspaceId: string,
    data: { samples?: string[]; episode_ids?: string[]; apply?: boolean },
  ) =>
    api<{ proposal: OntologyProposal; applied?: unknown }>(
      "/api/ontology/propose",
      { method: "POST", body: data, workspaceId },
    ),
};

// ---------------------------------------------------------------------------
// Entities
// ---------------------------------------------------------------------------

export const entitiesApi = {
  list: (
    workspaceId: string,
    params: {
      type?: string;
      query?: string;
      include_subtypes?: boolean;
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.type) qs.set("type", params.type);
    if (params.query) qs.set("query", params.query);
    if (params.include_subtypes != null)
      qs.set("include_subtypes", String(params.include_subtypes));
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    return api<Entity[]>(`/api/entities${qs.size ? `?${qs}` : ""}`, {
      workspaceId,
    });
  },
  create: (
    workspaceId: string,
    data: {
      type: string;
      canonical: string;
      aliases?: string[];
      summary?: string | null;
      props?: Record<string, unknown>;
    },
  ) =>
    api<Entity>("/api/entities", { method: "POST", body: data, workspaceId }),
  get: (workspaceId: string, ref: string) =>
    api<Entity>(`/api/entities/${encodeURIComponent(ref)}`, { workspaceId }),
  update: (
    workspaceId: string,
    ref: string,
    patch: Partial<{
      canonical: string;
      aliases: string[];
      summary: string | null;
      props: Record<string, unknown>;
    }>,
  ) =>
    api<Entity>(`/api/entities/${encodeURIComponent(ref)}`, {
      method: "PATCH",
      body: patch,
      workspaceId,
    }),
  remove: (workspaceId: string, ref: string) =>
    api<void>(`/api/entities/${encodeURIComponent(ref)}`, {
      method: "DELETE",
      workspaceId,
    }),
  edges: (
    workspaceId: string,
    ref: string,
    params: { direction?: "out" | "in" | "both"; predicate?: string } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.direction) qs.set("direction", params.direction);
    if (params.predicate) qs.set("predicate", params.predicate);
    return api<Edge[]>(
      `/api/entities/${encodeURIComponent(ref)}/edges${qs.size ? `?${qs}` : ""}`,
      { workspaceId },
    );
  },
  history: (workspaceId: string, ref: string, predicate?: string) =>
    api<Edge[]>(
      `/api/entities/${encodeURIComponent(ref)}/history${predicate ? `?predicate=${encodeURIComponent(predicate)}` : ""}`,
      { workspaceId },
    ),
  backlinks: (workspaceId: string, ref: string) =>
    api<
      Array<{
        block_id: string;
        document_id: string;
        document_title: string;
        block_type: string;
        search_text: string;
      }>
    >(`/api/entities/${encodeURIComponent(ref)}/backlinks`, { workspaceId }),
  merge: (workspaceId: string, survivor: string, loserId: string) =>
    api<Entity>(`/api/entities/${encodeURIComponent(survivor)}/merge`, {
      method: "POST",
      body: { loser_id: loserId },
      workspaceId,
    }),
};

// ---------------------------------------------------------------------------
// Edges
// ---------------------------------------------------------------------------

export const edgesApi = {
  create: (
    workspaceId: string,
    data: {
      subject_id: string;
      predicate: string;
      object_id: string;
      fact?: string | null;
      valid_from?: string | null;
      valid_to?: string | null;
      confidence?: number | null;
    },
  ) => api<Edge>("/api/edges", { method: "POST", body: data, workspaceId }),
  invalidate: (workspaceId: string, id: string, reason?: string) =>
    api<Edge>(`/api/edges/${id}/invalidate`, {
      method: "POST",
      body: { reason },
      workspaceId,
    }),
  list: (
    workspaceId: string,
    params: {
      subject_id?: string;
      object_id?: string;
      predicate?: string;
      as_of_valid?: string;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.subject_id) qs.set("subject_id", params.subject_id);
    if (params.object_id) qs.set("object_id", params.object_id);
    if (params.predicate) qs.set("predicate", params.predicate);
    if (params.as_of_valid) qs.set("as_of_valid", params.as_of_valid);
    return api<Edge[]>(`/api/edges${qs.size ? `?${qs}` : ""}`, { workspaceId });
  },
};

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export const documentsApi = {
  list: (workspaceId: string, query?: string) =>
    api<Document[]>(
      `/api/documents${query ? `?query=${encodeURIComponent(query)}` : ""}`,
      { workspaceId },
    ),
  create: (workspaceId: string, data: { title: string; type?: string }) =>
    api<Document>("/api/documents", {
      method: "POST",
      body: data,
      workspaceId,
    }),
  get: (workspaceId: string, id: string) =>
    api<Document>(`/api/documents/${id}`, { workspaceId }),
  remove: (workspaceId: string, id: string) =>
    api<void>(`/api/documents/${id}`, { method: "DELETE", workspaceId }),
  blocks: (workspaceId: string, id: string) =>
    api<
      Array<{
        id: string;
        document_id: string;
        parent_block_id: string | null;
        position: number;
        block_type: string;
        content: unknown;
        props: Record<string, unknown>;
        version: number;
        search_text: string | null;
      }>
    >(`/api/documents/${id}/blocks`, { workspaceId }),
  replaceBlocks: (
    workspaceId: string,
    id: string,
    blocks: Array<{
      id: string;
      parent_block_id?: string | null;
      position?: number;
      block_type: string;
      content?: unknown;
      props?: Record<string, unknown>;
      search_text?: string;
    }>,
  ) =>
    api<{ status: string }>(`/api/documents/${id}/blocks`, {
      method: "PUT",
      body: { blocks },
      workspaceId,
    }),
  upload: async (workspaceId: string, file: File): Promise<Document> => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const token = await getToken(workspaceId);
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${apiUrl}/api/documents/upload`, {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        "X-Workspace-Id": workspaceId,
      },
      body: form,
      credentials: "include",
    });
    if (!res.ok) {
      let detail = `upload failed (${res.status})`;
      try {
        const body = (await res.json()) as { detail?: string };
        if (body.detail) detail = body.detail;
      } catch {
        /* non-json body */
      }
      throw new Error(detail);
    }
    return (await res.json()) as Document;
  },
};

// ---------------------------------------------------------------------------
// Episodes
// ---------------------------------------------------------------------------

export const episodesApi = {
  list: (workspaceId: string, status?: string) =>
    api<Episode[]>(
      `/api/episodes${status ? `?status=${encodeURIComponent(status)}` : ""}`,
      { workspaceId },
    ),
  create: (
    workspaceId: string,
    data: {
      content: string | Record<string, unknown>;
      source_kind?: string;
      source_ref?: string;
      extract?: boolean;
    },
  ) =>
    api<Episode>("/api/episodes", {
      method: "POST",
      body: data,
      workspaceId,
    }),
  get: (workspaceId: string, id: string) =>
    api<Episode>(`/api/episodes/${id}`, { workspaceId }),
  reprocess: (workspaceId: string, id: string) =>
    api<{ status: string }>(`/api/episodes/${id}/reprocess`, {
      method: "POST",
      workspaceId,
    }),
  extracted: (workspaceId: string, id: string) =>
    api<{
      episode_id: string;
      entities: Array<{ id: string; canonical: string; type_slug: string }>;
      edges: Array<{
        id: string;
        subject_id: string;
        object_id: string;
        predicate: string;
        fact: string;
        valid_from: string;
        valid_to: string | null;
        subject_canonical: string;
        subject_type: string;
        object_canonical: string;
        object_type: string;
      }>;
    }>(`/api/episodes/${id}/extracted`, { workspaceId }),
};

// ---------------------------------------------------------------------------
// Search + graph
// ---------------------------------------------------------------------------

export const searchApi = {
  search: (
    workspaceId: string,
    data: {
      query: string;
      limit?: number;
      include_kinds?: Array<"entity" | "edge" | "episode" | "block">;
      entity_type?: string | null;
      graph_expand?: boolean;
    },
  ) =>
    api<SearchResponse>("/api/search", {
      method: "POST",
      body: data,
      workspaceId,
    }),
};

export const graphApi = {
  traverse: (
    workspaceId: string,
    data: {
      seeds: string[];
      max_hops?: number;
      direction?: "out" | "in" | "both";
      predicates?: string[];
      types?: string[];
      as_of_valid?: string;
      max_nodes?: number;
    },
  ) =>
    api<GraphPayload>("/api/graph/traverse", {
      method: "POST",
      body: data,
      workspaceId,
    }),
};

// ---------------------------------------------------------------------------
// MCP
// ---------------------------------------------------------------------------

export const mcpApi = {
  tools: (workspaceId: string) =>
    api<{ tools: McpTool[] }>("/api/mcp/tools", { workspaceId }),
  invoke: (
    workspaceId: string,
    data: {
      name: string;
      arguments: Record<string, unknown>;
      session_id?: string;
    },
  ) =>
    api<{ session_id: string; result: Record<string, unknown> }>(
      "/api/mcp/invoke",
      { method: "POST", body: data, workspaceId },
    ),
  sessions: (workspaceId: string) =>
    api<
      Array<{
        id: string;
        client: string;
        started_at: string;
        ended_at: string | null;
        tool_calls: number;
      }>
    >("/api/agent-sessions", { workspaceId }),
  sessionCalls: (workspaceId: string, sessionId: string) =>
    api<
      Array<{
        id: string;
        tool: string;
        input: Record<string, unknown>;
        output: Record<string, unknown> | null;
        error: string | null;
        latency_ms: number;
        created_at: string;
      }>
    >(`/api/agent-sessions/${sessionId}/calls`, { workspaceId }),
};

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

export const auditApi = {
  list: (workspaceId: string, limit = 100) =>
    api<AuditEntry[]>(`/api/audit?limit=${limit}`, { workspaceId }),
};

// ---------------------------------------------------------------------------
// Agent tokens (long-lived bearer for MCP clients)
// ---------------------------------------------------------------------------

export interface AgentTokenRow {
  id: string;
  workspace_id: string;
  user_id: string;
  name: string;
  prefix: string;
  scopes: string[];
  last_used_at: string | null;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  kind: "user" | "service";
}

export interface AgentTokenCreated extends AgentTokenRow {
  token: string;
}

export const agentTokensApi = {
  list: (workspaceId: string) =>
    api<AgentTokenRow[]>("/api/agent-tokens", { workspaceId }),
  create: (
    workspaceId: string,
    data: {
      name: string;
      expires_in_days?: number | null;
      kind?: "user" | "service";
      scopes?: string[];
    },
  ) =>
    api<AgentTokenCreated>("/api/agent-tokens", {
      method: "POST",
      body: data,
      workspaceId,
    }),
  revoke: (workspaceId: string, id: string) =>
    api<void>(`/api/agent-tokens/${id}`, {
      method: "DELETE",
      workspaceId,
    }),
  rotate: (workspaceId: string, id: string) =>
    api<AgentTokenCreated>(`/api/agent-tokens/${id}/rotate`, {
      method: "POST",
      workspaceId,
    }),
};

// ---------------------------------------------------------------------------
// Proposals (fact review queue) + extraction policies
// ---------------------------------------------------------------------------

export const proposalsApi = {
  list: (
    workspaceId: string,
    opts: {
      status?: "pending" | "approved" | "rejected" | "superseded";
      limit?: number;
      offset?: number;
      predicate_id?: string;
      source_kind?: string;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (opts.status) qs.set("status", opts.status);
    if (opts.limit) qs.set("limit", String(opts.limit));
    if (opts.offset) qs.set("offset", String(opts.offset));
    if (opts.predicate_id) qs.set("predicate_id", opts.predicate_id);
    if (opts.source_kind) qs.set("source_kind", opts.source_kind);
    const suffix = qs.size ? `?${qs}` : "";
    return api<PendingFact[]>(`/api/proposals${suffix}`, { workspaceId });
  },
  get: (workspaceId: string, id: string) =>
    api<PendingFact>(`/api/proposals/${id}`, { workspaceId }),
  approve: (workspaceId: string, id: string, comment?: string) =>
    api<{ approved_edge_id: string; edge: Edge }>(
      `/api/proposals/${id}/approve`,
      { method: "POST", body: { comment: comment ?? null }, workspaceId },
    ),
  reject: (workspaceId: string, id: string, reason: string) =>
    api<PendingFact>(`/api/proposals/${id}/reject`, {
      method: "POST",
      body: { reason },
      workspaceId,
    }),
};

export const extractionPolicyApi = {
  list: (workspaceId: string) =>
    api<ExtractionPolicy[]>(`/api/extraction-policies`, { workspaceId }),
  upsert: (
    workspaceId: string,
    body: {
      entity_type_id?: string | null;
      relation_type_id?: string | null;
      min_confidence: number;
      auto_reject_below: number;
    },
  ) =>
    api<{ id: string }>(`/api/extraction-policies`, {
      method: "POST",
      body,
      workspaceId,
    }),
  delete: (workspaceId: string, id: string) =>
    api<void>(`/api/extraction-policies/${id}`, {
      method: "DELETE",
      workspaceId,
    }),
};

// ---------------------------------------------------------------------------
// Provenance (W3C PROV-O JSON-LD)
// ---------------------------------------------------------------------------

export const provenanceApi = {
  edge: (workspaceId: string, edgeId: string) =>
    api<ProvenanceDoc>(`/api/provenance/edge/${edgeId}`, { workspaceId }),
  episode: (workspaceId: string, episodeId: string) =>
    api<ProvenanceDoc>(`/api/provenance/episode/${episodeId}`, { workspaceId }),
};

// ---------------------------------------------------------------------------
// Sensitivity labels + label policies
// ---------------------------------------------------------------------------

export const labelsApi = {
  list: (workspaceId: string) => api<Label[]>("/api/labels", { workspaceId }),
  forTarget: (
    workspaceId: string,
    targetKind: "edge" | "episode",
    targetId: string,
  ) =>
    api<Label[]>(
      `/api/labels/for/${targetKind}/${encodeURIComponent(targetId)}`,
      { workspaceId },
    ),
  create: (
    workspaceId: string,
    body: {
      slug: string;
      name: string;
      description?: string | null;
      color?: string | null;
      parent_slug?: string | null;
    },
  ) => api<Label>("/api/labels", { method: "POST", body, workspaceId }),
  delete: (workspaceId: string, slug: string) =>
    api<void>(`/api/labels/${encodeURIComponent(slug)}`, {
      method: "DELETE",
      workspaceId,
    }),
  assign: (
    workspaceId: string,
    slug: string,
    body: { target_kind: "edge" | "episode"; target_id: string },
  ) =>
    api<{ ok: string }>(`/api/labels/${encodeURIComponent(slug)}/assign`, {
      method: "POST",
      body,
      workspaceId,
    }),
  unassign: (
    workspaceId: string,
    slug: string,
    body: { target_kind: "edge" | "episode"; target_id: string },
  ) =>
    api<{ ok: string }>(`/api/labels/${encodeURIComponent(slug)}/unassign`, {
      method: "POST",
      body,
      workspaceId,
    }),
  bulkAssign: (
    workspaceId: string,
    slug: string,
    targets: Array<{ kind: "edge" | "episode"; id: string }>,
  ) =>
    api<{ assigned: number; failed: Array<{ id: string; error: string }> }>(
      `/api/labels/${encodeURIComponent(slug)}/bulk-assign`,
      { method: "POST", body: { targets }, workspaceId },
    ),
};

export const labelPoliciesApi = {
  list: (workspaceId: string) =>
    api<LabelPolicy[]>("/api/label-policies", { workspaceId }),
  create: (
    workspaceId: string,
    body: {
      name: string;
      rule: LabelPolicyRule;
      action: LabelPolicyAction;
      enabled?: boolean;
    },
  ) =>
    api<LabelPolicy>("/api/label-policies", {
      method: "POST",
      body,
      workspaceId,
    }),
  delete: (workspaceId: string, id: string) =>
    api<void>(`/api/label-policies/${id}`, {
      method: "DELETE",
      workspaceId,
    }),
};

// ---------------------------------------------------------------------------
// Kinetic actions
// ---------------------------------------------------------------------------

export const actionTypesApi = {
  list: (workspaceId: string) =>
    api<ActionType[]>("/api/action-types", { workspaceId }),
  create: (
    workspaceId: string,
    body: {
      slug: string;
      name: string;
      description?: string | null;
      source_kind?: string | null;
      input_schema: Record<string, unknown>;
      required_role?: "viewer" | "editor" | "admin" | "owner";
      idempotency_required?: boolean;
      requires_approval?: boolean;
      side_effects?: string[];
    },
  ) =>
    api<ActionType>("/api/action-types", {
      method: "POST",
      body,
      workspaceId,
    }),
};

export const actionsApi = {
  invoke: (
    workspaceId: string,
    typeSlug: string,
    body: {
      input: Record<string, unknown>;
      idempotency_key?: string | null;
    },
  ) =>
    api<ActionInvocation>(
      `/api/actions/${encodeURIComponent(typeSlug)}/invoke`,
      { method: "POST", body, workspaceId },
    ),
  listInvocations: (
    workspaceId: string,
    opts: { status?: string; limit?: number; offset?: number } = {},
  ) => {
    const qs = new URLSearchParams();
    if (opts.status) qs.set("status", opts.status);
    if (opts.limit) qs.set("limit", String(opts.limit));
    if (opts.offset) qs.set("offset", String(opts.offset));
    const suffix = qs.size ? `?${qs}` : "";
    return api<ActionInvocation[]>(`/api/actions/invocations${suffix}`, {
      workspaceId,
    });
  },
  approve: (workspaceId: string, id: string) =>
    api<ActionInvocation>(`/api/actions/invocations/${id}/approve`, {
      method: "POST",
      workspaceId,
    }),
  reject: (workspaceId: string, id: string, reason: string) =>
    api<ActionInvocation>(`/api/actions/invocations/${id}/reject`, {
      method: "POST",
      body: { reason },
      workspaceId,
    }),
};

// ---------------------------------------------------------------------------
// Bulk operations on the review queue
// ---------------------------------------------------------------------------

export const proposalsBulkApi = {
  approve: (
    workspaceId: string,
    body: { ids: string[]; comment?: string | null },
  ) =>
    api<{
      results: Array<{ id: string; ok: boolean; error?: string }>;
    }>("/api/proposals/bulk-approve", {
      method: "POST",
      body,
      workspaceId,
    }),
  reject: (workspaceId: string, body: { ids: string[]; reason: string }) =>
    api<{
      results: Array<{ id: string; ok: boolean; error?: string }>;
    }>("/api/proposals/bulk-reject", {
      method: "POST",
      body,
      workspaceId,
    }),
};

// ---------------------------------------------------------------------------
// Document revisions
// ---------------------------------------------------------------------------

export const revisionsApi = {
  list: (workspaceId: string, documentId: string) =>
    api<DocumentRevision[]>(`/api/documents/${documentId}/revisions`, {
      workspaceId,
    }),
  create: (workspaceId: string, documentId: string, note?: string | null) =>
    api<DocumentRevision>(`/api/documents/${documentId}/revisions`, {
      method: "POST",
      body: { note: note ?? null },
      workspaceId,
    }),
  restore: (workspaceId: string, documentId: string, revisionId: string) =>
    api<{ status: string }>(
      `/api/documents/${documentId}/revisions/${revisionId}/restore`,
      { method: "POST", workspaceId },
    ),
};

// ---------------------------------------------------------------------------
// Data export
// ---------------------------------------------------------------------------

export const exportsApi = {
  startWorkspace: (workspaceId: string) =>
    api<ExportJob>(`/api/workspaces/${workspaceId}/export`, {
      method: "POST",
      workspaceId,
    }),
  pollWorkspace: (workspaceId: string, jobId: string) =>
    api<ExportJob>(`/api/workspaces/${workspaceId}/export/${jobId}`, {
      workspaceId,
    }),
  startMe: () => api<ExportJob>("/api/me/export", { method: "POST" }),
  pollMe: (jobId: string) => api<ExportJob>(`/api/me/export/${jobId}`),
};
