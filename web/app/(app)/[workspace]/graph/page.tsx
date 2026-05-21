"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import {
  PiWarning as AlertTriangle,
  PiGraph as Network,
  PiGlobe as Globe,
  PiFadersHorizontal as Filters,
  PiX as XIcon,
} from "react-icons/pi";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty";
import { Select } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/components/ui/toast";
import { graphApi } from "@/lib/api/endpoints";
import type { GraphPayload } from "@/lib/api/types";
import { useWorkspace } from "@/lib/workspace-context";

import { GraphFilters } from "@/components/graph/GraphFilters";
import { GraphLegend } from "@/components/graph/GraphLegend";
import {
  EmptyGraphState,
  SkeletonCanvas,
  StatsBar,
} from "@/components/graph/GraphPageStates";
import { SeedSearch } from "@/components/graph/SeedSearch";
import { SelectedEntityPanel } from "@/components/graph/SelectedEntityPanel";
import { TimeSlider } from "@/components/graph/TimeSlider";
import {
  DEFAULT_FILTERS,
  type GraphFiltersValue,
  type SeedEntity,
} from "@/components/graph/types";

// Sigma + graphology are DOM-only; load client-side only.
const GraphView = dynamic(
  () => import("@/components/graph/GraphView").then((m) => m.GraphView),
  { ssr: false },
);

const MAX_NODES = 500;

export default function GraphPage() {
  const { workspace, isLoading: workspaceLoading } = useWorkspace();
  const { push } = useToast();

  const [seeds, setSeeds] = React.useState<SeedEntity[]>([]);
  const [filters, setFilters] =
    React.useState<GraphFiltersValue>(DEFAULT_FILTERS);
  const [selectedNode, setSelectedNode] = React.useState<string | null>(null);
  // "Show whole graph" mode — bypasses seeds and pulls everything via
  // /api/graph/all. Default to true so the page shows something immediately
  // on landing; users opt INTO seed-based traversal by picking a seed.
  const [showAll, setShowAll] = React.useState(true);

  const workspaceId = workspace?.id ?? "";
  const workspaceSlug = workspace?.slug ?? "";

  const seedIds = React.useMemo(() => seeds.map((s) => s.id), [seeds]);

  // Whole-graph query — disabled unless showAll is on. Filters mirror
  // the seed-based traversal so the same sidebar UI controls both modes.
  const allGraph = useQuery({
    queryKey: [
      "graph.all",
      workspaceId,
      MAX_NODES,
      filters.types,
      filters.predicates,
      filters.asOf,
    ],
    enabled: !!workspaceId && showAll,
    queryFn: () =>
      graphApi.all(workspaceId, {
        maxNodes: MAX_NODES,
        types: filters.types.length ? filters.types : undefined,
        predicates: filters.predicates.length ? filters.predicates : undefined,
        asOfValid: filters.asOf ?? undefined,
      }),
  });

  // Seed-rooted traversal — disabled when showAll is on or no seeds picked.
  const traversal = useQuery({
    queryKey: [
      "graph.traverse",
      workspaceId,
      seedIds,
      filters.maxHops,
      filters.direction,
      filters.predicates,
      filters.types,
      filters.asOf,
    ],
    enabled: !!workspaceId && seedIds.length > 0 && !showAll,
    queryFn: () =>
      graphApi.traverse(workspaceId, {
        seeds: seedIds,
        max_hops: filters.maxHops,
        direction: filters.direction,
        predicates: filters.predicates.length ? filters.predicates : undefined,
        types: filters.types.length ? filters.types : undefined,
        as_of_valid: filters.asOf ?? undefined,
        max_nodes: MAX_NODES,
      }),
  });

  // Unified view-result the canvas reads — whichever mode is active wins.
  const activeQuery: UseQueryResult<GraphPayload, Error> = showAll
    ? allGraph
    : traversal;

  // Hide orphan entities (no edges) from the viz. Extraction sometimes
  // leaves these behind when the ontology guard rejects all their edges,
  // and they render as isolated grey dots that look like junk.
  // In seed-rooted mode, the seed itself can be orphan-in-the-result if
  // no edges came back — keep seeds regardless so the user sees what
  // they asked for.
  const filteredPayload: GraphPayload | undefined = React.useMemo(() => {
    const payload = activeQuery.data;
    if (!payload) return payload;
    const connected = new Set<string>();
    for (const e of payload.edges) {
      connected.add(e.subject_id);
      connected.add(e.object_id);
    }
    const seedSet = new Set(seedIds);
    return {
      ...payload,
      nodes: payload.nodes.filter(
        (n) => connected.has(n.id) || seedSet.has(n.id),
      ),
    };
  }, [activeQuery.data, seedIds]);

  React.useEffect(() => {
    if (activeQuery.isError) {
      push({
        title: showAll ? "Failed to load full graph" : "Graph traversal failed",
        description:
          activeQuery.error instanceof Error
            ? activeQuery.error.message
            : "Unknown error",
        variant: "destructive",
      });
    }
  }, [activeQuery.isError, activeQuery.error, push, showAll]);

  // Esc clears selection.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelectedNode(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const handleNodeClick = React.useCallback(
    (id: string) => setSelectedNode(id),
    [],
  );
  const handleCanvasClick = React.useCallback(() => setSelectedNode(null), []);

  const addSeed = React.useCallback((seed: SeedEntity) => {
    setSeeds((prev) =>
      prev.some((s) => s.id === seed.id) ? prev : [...prev, seed],
    );
    // Picking a seed implies "I want to explore from here" — switch out
    // of whole-graph view to a seed-rooted traversal.
    setShowAll(false);
    setSelectedNode(null);
  }, []);

  const removeSeed = React.useCallback((id: string) => {
    setSeeds((prev) => prev.filter((s) => s.id !== id));
  }, []);

  const focusOn = React.useCallback(
    (nodeId: string) => {
      const payload = activeQuery.data;
      const node = payload?.nodes.find((n) => n.id === nodeId);
      if (!node) return;
      // Focusing a node implicitly switches off whole-graph mode and seeds it.
      setShowAll(false);
      setSeeds([{ id: node.id, canonical: node.canonical, type: node.type }]);
      setSelectedNode(null);
    },
    [activeQuery.data],
  );

  if (!workspace) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <EmptyState
          title={
            workspaceLoading ? "Loading workspace…" : "No workspace selected"
          }
          description={
            workspaceLoading
              ? "Fetching your workspaces."
              : "Choose a workspace to explore its graph."
          }
          icon={Network}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-[calc(100vh-3rem)] w-full flex-col bg-background">
      <TopBar
        workspaceId={workspaceId}
        seeds={seeds}
        filters={filters}
        onFiltersChange={setFilters}
        onAddSeed={addSeed}
        onRemoveSeed={removeSeed}
        showAll={showAll}
        onToggleShowAll={() => {
          setShowAll((prev: boolean) => !prev);
          setSelectedNode(null);
        }}
      />
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-72 shrink-0 border-r md:block">
          <GraphFilters
            workspaceId={workspaceId}
            value={filters}
            onChange={setFilters}
          />
        </aside>

        <main className="relative flex min-w-0 flex-1 flex-col">
          <GraphCanvas
            workspaceId={workspaceId}
            seeds={seeds}
            showAll={showAll}
            payload={filteredPayload}
            isLoading={activeQuery.isLoading}
            isError={activeQuery.isError}
            error={activeQuery.error}
            onRetry={() => activeQuery.refetch()}
            selectedNode={selectedNode}
            onNodeClick={handleNodeClick}
            onCanvasClick={handleCanvasClick}
            onAddSeed={addSeed}
          />
        </main>

        {selectedNode && (
          <>
            <aside className="hidden w-80 shrink-0 lg:block">
              <SelectedEntityPanel
                workspaceId={workspaceId}
                workspaceSlug={workspaceSlug}
                nodeId={selectedNode}
                payload={activeQuery.data}
                onClose={() => setSelectedNode(null)}
                onFocus={focusOn}
              />
            </aside>
            <div className="fixed inset-x-0 bottom-0 z-40 max-h-[70vh] overflow-y-auto border-t bg-background shadow-lg lg:hidden">
              <SelectedEntityPanel
                workspaceId={workspaceId}
                workspaceSlug={workspaceSlug}
                nodeId={selectedNode}
                payload={activeQuery.data}
                onClose={() => setSelectedNode(null)}
                onFocus={focusOn}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Top bar
// ---------------------------------------------------------------------------

function TopBar({
  workspaceId,
  seeds,
  filters,
  onFiltersChange,
  onAddSeed,
  onRemoveSeed,
  showAll,
  onToggleShowAll,
}: {
  workspaceId: string;
  seeds: SeedEntity[];
  filters: GraphFiltersValue;
  onFiltersChange: (v: GraphFiltersValue) => void;
  onAddSeed: (s: SeedEntity) => void;
  onRemoveSeed: (id: string) => void;
  showAll: boolean;
  onToggleShowAll: () => void;
}) {
  return (
    <div className="flex flex-col gap-2 border-b bg-background px-4 py-3">
      <div className="flex items-center gap-2">
        <Network className="h-4 w-4 text-muted-foreground" />
        <h1 className="text-sm font-semibold">Knowledge graph</h1>
        <Separator orientation="vertical" className="mx-2 h-5" />
        <div className="min-w-0 flex-1">
          <SeedSearch
            workspaceId={workspaceId}
            seeds={seeds}
            onAdd={onAddSeed}
            onRemove={onRemoveSeed}
          />
        </div>
        <Button
          variant={showAll ? "default" : "outline"}
          size="sm"
          onClick={onToggleShowAll}
          className="shrink-0 gap-1.5"
          title={
            showAll
              ? "Switch back to seed-based traversal"
              : "Show every entity in this workspace (capped at 500)"
          }
        >
          {showAll ? (
            <>
              <XIcon className="h-3.5 w-3.5" /> Exit full graph
            </>
          ) : (
            <>
              <Globe className="h-3.5 w-3.5" /> Show whole graph
            </>
          )}
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm" className="md:hidden">
              <Filters className="h-3.5 w-3.5" /> Filters
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-md p-0">
            <DialogHeader className="p-4 pb-2">
              <DialogTitle>Graph filters</DialogTitle>
            </DialogHeader>
            <div className="max-h-[70vh] overflow-y-auto">
              <GraphFilters
                workspaceId={workspaceId}
                value={filters}
                onChange={onFiltersChange}
              />
            </div>
          </DialogContent>
        </Dialog>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>Max hops</span>
          <Select
            className="h-8 w-16 text-xs"
            value={filters.maxHops}
            onChange={(e) =>
              onFiltersChange({ ...filters, maxHops: Number(e.target.value) })
            }
          >
            {[1, 2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>
        </div>
      </div>
      <TimeSlider
        workspaceId={workspaceId}
        value={filters.asOf}
        onChange={(v) => onFiltersChange({ ...filters, asOf: v })}
        className="w-full"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Canvas region with empty/loading/error states
// ---------------------------------------------------------------------------

function GraphCanvas({
  workspaceId,
  seeds,
  showAll,
  payload,
  isLoading,
  isError,
  error,
  onRetry,
  selectedNode,
  onNodeClick,
  onCanvasClick,
  onAddSeed,
}: {
  workspaceId: string;
  seeds: SeedEntity[];
  showAll: boolean;
  payload: GraphPayload | undefined;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  onRetry: () => void;
  selectedNode: string | null;
  onNodeClick: (id: string) => void;
  onCanvasClick: () => void;
  onAddSeed: (s: SeedEntity) => void;
}) {
  // Whole-graph mode: no seeds required. Seed-based mode: prompt for one.
  if (!showAll && seeds.length === 0) {
    return <EmptyGraphState workspaceId={workspaceId} onAddSeed={onAddSeed} />;
  }

  if (isLoading) {
    return <SkeletonCanvas />;
  }

  if (isError) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <EmptyState
          icon={AlertTriangle}
          title="Failed to load graph"
          description={
            error instanceof Error
              ? error.message
              : "An unexpected error occurred while traversing the graph."
          }
          action={
            <Button size="sm" onClick={onRetry}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  if (!payload || payload.nodes.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <EmptyState
          icon={Network}
          title={
            showAll
              ? "No entities in this workspace yet"
              : "No connected entities"
          }
          description={
            showAll
              ? "Ingest content (Google Docs sync, agent writes, etc.) and refresh."
              : "The selected seeds have no edges matching the current filters. Try loosening filters or increasing max hops."
          }
        />
      </div>
    );
  }

  return (
    <div className="relative flex-1">
      <GraphView
        payload={payload}
        seeds={seeds.map((s) => s.id)}
        selectedNodeId={selectedNode}
        onNodeClick={onNodeClick}
        onCanvasClick={onCanvasClick}
        className="h-full w-full"
      />
      <GraphLegend payload={payload} />
      <StatsBar
        nodeCount={payload.nodes.length}
        edgeCount={payload.edges.length}
        truncated={payload.nodes.length >= MAX_NODES}
        cap={MAX_NODES}
      />
    </div>
  );
}
