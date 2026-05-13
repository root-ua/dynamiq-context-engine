import * as React from "react";

import { Badge } from "@/components/ui/badge";
import type { Label } from "@/lib/api/types";

interface LabelBadgeProps {
  label: Pick<Label, "slug" | "name" | "color"> & { id?: string };
  onRemove?: () => void;
  className?: string;
}

export function LabelBadge({ label, onRemove, className }: LabelBadgeProps) {
  // Color is opt-in metadata; default to a neutral border when absent.
  const style = label.color
    ? {
        backgroundColor: `${label.color}22`,
        borderColor: label.color,
        color: label.color,
      }
    : undefined;
  return (
    <Badge
      variant="outline"
      className={className}
      style={style}
      title={label.slug}
    >
      <span>{label.name}</span>
      {onRemove && (
        <button
          type="button"
          aria-label={`Remove ${label.name}`}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="-mr-0.5 ml-1 rounded text-current hover:bg-foreground/10 focus:outline-none focus:ring-1 focus:ring-current"
        >
          ×
        </button>
      )}
    </Badge>
  );
}
