"use client";
import * as React from "react";
import {
  SuggestionMenuController,
  getDefaultReactSlashMenuItems,
  type DefaultReactSuggestionItem,
} from "@blocknote/react";
import { filterSuggestionItems } from "@blocknote/core";
import {
  PiAt as AtSign,
  PiPlus as Plus,
  PiSparkle as Sparkles,
} from "react-icons/pi";

import { EntityPicker } from "@/components/editor/EntityPicker";
import { EntityCreateDialog } from "@/components/editor/EntityCreateDialog";
import { entitiesApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";
import type { Entity } from "@/lib/api/types";
import type { MemoryEditor } from "@/components/editor/schema";
import {
  getCurrentBlockText,
  lastNGrams,
  insertEntityMention,
} from "@/components/editor/schema";

interface SlashMenuProps {
  editor: MemoryEditor;
}

type PickerState =
  | { kind: "closed" }
  | { kind: "picker"; initialQuery?: string }
  | { kind: "create"; initialCanonical?: string };

export function SlashMenu({ editor }: SlashMenuProps) {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id ?? null;

  const [picker, setPicker] = React.useState<PickerState>({ kind: "closed" });
  const [aiCandidates, setAiCandidates] = React.useState<string[] | null>(null);

  const onInsert = React.useCallback(
    (entity: Entity, typeSlug: string) => {
      insertEntityMention(editor, {
        entityId: entity.id,
        entityType: typeSlug || entity.type_slug || "",
        fallbackLabel: entity.canonical,
      });
      editor.focus();
    },
    [editor],
  );

  // -------------------------------------------------------------------------
  // Slash menu (/) — standard blocks + custom memory items
  // -------------------------------------------------------------------------
  const getSlashItems = React.useCallback(
    (query: string): DefaultReactSuggestionItem[] => {
      const defaults = getDefaultReactSlashMenuItems(editor);
      const custom: DefaultReactSuggestionItem[] = [
        {
          title: "Insert entity",
          subtext: "Mention an existing typed entity",
          aliases: ["entity", "mention", "ref"],
          group: "Memory",
          icon: <AtSign className="h-4 w-4" />,
          onItemClick: () => setPicker({ kind: "picker" }),
        },
        {
          title: "New entity…",
          subtext: "Create and mention",
          aliases: ["new", "create", "entity"],
          group: "Memory",
          icon: <Plus className="h-4 w-4" />,
          onItemClick: () => setPicker({ kind: "create" }),
        },
        {
          title: "Ask AI to link entities",
          subtext: "Suggest mentions from the current block",
          aliases: ["ai", "link", "suggest"],
          group: "Memory",
          icon: <Sparkles className="h-4 w-4" />,
          onItemClick: () => {
            const text = getCurrentBlockText(editor);
            const candidates = lastNGrams(text, 3);
            if (candidates.length === 0) {
              setPicker({ kind: "picker" });
              return;
            }
            setAiCandidates(candidates);
          },
        },
      ];
      return filterSuggestionItems([...defaults, ...custom], query);
    },
    [editor],
  );

  // -------------------------------------------------------------------------
  // Mention menu (@) — inline, async-loaded from entitiesApi
  // -------------------------------------------------------------------------
  const getMentionItems = React.useCallback(
    async (query: string): Promise<DefaultReactSuggestionItem[]> => {
      if (!workspaceId) return [];

      const trimmed = query.trim();
      let entities: Entity[] = [];
      try {
        entities = await entitiesApi.list(workspaceId, {
          query: trimmed || undefined,
          limit: 10,
        });
      } catch {
        entities = [];
      }

      const items: DefaultReactSuggestionItem[] = entities.map((entity) => {
        const aliases = entity.aliases?.length
          ? ` (${entity.aliases.slice(0, 2).join(", ")})`
          : "";
        return {
          title: entity.canonical,
          subtext: `${entity.type_slug ?? "entity"}${aliases}`,
          aliases: [entity.canonical, ...entity.aliases.slice(0, 5)],
          group: "Entities",
          icon: <AtSign className="h-4 w-4 text-muted-foreground" />,
          onItemClick: () => onInsert(entity, entity.type_slug ?? ""),
        };
      });

      if (trimmed.length > 0) {
        items.push({
          title: `Create "${trimmed}"…`,
          subtext: "Open the new-entity dialog with this name",
          aliases: ["new", "create", trimmed],
          group: "Create",
          icon: <Plus className="h-4 w-4" />,
          onItemClick: () =>
            setPicker({ kind: "create", initialCanonical: trimmed }),
        });
      } else {
        items.push({
          title: "Create new entity…",
          subtext: "Type to search, or create one now",
          aliases: ["new", "create"],
          group: "Create",
          icon: <Plus className="h-4 w-4" />,
          onItemClick: () => setPicker({ kind: "create" }),
        });
      }

      return items;
    },
    [workspaceId, onInsert],
  );

  return (
    <>
      <SuggestionMenuController
        triggerCharacter="/"
        getItems={(query) => Promise.resolve(getSlashItems(query))}
      />
      <SuggestionMenuController
        triggerCharacter="@"
        getItems={getMentionItems}
      />

      <EntityPicker
        open={picker.kind === "picker"}
        onOpenChange={(open) =>
          setPicker(open ? { kind: "picker" } : { kind: "closed" })
        }
        initialQuery={
          picker.kind === "picker" ? picker.initialQuery : undefined
        }
        onPick={onInsert}
      />

      <EntityCreateDialog
        open={picker.kind === "create"}
        onOpenChange={(open) =>
          setPicker(open ? { kind: "create" } : { kind: "closed" })
        }
        initialCanonical={
          picker.kind === "create" ? picker.initialCanonical : undefined
        }
        onCreated={onInsert}
      />

      {aiCandidates && (
        <AiLinkPrompt
          candidates={aiCandidates}
          onPick={(candidate) => {
            setAiCandidates(null);
            setPicker({ kind: "picker", initialQuery: candidate });
          }}
          onDismiss={() => setAiCandidates(null)}
        />
      )}
    </>
  );
}

interface AiLinkPromptProps {
  candidates: string[];
  onPick: (candidate: string) => void;
  onDismiss: () => void;
}

function AiLinkPrompt({ candidates, onPick, onDismiss }: AiLinkPromptProps) {
  React.useEffect(() => {
    const esc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onDismiss();
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [onDismiss]);

  return (
    <div
      role="dialog"
      className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-md border bg-popover p-3 shadow-lg"
    >
      <div className="mb-2 flex items-center gap-2 text-sm font-medium">
        <Sparkles className="h-4 w-4 text-primary" />
        Pick a phrase to link
      </div>
      <div className="flex flex-wrap gap-2">
        {candidates.map((candidate) => (
          <button
            key={candidate}
            type="button"
            onClick={() => onPick(candidate)}
            className="rounded-md border px-2 py-1 text-xs hover:bg-accent"
          >
            {candidate}
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="mt-2 text-xs text-muted-foreground hover:underline"
      >
        Cancel
      </button>
    </div>
  );
}
