"use client";
import * as React from "react";
import { createReactInlineContentSpec } from "@blocknote/react";
import {
  PiArrowSquareOut as ExternalLink,
  PiSpinnerGap as Loader2,
} from "react-icons/pi";

import { cn } from "@/lib/utils";
import { useWorkspace } from "@/lib/workspace-context";
import { useEntityById } from "@/components/editor/useEntityById";

/**
 * Read a css color from the type's `ui_hints.color` payload, falling back
 * to a tasteful default. Typed-entity pills are the visual anchor of the
 * editor so small things (contrast, dot size) matter here.
 */
function readTypeColor(uiHints: unknown): string {
  if (uiHints && typeof uiHints === "object") {
    const color = (uiHints as { color?: unknown }).color;
    if (typeof color === "string" && color.length > 0) return color;
  }
  return "#6366f1"; // indigo-500
}

interface PopoverProps {
  workspaceSlug: string | null | undefined;
  entityId: string;
  canonical: string;
  typeLabel: string | null;
  onClose: () => void;
  anchor: { x: number; y: number };
}

function MentionPopover({
  workspaceSlug,
  entityId,
  canonical,
  typeLabel,
  anchor,
  onClose,
}: PopoverProps) {
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (!ref.current) return;
      if (!ref.current.contains(event.target as Node)) onClose();
    };
    const esc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", handler);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", esc);
    };
  }, [onClose]);

  const href = workspaceSlug
    ? `/${workspaceSlug}/entities/${entityId}`
    : `/entities/${entityId}`;

  return (
    <div
      ref={ref}
      className="fixed z-50 w-64 rounded-md border bg-popover p-3 text-popover-foreground shadow-md"
      style={{ top: anchor.y, left: anchor.x }}
      role="dialog"
    >
      <div className="text-sm font-medium">{canonical}</div>
      {typeLabel && (
        <div className="mt-0.5 text-xs text-muted-foreground">{typeLabel}</div>
      )}
      <a
        href={href}
        className="mt-3 flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
      >
        <ExternalLink className="h-3 w-3" /> Open entity
      </a>
    </div>
  );
}

interface ChipProps {
  entityId: string;
  fallbackLabel: string;
  entityType: string;
}

function Chip({ entityId, fallbackLabel, entityType }: ChipProps) {
  const { workspace } = useWorkspace();
  const query = useEntityById(entityId);
  const [popover, setPopover] = React.useState<{ x: number; y: number } | null>(
    null,
  );

  const entity = query.data;
  const color = readTypeColor(
    // Prefer the entity's type ui_hints if the backend embeds them
    // (via `props`), else fall back to the stored `entityType` slug.
    entity?.props?.ui_hints,
  );
  const typeLabel = entity?.type_slug ?? entityType ?? null;
  const canonical = entity?.canonical ?? fallbackLabel;
  const isError = !query.isLoading && !entity;

  const onClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setPopover({ x: rect.left, y: rect.bottom + 4 });
  };

  return (
    <>
      <button
        type="button"
        contentEditable={false}
        onClick={onClick}
        className={cn(
          "mx-0.5 inline-flex items-center gap-1 rounded-md border border-transparent bg-muted/60 px-1.5 py-0.5 align-baseline text-sm font-medium leading-tight",
          "hover:border-border hover:bg-muted",
          "data-[selected=true]:bg-primary/20",
        )}
        data-entity-id={entityId}
        data-entity-type={typeLabel ?? ""}
        title={typeLabel ? `${typeLabel} · ${canonical}` : canonical}
      >
        <span
          aria-hidden
          className="inline-block h-1.5 w-1.5 rounded-full"
          style={{ backgroundColor: color }}
        />
        <span className="text-muted-foreground">@</span>
        {query.isLoading ? (
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            {fallbackLabel}
          </span>
        ) : isError ? (
          <span className="text-muted-foreground line-through">
            {fallbackLabel}
          </span>
        ) : (
          <span>{canonical}</span>
        )}
      </button>
      {popover && (
        <MentionPopover
          workspaceSlug={workspace?.slug}
          entityId={entityId}
          canonical={canonical}
          typeLabel={typeLabel}
          anchor={popover}
          onClose={() => setPopover(null)}
        />
      )}
    </>
  );
}

/**
 * BlockNote inline content spec for typed entity mentions. Stored props
 * are stable across clients; render-time enrichment (canonical name,
 * type color) comes from the cached `useEntityById` query so that
 * edits elsewhere to the entity propagate here without a document save.
 */
export const EntityMention = createReactInlineContentSpec(
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
    render: (props) => {
      const { entityId, entityType, fallbackLabel } = props.inlineContent.props;
      return (
        <Chip
          entityId={entityId}
          entityType={entityType}
          fallbackLabel={fallbackLabel}
        />
      );
    },
  },
);
