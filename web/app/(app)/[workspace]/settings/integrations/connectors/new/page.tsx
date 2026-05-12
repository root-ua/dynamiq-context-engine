"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { PiGoogleLogo as GoogleLogo } from "react-icons/pi";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { connectorsApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

const KINDS = [
  {
    kind: "google_drive",
    name: "Google Drive",
    description:
      "Crawl Docs, Sheets, Slides, and PDFs you have access to. Each fact extracted inherits the file's per-user permissions.",
    icon: GoogleLogo,
  },
];

export default function NewConnectorPage() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const router = useRouter();
  const { push } = useToast();

  const [selected, setSelected] = React.useState<string>("google_drive");
  const [name, setName] = React.useState("Google Drive");

  const create = useMutation({
    mutationFn: () =>
      connectorsApi.create(wsId, {
        kind: selected,
        display_name: name.trim() || "Google Drive",
      }),
    onSuccess: (resp) => {
      // Persist workspace + instance ids so the OAuth callback page
      // (which lives at /connectors/oauth-callback, outside the
      // workspace prefix) can re-scope the API call. The callback URL
      // itself only carries `code` and `state`.
      try {
        sessionStorage.setItem("connector_oauth_workspace_id", wsId);
        sessionStorage.setItem(
          "connector_oauth_workspace_slug",
          workspace?.slug ?? "",
        );
        sessionStorage.setItem(
          "connector_oauth_instance",
          resp.instance.id,
        );
      } catch {
        // Storage unavailable (private mode etc); the callback will
        // surface a "lost workspace context" error.
      }
      window.location.href = resp.authorize_url;
    },
    onError: (e: Error) =>
      push({
        title: "Could not start OAuth",
        description: e.message,
        variant: "destructive",
      }),
  });

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-semibold">Add a connector</h1>
        <p className="text-sm text-muted-foreground">
          Pick a source, complete its OAuth flow, and the worker starts
          ingesting documents on your behalf.
        </p>
      </div>

      <div className="space-y-3">
        {KINDS.map((k) => {
          const Icon = k.icon;
          const isSelected = selected === k.kind;
          return (
            <Card
              key={k.kind}
              className={`cursor-pointer transition-colors ${
                isSelected ? "ring-2 ring-primary" : "hover:bg-accent"
              }`}
              onClick={() => setSelected(k.kind)}
            >
              <CardContent className="flex items-start gap-4 p-4">
                <Icon className="h-6 w-6 text-muted-foreground" />
                <div className="space-y-1">
                  <div className="font-medium">{k.name}</div>
                  <div className="text-sm text-muted-foreground">
                    {k.description}
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="space-y-2">
        <Label htmlFor="display-name">Display name</Label>
        <Input
          id="display-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Google Drive"
        />
      </div>

      <div className="flex gap-2">
        <Button
          variant="outline"
          onClick={() => router.back()}
          disabled={create.isPending}
        >
          Cancel
        </Button>
        <Button
          onClick={() => create.mutate()}
          disabled={!wsId || create.isPending}
        >
          {create.isPending ? "Starting…" : "Continue with OAuth"}
        </Button>
      </div>
    </div>
  );
}
