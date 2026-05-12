"use client";

import { format, parseISO } from "date-fns";

import { Badge } from "@/components/ui/badge";
import type { Edge } from "@/lib/api/types";

export function EntityTimeline({ events }: { events: Edge[] }) {
  if (events.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No history recorded yet.</p>
    );
  }

  return (
    <ol className="relative space-y-3 border-l pl-4">
      {events.map((e) => {
        const closed = e.sys_to != null;
        const validEnd = e.valid_to ? parseISO(e.valid_to) : null;
        return (
          <li key={e.id} className="relative">
            <span
              className={
                "absolute -left-[22px] top-1.5 h-2.5 w-2.5 rounded-full " +
                (closed ? "bg-muted-foreground" : "bg-green-500")
              }
            />
            <div className="flex items-center gap-2 text-sm">
              <Badge variant={closed ? "outline" : "default"}>
                {e.predicate_slug}
              </Badge>
              <span
                className={closed ? "text-muted-foreground line-through" : ""}
              >
                {e.fact}
              </span>
            </div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              valid {format(parseISO(e.valid_from), "PP")}
              {validEnd ? ` → ${format(validEnd, "PP")}` : " → now"}
              {" · "}recorded {format(parseISO(e.sys_from), "PP")}
              {closed && e.sys_to
                ? ` · closed ${format(parseISO(e.sys_to), "PP")}`
                : ""}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
