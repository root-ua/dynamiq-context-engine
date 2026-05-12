"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  PiPulse as Activity,
  PiCubeTransparent as Boxes,
  PiCalendarBlank as Calendar,
  PiFileText as FileText,
  PiGraph as Network,
  PiPlus as Plus,
  PiShapes as Shapes,
} from "react-icons/pi";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import {
  auditApi,
  documentsApi,
  entitiesApi,
  episodesApi,
} from "@/lib/api/endpoints";
import { formatDate, formatDateTime } from "@/lib/format";
import { useWorkspace } from "@/lib/workspace-context";

export default function WorkspaceHome() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";

  const docs = useQuery({
    queryKey: ["documents", wsId],
    queryFn: () => documentsApi.list(wsId),
    enabled: !!wsId,
  });
  const entities = useQuery({
    queryKey: ["entities", wsId, { type: null }],
    queryFn: () => entitiesApi.list(wsId, { limit: 8 }),
    enabled: !!wsId,
  });
  const episodes = useQuery({
    queryKey: ["episodes", wsId],
    queryFn: () => episodesApi.list(wsId),
    enabled: !!wsId,
  });
  const audit = useQuery({
    queryKey: ["audit", wsId],
    queryFn: () => auditApi.list(wsId, 15),
    enabled: !!wsId,
  });

  if (!workspace) return null;
  const base = `/${workspace.slug}`;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          {workspace.name}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Workspace overview. Shape your ontology, ingest episodes, and let
          agents remember.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          icon={FileText}
          label="Documents"
          value={docs.data?.length ?? "—"}
          href={`${base}/documents`}
        />
        <StatCard
          icon={Boxes}
          label="Entities"
          value={entities.data?.length ?? "—"}
          href={`${base}/entities`}
        />
        <StatCard
          icon={Calendar}
          label="Episodes"
          value={episodes.data?.length ?? "—"}
          href={`${base}/episodes`}
        />
        <StatCard
          icon={Network}
          label="Graph"
          value="Explore"
          href={`${base}/graph`}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Recent documents</CardTitle>
              <CardDescription>
                Notes and documents you can edit collaboratively.
              </CardDescription>
            </div>
            <Button asChild size="sm" variant="outline">
              <Link href={`${base}/documents`}>
                <Plus className="h-3.5 w-3.5" /> New
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            {docs.data && docs.data.length > 0 ? (
              <ul className="space-y-1">
                {docs.data.slice(0, 6).map((d) => (
                  <li key={d.id}>
                    <Link
                      className="flex items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-accent"
                      href={`${base}/documents/${d.id}`}
                    >
                      <span>{d.title || "Untitled"}</span>
                      <span className="text-xs text-muted-foreground">
                        {formatDate(d.updated_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={FileText}
                title="No documents yet"
                description="Create a note to start writing. Mention entities with @ to connect them to the graph."
                action={
                  <Button asChild size="sm">
                    <Link href={`${base}/documents`}>Create a note</Link>
                  </Button>
                }
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Ontology</CardTitle>
              <CardDescription>
                Shape the types and relations used across your memory.
              </CardDescription>
            </div>
            <Button asChild size="sm" variant="outline">
              <Link href={`${base}/ontology`}>
                <Shapes className="h-3.5 w-3.5" /> Open
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Your workspace ships with a small built-in ontology (Person,
              Organization, Project, Task, Meeting, Note, Document, Topic). Add
              your own types, or have an AI agent propose a domain-specific
              ontology from your notes.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Recent activity</CardTitle>
            <CardDescription>
              Every change — human and agent — is recorded.
            </CardDescription>
          </div>
          <Button asChild size="sm" variant="ghost">
            <Link href={`${base}/activity`}>
              <Activity className="h-3.5 w-3.5" /> All
            </Link>
          </Button>
        </CardHeader>
        <CardContent>
          {audit.data && audit.data.length > 0 ? (
            <ul className="divide-y text-sm">
              {audit.data.slice(0, 10).map((a) => (
                <li
                  key={a.id}
                  className="flex items-center justify-between py-2"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={
                        "rounded px-1.5 py-0.5 text-xs " +
                        (a.actor_kind === "agent"
                          ? "bg-violet-500/15 text-violet-700 dark:text-violet-300"
                          : a.actor_kind === "system"
                            ? "bg-muted text-muted-foreground"
                            : "bg-blue-500/15 text-blue-700 dark:text-blue-300")
                      }
                    >
                      {a.actor_kind}
                    </span>
                    <span className="font-mono text-xs">{a.action}</span>
                    <span className="text-xs text-muted-foreground">
                      on {a.target_kind}
                    </span>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {formatDateTime(a.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={Activity}
              title="No activity yet"
              description="Create a document or invite an agent to see the workspace timeline."
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  href,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-lg border bg-card p-3 shadow-xs transition-colors hover:bg-accent/50"
    >
      <div className="flex items-center gap-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="mt-1.5 text-2xl font-semibold tabular-nums">{value}</div>
    </Link>
  );
}
