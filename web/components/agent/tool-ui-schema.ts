import type { UiSchema } from "@rjsf/utils";

/**
 * Heuristic ui:widget mapping per tool so the rjsf form can use the right
 * picker component (entity / relation / entity-type) instead of a raw
 * string input. Keys are MCP tool names; values are the rjsf uiSchema to
 * merge in.
 */
const PER_TOOL: Record<string, UiSchema> = {
  search_memory: {
    entity_type: { "ui:widget": "entityTypeRef" },
  },
  get_entity: {
    ref: { "ui:widget": "entityRef" },
  },
  graph_query: {
    seeds: {
      items: { "ui:widget": "entityRef" },
    },
    predicates: {
      items: { "ui:widget": "relationRef" },
    },
    types: {
      items: { "ui:widget": "entityTypeRef" },
    },
  },
  add_fact: {
    subject: { "ui:widget": "entityRef" },
    object: { "ui:widget": "entityRef" },
    predicate: { "ui:widget": "relationRef" },
  },
  invalidate_fact: {
    edge_id: { "ui:placeholder": "edge uuid" },
  },
  update_entity: {
    ref: { "ui:widget": "entityRef" },
    props: {
      "ui:options": { orderable: false },
    },
  },
  create_relation_type: {
    domain: { "ui:widget": "entityTypeRef" },
    range: { "ui:widget": "entityTypeRef" },
  },
  create_entity_type: {
    extends: { "ui:widget": "entityTypeRef" },
  },
  as_of_query: {
    subject: { "ui:widget": "entityRef" },
    predicate: { "ui:widget": "relationRef" },
  },
  propose_ontology: {
    episode_ids: {
      "ui:description":
        "Optional — use existing episode UUIDs instead of pasting samples.",
    },
  },
  add_episode: {
    content: { "ui:widget": "textarea" },
  },
};

export function uiSchemaForTool(toolName: string): UiSchema {
  return {
    "ui:submitButtonOptions": { norender: true },
    ...(PER_TOOL[toolName] ?? {}),
  };
}
