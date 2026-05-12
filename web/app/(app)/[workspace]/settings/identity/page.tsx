"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PiGoogleLogo as GoogleLogo,
  PiTrash as Trash,
  PiUser as User,
} from "react-icons/pi";
import { format } from "date-fns";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import {
  identityApi,
  type ExternalIdentity,
} from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

export default function IdentityPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const wsSlug = workspace?.slug ?? "";
  const qc = useQueryClient();
  const { push } = useToast();

  const list = useQuery({
    queryKey: ["identity", wsId],
    queryFn: () => identityApi.list(wsId),
    enabled: !!wsId,
  });

  const startGoogle = useMutation({
    mutationFn: () => identityApi.googleAuthorizeUrl(wsId),
    onSuccess: ({ url }) => {
      try {
        sessionStorage.setItem("identity_oauth_workspace_id", wsId);
        sessionStorage.setItem("identity_oauth_workspace_slug", wsSlug);
      } catch {
        // private mode etc; the callback can still try the active workspace
      }
      window.location.href = url;
    },
    onError: (e: Error) =>
      push({
        title: "Could not start Google OAuth",
        description: e.message,
        variant: "destructive",
      }),
  });

  const disconnect = useMutation({
    mutationFn: (id: string) => identityApi.remove(wsId, id),
    onSuccess: () => {
      push({ title: "Identity removed" });
      void qc.invalidateQueries({ queryKey: ["identity", wsId] });
    },
    onError: (e: Error) =>
      push({
        title: "Disconnect failed",
        description: e.message,
        variant: "destructive",
      }),
  });

  const items = list.data ?? [];

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-semibold">Connected identities</h1>
        <p className="text-sm text-muted-foreground">
          Connect your accounts on the source systems your workspace ingests
          from. Without this link, facts derived from source documents are
          hidden — even if you have access in the source system itself.
        </p>
      </div>

      {list.isLoading && (
        <p className="text-sm text-muted-foreground">Loading…</p>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <GoogleLogo className="h-5 w-5" />
            Google
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {items
            .filter((i) => i.provider === "google")
            .map((i) => (
              <IdentityRow
                key={i.id}
                identity={i}
                onDisconnect={() => disconnect.mutate(i.id)}
              />
            ))}
          {items.filter((i) => i.provider === "google").length === 0 && (
            <p className="text-sm text-muted-foreground">
              No Google account connected.
            </p>
          )}
          <Button
            variant="outline"
            disabled={!wsId || startGoogle.isPending}
            onClick={() => startGoogle.mutate()}
          >
            <GoogleLogo className="h-4 w-4" />
            {items.some((i) => i.provider === "google")
              ? "Add another Google account"
              : "Connect Google"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function IdentityRow({
  identity,
  onDisconnect,
}: {
  identity: ExternalIdentity;
  onDisconnect: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border p-3">
      <div className="flex items-center gap-3 min-w-0">
        <User className="h-4 w-4 text-muted-foreground shrink-0" />
        <div className="min-w-0">
          <div className="font-medium truncate">
            {identity.external_email ?? identity.external_id}
          </div>
          <div className="text-xs text-muted-foreground">
            Connected {format(new Date(identity.created_at), "PP")}
          </div>
        </div>
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          if (
            window.confirm(
              "Remove this identity? Facts gated by it will be hidden again until you reconnect.",
            )
          ) {
            onDisconnect();
          }
        }}
      >
        <Trash className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
