"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import {
  PiArrowsClockwise,
  PiCaretDown,
  PiCaretRight,
  PiFile,
  PiFolder,
  PiFolderOpen,
} from "react-icons/pi";

import { googleDocsApi } from "@/lib/api/endpoints";
import type { DriveTreeNode } from "@/lib/api/types";

/**
 * Inline loader that names the folder being fetched and, after 4s,
 * appends a "Drive is slow today, still trying" hint. The name comes
 * from the parent row (or "your Drive" for the root) so the user knows
 * which fetch is in flight.
 */
function FolderLoader({ name }: { name: string }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), 4000);
    return () => clearTimeout(t);
  }, []);
  const label =
    name === "__root__"
      ? "Fetching your Drive…"
      : `Fetching "${name}" from Drive…`;
  return (
    <span>
      {label}
      {slow && " — Drive is slow today, still trying"}
    </span>
  );
}

interface SelectionItem {
  id: string;
  name: string;
}

interface SelectionState {
  folders: SelectionItem[];
  files: SelectionItem[];
}

interface GoogleDrivePickerProps {
  workspaceId: string;
  connectionId: string;
  initialSelection: SelectionState;
  onChange: (selection: SelectionState) => void;
}

/**
 * Lazy-loaded Drive folder tree with checkboxes.
 *
 * Each folder fetches its own children on first expand (separate React
 * Query call keyed by parent id). Selecting a folder == "ingest everything
 * under it"; selecting a file == "ingest just that doc". The two sets are
 * tracked separately and persisted via PUT /selection.
 */
export function GoogleDrivePicker({
  workspaceId,
  connectionId,
  initialSelection,
  onChange,
}: GoogleDrivePickerProps) {
  const queryClient = useQueryClient();
  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: ["gdrive-tree", connectionId],
    });
  }, [queryClient, connectionId]);
  const [folders, setFolders] = useState<Map<string, boolean>>(
    () => new Map(initialSelection.folders.map((f) => [f.id, true])),
  );
  const [files, setFiles] = useState<Map<string, boolean>>(
    () => new Map(initialSelection.files.map((f) => [f.id, true])),
  );
  const [folderNames, setFolderNames] = useState<Map<string, string>>(
    () => new Map(initialSelection.folders.map((f) => [f.id, f.name])),
  );
  const [fileNames, setFileNames] = useState<Map<string, string>>(
    () => new Map(initialSelection.files.map((f) => [f.id, f.name])),
  );

  // Push selection upward whenever anything toggles.
  const fireChange = useCallback(
    (
      newFolders: Map<string, boolean>,
      newFiles: Map<string, boolean>,
      foldersByName: Map<string, string>,
      filesByName: Map<string, string>,
    ) => {
      onChange({
        folders: Array.from(newFolders.entries())
          .filter(([, v]) => v)
          .map(([id]) => ({ id, name: foldersByName.get(id) ?? id })),
        files: Array.from(newFiles.entries())
          .filter(([, v]) => v)
          .map(([id]) => ({ id, name: filesByName.get(id) ?? id })),
      });
    },
    [onChange],
  );

  const toggleFolder = useCallback(
    (id: string, name: string) => {
      setFolderNames((m) => {
        const next = new Map(m);
        next.set(id, name);
        return next;
      });
      setFolders((m) => {
        const next = new Map(m);
        const isOn = next.get(id) ?? false;
        if (isOn) next.delete(id);
        else next.set(id, true);
        const newNames = new Map(folderNames);
        newNames.set(id, name);
        fireChange(next, files, newNames, fileNames);
        return next;
      });
    },
    [files, fileNames, folderNames, fireChange],
  );

  const toggleFile = useCallback(
    (id: string, name: string) => {
      setFileNames((m) => {
        const next = new Map(m);
        next.set(id, name);
        return next;
      });
      setFiles((m) => {
        const next = new Map(m);
        const isOn = next.get(id) ?? false;
        if (isOn) next.delete(id);
        else next.set(id, true);
        const newNames = new Map(fileNames);
        newNames.set(id, name);
        fireChange(folders, next, folderNames, newNames);
        return next;
      });
    },
    [folders, folderNames, fileNames, fireChange],
  );

  return (
    <div className="overflow-hidden rounded-md border bg-background">
      <div className="flex items-center justify-between border-b bg-muted/30 px-2 py-1">
        <span className="text-xs text-muted-foreground">
          Showing your Google Drive
        </span>
        <button
          type="button"
          onClick={refresh}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-accent/40 hover:text-foreground"
          title="Reload folder tree from Google Drive"
        >
          <PiArrowsClockwise className="size-3" />
          Refresh
        </button>
      </div>
      <div className="max-h-[420px] overflow-auto">
        <FolderNode
          parentId="root"
          depth={0}
          workspaceId={workspaceId}
          connectionId={connectionId}
          folders={folders}
          files={files}
          onToggleFolder={toggleFolder}
          onToggleFile={toggleFile}
          rootName="My Drive"
          ancestorSelected={false}
        />
      </div>
    </div>
  );
}

interface FolderNodeProps {
  parentId: string;
  depth: number;
  workspaceId: string;
  connectionId: string;
  folders: Map<string, boolean>;
  files: Map<string, boolean>;
  onToggleFolder: (id: string, name: string) => void;
  onToggleFile: (id: string, name: string) => void;
  rootName?: string;
  /** True iff any ancestor folder is selected. Children of selected folders
   *  are auto-included by the sync worker; we mirror that visually with a
   *  checked-but-disabled checkbox and a "via parent" hint. */
  ancestorSelected: boolean;
}

function FolderNode({
  parentId,
  depth,
  workspaceId,
  connectionId,
  folders,
  files,
  onToggleFolder,
  onToggleFile,
  rootName,
  ancestorSelected,
}: FolderNodeProps) {
  const [expanded, setExpanded] = useState(parentId === "root");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["gdrive-tree", connectionId, parentId],
    queryFn: () => googleDocsApi.tree(workspaceId, connectionId, parentId),
    enabled: expanded,
    staleTime: 30_000,
  });

  return (
    <div>
      {parentId !== "root" && null}
      {parentId === "root" && (
        <div
          className="flex cursor-pointer items-center gap-1 px-2 py-1 hover:bg-accent/30"
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? (
            <PiCaretDown className="size-3 text-muted-foreground" />
          ) : (
            <PiCaretRight className="size-3 text-muted-foreground" />
          )}
          <PiFolderOpen className="size-4 text-blue-500" />
          <span className="text-sm font-medium">{rootName ?? "Root"}</span>
        </div>
      )}

      {expanded && (
        <div style={{ paddingLeft: `${depth === 0 ? 0 : 16}px` }}>
          {isLoading && (
            <div className="px-3 py-1 text-xs text-muted-foreground">
              <FolderLoader name="__root__" />
            </div>
          )}
          {isError && (
            <div className="px-3 py-1 text-xs text-red-600">Failed to load</div>
          )}
          {data?.children?.map((node) => (
            <Row
              key={node.id}
              node={node}
              depth={depth + 1}
              workspaceId={workspaceId}
              connectionId={connectionId}
              folders={folders}
              files={files}
              onToggleFolder={onToggleFolder}
              onToggleFile={onToggleFile}
              ancestorSelected={ancestorSelected}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface RowProps {
  node: DriveTreeNode;
  depth: number;
  workspaceId: string;
  connectionId: string;
  folders: Map<string, boolean>;
  files: Map<string, boolean>;
  onToggleFolder: (id: string, name: string) => void;
  onToggleFile: (id: string, name: string) => void;
  /** True iff any ancestor folder is checked. */
  ancestorSelected: boolean;
}

function Row({
  node,
  depth,
  workspaceId,
  connectionId,
  folders,
  files,
  onToggleFolder,
  onToggleFile,
  ancestorSelected,
}: RowProps) {
  const [expanded, setExpanded] = useState(false);

  if (node.is_folder) {
    const ownChecked = folders.get(node.id) ?? false;
    const effectiveChecked = ownChecked || ancestorSelected;
    return (
      <div>
        <div
          className={`flex items-center gap-1 px-2 py-1 hover:bg-accent/30 ${
            ancestorSelected ? "opacity-60" : ""
          }`}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            className="hover:text-foreground"
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? (
              <PiCaretDown className="size-3 text-muted-foreground" />
            ) : (
              <PiCaretRight className="size-3 text-muted-foreground" />
            )}
          </button>
          <input
            type="checkbox"
            className="size-3.5"
            checked={effectiveChecked}
            disabled={ancestorSelected}
            onChange={() => onToggleFolder(node.id, node.name)}
            aria-label={`Select folder ${node.name}`}
            title={
              ancestorSelected
                ? "Included via parent folder — uncheck the parent to deselect"
                : `Select folder ${node.name}`
            }
          />
          {expanded ? (
            <PiFolderOpen className="size-4 text-blue-500" />
          ) : (
            <PiFolder className="size-4 text-blue-500" />
          )}
          <span className="truncate text-sm" title={node.name}>
            {node.name}
          </span>
          {ancestorSelected && (
            <span className="ml-1 text-[10px] italic text-muted-foreground">
              via parent
            </span>
          )}
        </div>
        {expanded && (
          <FolderChildren
            parentId={node.id}
            parentName={node.name}
            depth={depth}
            workspaceId={workspaceId}
            connectionId={connectionId}
            folders={folders}
            files={files}
            onToggleFolder={onToggleFolder}
            onToggleFile={onToggleFile}
            ancestorSelected={ancestorSelected || ownChecked}
          />
        )}
      </div>
    );
  }

  // It's a Google Doc leaf.
  const ownChecked = files.get(node.id) ?? false;
  const effectiveChecked = ownChecked || ancestorSelected;
  return (
    <div
      className={`flex items-center gap-1 px-2 py-1 hover:bg-accent/30 ${
        ancestorSelected ? "opacity-60" : ""
      }`}
      style={{ paddingLeft: `${depth * 16 + 24}px` }}
    >
      <input
        type="checkbox"
        className="size-3.5"
        checked={effectiveChecked}
        disabled={ancestorSelected}
        onChange={() => onToggleFile(node.id, node.name)}
        aria-label={`Select file ${node.name}`}
        title={
          ancestorSelected
            ? "Included via parent folder — uncheck the parent to deselect"
            : `Select file ${node.name}`
        }
      />
      <PiFile className="size-4 text-muted-foreground" />
      <span className="truncate text-sm" title={node.name}>
        {node.name}
      </span>
      {ancestorSelected && (
        <span className="ml-1 text-[10px] italic text-muted-foreground">
          via parent
        </span>
      )}
    </div>
  );
}

interface FolderChildrenProps extends Omit<RowProps, "node"> {
  parentId: string;
  parentName: string;
}

function FolderChildren({
  parentId,
  parentName,
  depth,
  workspaceId,
  connectionId,
  folders,
  files,
  onToggleFolder,
  onToggleFile,
  ancestorSelected,
}: FolderChildrenProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["gdrive-tree", connectionId, parentId],
    queryFn: () => googleDocsApi.tree(workspaceId, connectionId, parentId),
    staleTime: 30_000,
  });
  return (
    <div>
      {isLoading && (
        <div
          className="px-3 py-1 text-xs text-muted-foreground"
          style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
        >
          <FolderLoader name={parentName} />
        </div>
      )}
      {isError && (
        <div
          className="px-3 py-1 text-xs text-red-600"
          style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
        >
          Failed to load
        </div>
      )}
      {data?.children?.map((c) => (
        <Row
          key={c.id}
          node={c}
          depth={depth + 1}
          workspaceId={workspaceId}
          connectionId={connectionId}
          folders={folders}
          files={files}
          onToggleFolder={onToggleFolder}
          onToggleFile={onToggleFile}
          ancestorSelected={ancestorSelected}
        />
      ))}
    </div>
  );
}
