"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  PiArrowRight as ArrowRight,
  PiCubeTransparent as Boxes,
  PiSpinnerGap as Loader2,
  PiGraph as Network,
} from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { episodesApi } from "@/lib/api/endpoints";

interface ExtractionResultsProps {
  workspaceId: string;
  workspaceSlug: string;
  episodeId: string;
  /** When the parent row expands the accordion, we only load the data then. */
  enabled: boolean;
}

export function ExtractionResults({
  workspaceId,
  workspaceSlug,
  episodeId,
  enabled,
}: ExtractionResultsProps) {
  const query = useQuery({
    queryKey: ["episode-extracted", workspaceId, episodeId],
    queryFn: () => episodesApi.extracted(workspaceId, episodeId),
    enabled: enabled && !!workspaceId,
  });

  if (!enabled) return null;

  if (query.isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading extraction…
      </div>
    );
  }

  const data = query.data;
  if (!data || (data.entities.length === 0 && data.edges.length === 0)) {
    return (
      <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        No entities or facts were extracted from this episode.
      </div>
    );
  }

  return (
    <div className="space-y-2 rounded-md border bg-muted/20 p-3">
      {data.entities.length > 0 && (
        <section>
          <div className="mb-1 flex items-center gap-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            <Boxes className="h-3 w-3" /> Entities ({data.entities.length})
          </div>
          <div className="flex flex-wrap gap-1">
            {data.entities.map((e) => (
              <Link
                key={e.id}
                href={`/${workspaceSlug}/entities/${e.id}`}
                className="inline-flex items-center gap-1 rounded-md border bg-background px-2 py-0.5 text-xs hover:bg-accent"
              >
                <span className="font-medium">{e.canonical}</span>
                <Badge variant="outline" className="text-[10px]">
                  {e.type_slug}
                </Badge>
              </Link>
            ))}
          </div>
        </section>
      )}

      {data.edges.length > 0 && (
        <section>
          <div className="mb-1 flex items-center gap-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            <Network className="h-3 w-3" /> Facts ({data.edges.length})
          </div>
          <ul className="space-y-1 text-xs">
            {data.edges.map((edge) => (
              <li
                key={edge.id}
                className="flex flex-wrap items-center gap-1 rounded bg-background px-2 py-1"
              >
                <Link
                  href={`/${workspaceSlug}/entities/${edge.subject_id}`}
                  className="font-medium hover:underline"
                >
                  {edge.subject_canonical}
                </Link>
                <Badge variant="secondary" className="text-[10px]">
                  {edge.predicate}
                </Badge>
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <Link
                  href={`/${workspaceSlug}/entities/${edge.object_id}`}
                  className="font-medium hover:underline"
                >
                  {edge.object_canonical}
                </Link>
                {edge.valid_from && (
                  <span className="text-muted-foreground">
                    · {new Date(edge.valid_from).toLocaleDateString()}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
