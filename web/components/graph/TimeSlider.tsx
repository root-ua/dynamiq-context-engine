"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  PiClock as Clock,
  PiArrowCounterClockwise as RotateCcw,
} from "react-icons/pi";
import { format } from "date-fns";

import { Button } from "@/components/ui/button";
import { edgesApi } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";

export interface TimeSliderProps {
  workspaceId: string;
  value: string | null;
  onChange: (value: string | null) => void;
  className?: string;
}

/**
 * Horizontal "as of" time scrubber. Single-line flat control; sits in
 * its own row on the graph page so it can claim the full TopBar width
 * without making a ragged multi-height filters row.
 */
export function TimeSlider({
  workspaceId,
  value,
  onChange,
  className,
}: TimeSliderProps) {
  // Cheap aggregate from the backend (was: fetch every edge and reduce
  // client-side, which made the slider laggy on large workspaces and
  // capped the max at "now" so future-valid facts were unreachable).
  const rangeQuery = useQuery({
    queryKey: ["graph.time-range", workspaceId],
    queryFn: () => edgesApi.timeBounds(workspaceId),
    enabled: !!workspaceId,
    select: (b) => {
      if (!b) return null;
      const min = b.min_valid_from ? Date.parse(b.min_valid_from) : null;
      const max = b.max_valid_from ? Date.parse(b.max_valid_from) : null;
      if (min === null || max === null) return null;
      return { min, max };
    },
  });

  const range = rangeQuery.data;
  // Sensible fallback when the workspace has zero edges: a 30-day window
  // ending today, so the slider at least renders.
  const fallbackMax = Date.now();
  const fallbackMin = fallbackMax - 1000 * 60 * 60 * 24 * 30;
  const min = range?.min ?? fallbackMin;
  const max = range?.max ?? fallbackMax;
  const isLive = value === null;
  const current = value ? Date.parse(value) : max;

  const handleChange = React.useCallback(
    (ts: number) => {
      const clamped = Math.max(min, Math.min(max, ts));
      onChange(new Date(clamped).toISOString());
    },
    [min, max, onChange],
  );

  return (
    <div
      className={cn(
        "flex h-9 items-center gap-3 rounded-md border bg-background px-3 text-xs",
        className,
      )}
    >
      <div className="flex shrink-0 items-center gap-1.5 text-muted-foreground">
        <Clock
          className={cn(
            "h-3.5 w-3.5",
            isLive ? "text-muted-foreground" : "text-brand",
          )}
        />
        <span>As of</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={Math.max(1000, Math.floor((max - min) / 1000))}
        value={current}
        onChange={(e) => handleChange(Number(e.target.value))}
        className="h-1 min-w-0 flex-1 cursor-pointer accent-brand"
        aria-label="As-of time"
      />
      <span
        className={cn(
          "shrink-0 font-mono tabular-nums",
          isLive ? "text-muted-foreground" : "font-medium text-foreground",
        )}
      >
        {isLive ? "now" : format(new Date(current), "yyyy-MM-dd HH:mm")}
      </span>
      {!isLive && (
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 shrink-0"
          onClick={() => onChange(null)}
          aria-label="Reset time"
          title="Reset to now"
        >
          <RotateCcw className="h-3 w-3" />
        </Button>
      )}
    </div>
  );
}
