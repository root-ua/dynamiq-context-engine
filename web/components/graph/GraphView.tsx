"use client";

import * as React from "react";
import Sigma from "sigma";
import type Graph from "graphology";
import { MultiDirectedGraph } from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { useTheme } from "next-themes";

import type { GraphPayload } from "@/lib/api/types";
import { colorForType, type ThemeMode } from "./types";

interface GraphPalette {
  mode: ThemeMode;
  edgeDefault: string;
  edgeDim: string;
  seedBorder: string;
}

function paletteFor(mode: ThemeMode): GraphPalette {
  return mode === "dark"
    ? {
        mode,
        edgeDefault: "rgba(148,163,184,0.4)",
        edgeDim: "rgba(100,116,139,0.2)",
        seedBorder: "rgba(240,240,245,0.9)",
      }
    : {
        mode,
        edgeDefault: "rgba(100,116,139,0.55)",
        edgeDim: "rgba(148,163,184,0.2)",
        seedBorder: "rgba(15,23,42,0.85)",
      };
}

// ---------------------------------------------------------------------------
// ForceAtlas2 worker setup.
//
// graphology-layout-forceatlas2 ships a worker entry (`/worker`). Loading it
// eagerly at module scope lets us re-use the same class across mounts. If
// `Worker` is unavailable or the import fails (tests, SSR, locked-down
// environments) we fall back to a synchronous layout pass in `mountSigma`.
// ---------------------------------------------------------------------------

interface FA2WorkerInstance {
  start: () => void;
  stop: () => void;
  kill: () => void;
  isRunning: () => boolean;
}

type FA2WorkerCtor = new (
  graph: Graph,
  settings?: Record<string, unknown>,
) => FA2WorkerInstance;

let WorkerLayout: FA2WorkerCtor | null = null;
let workerLoadError: unknown = null;

async function loadWorkerLayout(): Promise<FA2WorkerCtor | null> {
  if (WorkerLayout || workerLoadError) return WorkerLayout;
  if (typeof window === "undefined" || typeof Worker === "undefined") {
    return null;
  }
  try {
    const mod = (await import("graphology-layout-forceatlas2/worker")) as
      | { default: FA2WorkerCtor }
      | FA2WorkerCtor;
    WorkerLayout =
      (mod as { default?: FA2WorkerCtor }).default ?? (mod as FA2WorkerCtor);
    return WorkerLayout;
  } catch (err) {
    workerLoadError = err;
    return null;
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface GraphViewProps {
  payload: GraphPayload;
  seeds: string[];
  selectedNodeId: string | null;
  onNodeClick: (nodeId: string) => void;
  onCanvasClick: () => void;
  className?: string;
}

const FA2_SETTINGS = {
  gravity: 1,
  scalingRatio: 10,
  slowDown: 10,
  adjustSizes: true,
  barnesHutOptimize: true,
  strongGravityMode: false,
  linLogMode: false,
};

// 40 iterations stabilises the layout visually for graphs up to ~200 nodes
// (our typical workspace scale) without the ~1s wall-clock of the previous
// 100-iteration run. If future workspaces push past that, expose a
// "Refine layout" button that runs another pass on demand.
const FA2_ITERATIONS = 40;

/**
 * Sigma + graphology + ForceAtlas2 canvas. Rebuilds its graph whenever the
 * payload identity changes; keeps a single long-lived Sigma instance across
 * renders for smooth re-layout.
 */
export function GraphView({
  payload,
  seeds,
  selectedNodeId,
  onNodeClick,
  onCanvasClick,
  className,
}: GraphViewProps) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const sigmaRef = React.useRef<Sigma | null>(null);
  const hoveredRef = React.useRef<string | null>(null);
  const seedsRef = React.useRef<Set<string>>(new Set(seeds));
  const selectedRef = React.useRef<string | null>(selectedNodeId);

  const { resolvedTheme } = useTheme();
  const themeMode: ThemeMode = resolvedTheme === "dark" ? "dark" : "light";
  const paletteRef = React.useRef<GraphPalette>(paletteFor(themeMode));
  React.useEffect(() => {
    paletteRef.current = paletteFor(themeMode);
    sigmaRef.current?.refresh();
  }, [themeMode]);

  // Keep mutable refs in sync so the Sigma reducers (registered once) always
  // read the latest selection/hover state without resubscribing.
  React.useEffect(() => {
    seedsRef.current = new Set(seeds);
    sigmaRef.current?.refresh();
  }, [seeds]);

  React.useEffect(() => {
    selectedRef.current = selectedNodeId;
    sigmaRef.current?.refresh();
  }, [selectedNodeId]);

  // --- Mount / unmount Sigma lifecycle ---------------------------------------
  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    let cancelled = false;
    let mountedGraph: Graph | null = null;
    let mountedSigma: Sigma | null = null;
    let mountedWorker: FA2WorkerInstance | null = null;
    let workerStopTimer: number | null = null;

    void (async () => {
      const graph = buildGraph(payload, seeds, paletteRef.current);
      mountedGraph = graph;

      const sigma = new Sigma(graph, el, {
        renderLabels: true,
        labelRenderedSizeThreshold: 6,
        defaultEdgeType: "arrow",
        minCameraRatio: 0.1,
        maxCameraRatio: 10,
        labelDensity: 0.7,
        labelGridCellSize: 60,
        labelFont: "Inter, system-ui, sans-serif",
        labelSize: 12,
        labelWeight: "500",
        nodeReducer: (node, data) => {
          const isSeed = seedsRef.current.has(node);
          const isSelected = selectedRef.current === node;
          const isHovered = hoveredRef.current === node;
          const size =
            (data.size as number) + (isSeed ? 2 : 0) + (isSelected ? 3 : 0);
          return {
            ...data,
            size,
            highlighted: isHovered || isSelected,
            zIndex: isSelected || isSeed ? 2 : 1,
            borderColor: isSeed ? paletteRef.current.seedBorder : undefined,
            forceLabel: isHovered || isSelected || isSeed,
          };
        },
        edgeReducer: (edge, data) => {
          const sel = selectedRef.current;
          if (!sel) return data;
          const [from, to] = graph.extremities(edge);
          const dim = from !== sel && to !== sel;
          return {
            ...data,
            color: dim ? paletteRef.current.edgeDim : (data.color as string),
            size: dim
              ? Math.max(0.6, ((data.size as number) ?? 1) * 0.6)
              : data.size,
          };
        },
      });
      mountedSigma = sigma;
      sigmaRef.current = sigma;

      sigma.on("clickNode", ({ node }) => onNodeClick(node));
      sigma.on("clickStage", () => onCanvasClick());
      sigma.on("enterNode", ({ node }) => {
        hoveredRef.current = node;
        sigma.refresh();
      });
      sigma.on("leaveNode", () => {
        hoveredRef.current = null;
        sigma.refresh();
      });

      // Run layout. Prefer worker; fall back to sync on failure.
      const WorkerCtor = await loadWorkerLayout();
      if (cancelled) return;

      if (WorkerCtor) {
        try {
          const worker = new WorkerCtor(graph, { settings: FA2_SETTINGS });
          mountedWorker = worker;
          worker.start();
          workerStopTimer = window.setTimeout(() => {
            try {
              worker.stop();
            } catch {
              /* worker may already be stopped */
            }
          }, 2500);
        } catch {
          forceAtlas2.assign(graph, {
            iterations: FA2_ITERATIONS,
            settings: FA2_SETTINGS,
          });
        }
      } else {
        forceAtlas2.assign(graph, {
          iterations: FA2_ITERATIONS,
          settings: FA2_SETTINGS,
        });
      }
    })();

    return () => {
      cancelled = true;
      if (workerStopTimer != null) window.clearTimeout(workerStopTimer);
      try {
        mountedWorker?.stop();
        mountedWorker?.kill();
      } catch {
        /* noop */
      }
      try {
        mountedSigma?.kill();
      } catch {
        /* noop */
      }
      sigmaRef.current = null;
      try {
        mountedGraph?.clear();
      } catch {
        /* noop */
      }
    };
    // Intentionally re-run only when payload identity changes — hot swapping
    // the Sigma instance on every prop tick would ruin layout continuity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload]);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{
        width: "100%",
        height: "100%",
        backgroundColor: "hsl(var(--background))",
        backgroundImage:
          "radial-gradient(circle at 50% 35%, hsl(var(--accent-brand) / 0.06), transparent 65%)",
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Graph construction
// ---------------------------------------------------------------------------

function buildGraph(
  payload: GraphPayload,
  seeds: string[],
  palette: GraphPalette,
): Graph {
  const graph = new MultiDirectedGraph();
  const seedSet = new Set(seeds);

  // Seed a circular initial layout — FA2 spreads from here, but Sigma also
  // draws the first frame before the worker has produced any positions.
  const n = payload.nodes.length || 1;
  payload.nodes.forEach((node, i) => {
    const angle = (i / n) * Math.PI * 2;
    const radius = 10 + (node.distance ?? 0) * 6;
    const isSeed = seedSet.has(node.id);
    graph.addNode(node.id, {
      label: node.canonical,
      x: Math.cos(angle) * radius + (isSeed ? 0 : 0.01 * i),
      y: Math.sin(angle) * radius,
      size: isSeed ? 10 : Math.max(4, 8 - (node.distance ?? 0)),
      color: colorForType(node.type || "unknown", palette.mode),
      nodeType: node.type,
      distance: node.distance,
      iri: node.iri,
    });
  });

  const dpr =
    typeof window !== "undefined"
      ? Math.min(window.devicePixelRatio || 1, 2)
      : 1;
  const edgeWidthScale = 1 + (dpr - 1) * 0.3;

  payload.edges.forEach((edge) => {
    if (!graph.hasNode(edge.subject_id) || !graph.hasNode(edge.object_id))
      return;
    const subjDist =
      (graph.getNodeAttribute(edge.subject_id, "distance") as number) ?? 0;
    const objDist =
      (graph.getNodeAttribute(edge.object_id, "distance") as number) ?? 0;
    const maxDist = Math.max(subjDist, objDist);
    const width = edgeWidthScale * (1 / (1 + maxDist * 0.6));
    graph.addEdgeWithKey(edge.id, edge.subject_id, edge.object_id, {
      label: edge.predicate,
      predicate: edge.predicate,
      size: Math.max(0.6, width * 2.5),
      color: palette.edgeDefault,
      fact: edge.fact,
      type: "arrow",
    });
  });

  return graph;
}
