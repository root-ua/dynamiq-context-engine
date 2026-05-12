import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

import type { Entity, EntityType } from "@/lib/api/types";
import { EntityForm } from "./EntityForm";

const baseEntity: Entity = {
  id: "ent-1",
  workspace_id: "ws-1",
  type_id: "t-1",
  type_slug: "person",
  iri: "memory://person/ent-1",
  canonical: "Ada Lovelace",
  aliases: [],
  summary: null,
  props: {},
  merged_into_id: null,
  created_by: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const baseType: EntityType = {
  id: "t-1",
  workspace_id: "ws-1",
  name: "Person",
  slug: "person",
  extends_id: null,
  hierarchy: "thing.agent.person",
  schema: {
    type: "object",
    properties: {
      email: { type: "string", title: "Email" },
    },
  },
  ui_hints: {},
  description: null,
  system: true,
};

describe("EntityForm", () => {
  it("does NOT nest a <form> inside the outer <form>", () => {
    // Regression: rjsf's `<Form>` defaults to rendering a <form> element,
    // which produced a hydration error when mounted inside our outer <form>
    // on the entity detail page. We pass `tagName="div"` so only one
    // <form> ends up in the DOM.
    const { container } = render(
      <EntityForm entity={baseEntity} type={baseType} onSubmit={vi.fn()} />,
    );
    const forms = container.querySelectorAll("form");
    expect(forms).toHaveLength(1);
  });
});
