"use client";
import * as React from "react";
import {
  PiCaretRight as ChevronRight,
  PiMagnifyingGlass as Search,
} from "react-icons/pi";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { EntityType } from "@/lib/api/types";

interface TypeHierarchyTreeProps {
  types: EntityType[];
  selectedSlug?: string | null;
  onSelect: (type: EntityType) => void;
}

interface TreeNode {
  segment: string;
  type: EntityType | null;
  children: TreeNode[];
}

export function TypeHierarchyTree({
  types,
  selectedSlug,
  onSelect,
}: TypeHierarchyTreeProps) {
  const [query, setQuery] = React.useState("");
  const filteredTypes = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return types;
    return types.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.slug.toLowerCase().includes(q) ||
        t.hierarchy.toLowerCase().includes(q),
    );
  }, [types, query]);

  const tree = React.useMemo(() => buildTree(filteredTypes), [filteredTypes]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter types..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-8"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {tree.length === 0 ? (
          <div className="py-10 text-center text-xs text-muted-foreground">
            No types match.
          </div>
        ) : (
          <ul className="space-y-0.5">
            {tree.map((node) => (
              <TreeRow
                key={node.segment}
                node={node}
                depth={0}
                selectedSlug={selectedSlug}
                onSelect={onSelect}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function TreeRow({
  node,
  depth,
  selectedSlug,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  selectedSlug?: string | null;
  onSelect: (type: EntityType) => void;
}) {
  const [open, setOpen] = React.useState(depth < 2);
  const isSelected = !!node.type && node.type.slug === selectedSlug;
  const hasChildren = node.children.length > 0;

  return (
    <li>
      <div
        className={cn(
          "group flex items-center gap-1 rounded-md px-1.5 py-1 text-sm transition-colors",
          isSelected ? "bg-accent text-accent-foreground" : "hover:bg-muted",
        )}
        style={{ paddingLeft: `${depth * 12 + 6}px` }}
      >
        <button
          type="button"
          aria-label={open ? "Collapse" : "Expand"}
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "inline-flex h-4 w-4 items-center justify-center text-muted-foreground transition-transform",
            !hasChildren && "invisible",
            open && "rotate-90",
          )}
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          onClick={() => node.type && onSelect(node.type)}
          disabled={!node.type}
        >
          <span className="truncate font-medium">
            {node.type?.name ?? node.segment}
          </span>
          {node.type?.system && (
            <Badge variant="outline" className="h-4 px-1 text-[10px]">
              system
            </Badge>
          )}
        </button>
      </div>
      {hasChildren && open && (
        <ul className="space-y-0.5">
          {node.children.map((child) => (
            <TreeRow
              key={child.segment}
              node={child}
              depth={depth + 1}
              selectedSlug={selectedSlug}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

function buildTree(types: EntityType[]): TreeNode[] {
  const sorted = [...types].sort((a, b) =>
    a.hierarchy.localeCompare(b.hierarchy),
  );
  const roots: TreeNode[] = [];
  const bySegment = new Map<string, TreeNode>();

  for (const t of sorted) {
    const segments = (t.hierarchy || t.slug).split(".").filter(Boolean);
    let parentList = roots;
    let pathSoFar = "";

    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i]!;
      pathSoFar = pathSoFar ? `${pathSoFar}.${seg}` : seg;
      let node = bySegment.get(pathSoFar);
      if (!node) {
        node = { segment: seg, type: null, children: [] };
        bySegment.set(pathSoFar, node);
        parentList.push(node);
      }
      if (i === segments.length - 1) {
        node.type = t;
      }
      parentList = node.children;
    }
  }

  const sortRec = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => a.segment.localeCompare(b.segment));
    nodes.forEach((n) => sortRec(n.children));
  };
  sortRec(roots);
  return roots;
}
