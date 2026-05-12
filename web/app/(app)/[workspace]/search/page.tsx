"use client";

import Link from "next/link";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PiMagnifyingGlass as SearchIcon } from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { searchApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

export default function SearchPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();

  const initial = sp.get("q") ?? "";
  const [query, setQuery] = useState(initial);
  const [expandGraph, setExpandGraph] = useState(false);

  const results = useQuery({
    queryKey: ["search", wsId, initial, expandGraph],
    queryFn: () =>
      searchApi.search(wsId, {
        query: initial,
        graph_expand: expandGraph,
        limit: 40,
      }),
    enabled: !!wsId && initial.length > 0,
  });

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    void router.push(`${pathname}?q=${encodeURIComponent(query)}`);
  }

  if (!workspace) return null;
  const base = `/${workspace.slug}`;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 md:p-6">
      <form onSubmit={onSubmit} className="flex items-center gap-2">
        <div className="relative flex-1">
          <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search entities, edges, episodes, and blocks…"
            className="pl-9"
          />
        </div>
        <Button type="submit">Search</Button>
      </form>
      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <Switch
          checked={expandGraph}
          onChange={(e) => setExpandGraph(e.target.checked)}
        />
        Expand by graph neighbors
      </label>

      {!initial ? (
        <EmptyState
          title="Search memory"
          description="Hybrid retrieval combines vector embeddings, full-text search, and fuzzy matching."
        />
      ) : results.isLoading ? (
        <Card>
          <CardContent className="space-y-3 p-4">
            <div className="h-4 w-3/5 animate-pulse rounded bg-muted" />
            <div className="h-3 w-4/5 animate-pulse rounded bg-muted" />
            <div className="h-3 w-2/5 animate-pulse rounded bg-muted" />
          </CardContent>
        </Card>
      ) : (results.data?.hits ?? []).length === 0 ? (
        <EmptyState
          title="No hits"
          description={`Nothing for "${initial}" yet.`}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <ul className="divide-y text-sm">
              {(results.data?.hits ?? []).map((h) => (
                <li key={`${h.kind}:${h.id}`} className="space-y-1 p-4">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{h.kind}</Badge>
                    {h.kind === "entity" ? (
                      <Link
                        className="font-medium hover:underline"
                        href={`${base}/entities/${h.id}`}
                      >
                        {h.title}
                      </Link>
                    ) : h.kind === "block" &&
                      typeof h.payload.document_id === "string" ? (
                      <Link
                        className="font-medium hover:underline"
                        href={`${base}/documents/${h.payload.document_id}`}
                      >
                        {h.title}
                      </Link>
                    ) : (
                      <span className="font-medium">{h.title}</span>
                    )}
                    <span className="ml-auto text-xs text-muted-foreground">
                      score {h.score.toFixed(3)}
                    </span>
                  </div>
                  {h.snippet && (
                    <p className="line-clamp-2 text-muted-foreground">
                      {h.snippet}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
