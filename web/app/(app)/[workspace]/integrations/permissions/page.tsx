"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  PiArrowLeft,
  PiCheckCircle,
  PiEyeSlash,
  PiGlobe,
  PiSpinnerGap,
  PiUser,
  PiUsersThree,
} from "react-icons/pi";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  permissionsApi,
  type PermissionAce,
  type PermissionEpisode,
  type PermissionMatrix,
  type PermissionMember,
} from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

export default function PermissionsPage() {
  const { workspace } = useWorkspace();
  const [onlyWithAcl, setOnlyWithAcl] = useState(true);

  const query = useQuery<PermissionMatrix>({
    queryKey: ["permissions", workspace?.id, onlyWithAcl],
    queryFn: () =>
      permissionsApi.list(workspace!.id, { onlyWithAcl, limit: 500 }),
    enabled: !!workspace?.id,
  });

  if (!workspace) return null;

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-8">
      <div className="flex items-start justify-between">
        <div>
          <Link
            href={`/${workspace.slug}/integrations`}
            className="mb-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <PiArrowLeft className="size-3" /> Back to Integrations
          </Link>
          <h1 className="text-xl font-semibold">Permissions inspector</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            For every ingested episode in this workspace, see the source-system
            ACL we captured at sync time and which workspace members would
            currently see it under that ACL. Useful for sanity-checking the
            Drive-permission filter before/after enforcement is on.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <Switch
            checked={!onlyWithAcl}
            onChange={(e) => setOnlyWithAcl(!e.target.checked)}
          />
          <span className="text-muted-foreground">
            Show episodes without ACL
          </span>
        </div>
      </div>

      {query.isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <PiSpinnerGap className="size-4 animate-spin" /> Loading…
        </div>
      )}
      {query.isError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm">
          {query.error?.message ?? "Failed to load permissions"}
        </div>
      )}

      {query.data && (
        <>
          <MembersPanel members={query.data.members} />
          <EpisodesTable
            episodes={query.data.episodes}
            members={query.data.members}
          />
        </>
      )}
    </div>
  );
}

function MembersPanel({ members }: { members: PermissionMember[] }) {
  return (
    <div className="rounded-lg border bg-card">
      <div className="border-b px-4 py-3">
        <div className="text-sm font-medium">
          Workspace members & connected identities
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {members.length} member{members.length === 1 ? "" : "s"}. A member
          must have at least one verified Google identity to see Drive-ACL
          episodes that aren't anyone-with-link.
        </div>
      </div>
      <div className="divide-y">
        {members.map((m) => (
          <div
            key={m.user_id}
            className="flex items-center gap-3 px-4 py-2.5 text-sm"
          >
            <PiUser className="size-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{m.user_email}</div>
              {m.google_emails.length > 0 ? (
                <div className="truncate text-xs text-muted-foreground">
                  {m.google_emails.join(", ")}
                </div>
              ) : (
                <div className="text-xs text-amber-600 dark:text-amber-400">
                  no connected Google account
                </div>
              )}
            </div>
            <Badge variant="outline" className="text-[10px]">
              {m.role}
            </Badge>
          </div>
        ))}
      </div>
    </div>
  );
}

function EpisodesTable({
  episodes,
  members,
}: {
  episodes: PermissionEpisode[];
  members: PermissionMember[];
}) {
  if (episodes.length === 0) {
    return (
      <div className="rounded-md border bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
        No episodes match the current filter.
      </div>
    );
  }
  const memberById: Record<string, PermissionMember> = Object.fromEntries(
    members.map((m) => [m.user_id, m]),
  );

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div>
          <div className="text-sm font-medium">Episodes & ACL</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {episodes.length} episode{episodes.length === 1 ? "" : "s"}
          </div>
        </div>
      </div>
      <div className="divide-y">
        {episodes.map((ep) => (
          <EpisodeRow
            key={ep.id}
            episode={ep}
            memberById={memberById}
            allMembers={members}
          />
        ))}
      </div>
    </div>
  );
}

function EpisodeRow({
  episode,
  memberById: _memberById,
  allMembers,
}: {
  episode: PermissionEpisode;
  memberById: Record<string, PermissionMember>;
  allMembers: PermissionMember[];
}) {
  const [expanded, setExpanded] = useState(false);
  const visibleCount = episode.visible_to_user_ids.length;
  const totalCount = allMembers.length;
  const hidden = totalCount - visibleCount;
  const hasAcl = episode.aces.length > 0;

  return (
    <div className="px-4 py-3 text-sm">
      <div
        className="flex cursor-pointer items-start gap-3"
        onClick={() => setExpanded((e) => !e)}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px]">
              {episode.source_kind}
            </Badge>
            {!hasAcl && (
              <Badge variant="secondary" className="text-[10px]">
                workspace-trust
              </Badge>
            )}
            <div className="text-xs text-muted-foreground">
              {episode.ingested_at?.slice(0, 19).replace("T", " ")}
            </div>
          </div>
          <div className="mt-1 truncate font-mono text-sm">
            {episode.source_ref || episode.id}
          </div>
          <div className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
            {episode.snippet}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-xs text-muted-foreground">visible to</div>
          <div className="text-sm font-medium">
            {visibleCount} / {totalCount}
          </div>
          {hidden > 0 && (
            <div className="text-[10px] text-amber-600 dark:text-amber-400">
              {hidden} hidden
            </div>
          )}
        </div>
      </div>

      {expanded && (
        <div className="ml-1 mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
          <div>
            <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
              Source ACL ({episode.aces.length})
            </div>
            {episode.aces.length === 0 ? (
              <div className="text-xs italic text-muted-foreground">
                No external ACL — falls under workspace-trust (all members see
                it).
              </div>
            ) : (
              <ul className="space-y-1">
                {episode.aces.map((a, i) => (
                  <AceRow key={i} ace={a} />
                ))}
              </ul>
            )}
          </div>
          <div>
            <div className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
              Visible to members
            </div>
            <ul className="space-y-1">
              {allMembers.map((m) => {
                const visible = episode.visible_to_user_ids.includes(m.user_id);
                return (
                  <li
                    key={m.user_id}
                    className="flex items-center gap-2 text-xs"
                  >
                    {visible ? (
                      <PiCheckCircle className="size-3.5 text-emerald-600 dark:text-emerald-400" />
                    ) : (
                      <PiEyeSlash className="size-3.5 text-muted-foreground" />
                    )}
                    <span className={visible ? "" : "text-muted-foreground"}>
                      {m.user_email}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

function AceRow({ ace }: { ace: PermissionAce }) {
  const Icon =
    ace.ace_kind === "anyone"
      ? PiGlobe
      : ace.ace_kind === "domain"
        ? PiUsersThree
        : ace.ace_kind === "group"
          ? PiUsersThree
          : PiUser;

  const label =
    ace.ace_kind === "anyone"
      ? "anyone with the link"
      : ace.ace_kind === "domain"
        ? `@${ace.domain}`
        : ace.email || "?";

  return (
    <li className="flex items-center gap-2 rounded-md border bg-background px-2 py-1.5 text-xs">
      <Icon className="size-3.5 text-muted-foreground" />
      <span className="font-medium">{label}</span>
      <Badge variant="outline" className="ml-auto text-[10px]">
        {ace.ace_kind}
      </Badge>
      <Badge variant="outline" className="text-[10px]">
        {ace.role}
      </Badge>
      {ace.provider !== "google_drive" && (
        <Badge variant="outline" className="text-[10px]">
          {ace.provider}
        </Badge>
      )}
    </li>
  );
}
