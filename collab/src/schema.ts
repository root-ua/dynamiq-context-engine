/**
 * Server-side mirror of `web/components/editor/schema.ts`.
 *
 * BlockNote's schema has to match between the editor and any server
 * component that parses the same content (here: the Yjs hydration
 * endpoint). The web schema registers an `entityMention` inline-content
 * type via `createReactInlineContentSpec`; we can't use the React
 * variant from a Node server, so we construct the equivalent spec with
 * `createInlineContentSpec` and a no-op DOM render — we never actually
 * render in this process, we just need the schema to parse.
 *
 * **If the web schema changes, change this too.** Keep the type name,
 * prop names, and `content: "none"` in sync.
 */
import {
  BlockNoteSchema,
  createInlineContentSpec,
  defaultBlockSpecs,
  defaultInlineContentSpecs,
  defaultStyleSpecs,
} from "@blocknote/core";

const EntityMentionServerSpec = createInlineContentSpec(
  {
    type: "entityMention",
    propSchema: {
      entityId: { default: "" },
      entityType: { default: "" },
      fallbackLabel: { default: "" },
    },
    content: "none",
  },
  {
    // We never render in the Hocuspocus process; BlockNote requires a
    // function, so return a minimal DOM span. The ServerBlockNoteEditor
    // uses jsdom internally, so `document` is available at call time.
    render: () => {
      const dom = document.createElement("span");
      dom.setAttribute("data-type", "entityMention");
      return { dom };
    },
  },
);

export const memorySchema = BlockNoteSchema.create({
  blockSpecs: defaultBlockSpecs,
  inlineContentSpecs: {
    ...defaultInlineContentSpecs,
    entityMention: EntityMentionServerSpec,
  },
  styleSpecs: defaultStyleSpecs,
});
