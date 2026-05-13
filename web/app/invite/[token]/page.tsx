"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { invitesApi } from "@/lib/api/endpoints";
import { useSession } from "@/lib/auth-client";
import { useWorkspace } from "@/lib/workspace-context";

export default function InviteAcceptPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const router = useRouter();
  const { data: session, isPending } = useSession();
  const { push } = useToast();
  const { setWorkspaceId, refresh } = useWorkspace();
  const [accepting, setAccepting] = useState(false);

  // Redirect unauthenticated users to signup, preserving the return-to.
  useEffect(() => {
    if (!isPending && !session?.user) {
      const next = encodeURIComponent(`/invite/${token}`);
      void router.replace(`/signup?next=${next}`);
    }
  }, [session, isPending, token, router]);

  const preview = useQuery({
    queryKey: ["invite-preview", token],
    queryFn: () => invitesApi.preview(token),
    enabled: !!session?.user && !!token,
    retry: false,
  });

  async function accept() {
    setAccepting(true);
    try {
      const { workspace_id } = await invitesApi.accept(token);
      void refresh();
      setWorkspaceId(workspace_id);
      push({
        title: `Welcome to ${preview.data?.workspace_name ?? "the workspace"}`,
      });
      void router.replace("/home");
    } catch (err) {
      push({
        title: "Couldn't accept invite",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setAccepting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="flex justify-center">
          <Logo className="text-base" subtitle="Context Engine" />
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Workspace invitation</CardTitle>
            <CardDescription>
              {preview.isLoading
                ? "Loading…"
                : preview.isError
                  ? "Invite not found, expired, or revoked."
                  : preview.data
                    ? `${preview.data.invited_by_name ?? preview.data.invited_by_email ?? "Someone"} invited you to join ${preview.data.workspace_name} as ${preview.data.role}.`
                    : null}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {preview.isError ? (
              <Button asChild variant="outline">
                <Link href="/home">Back</Link>
              </Button>
            ) : (
              <div className="flex gap-2">
                <Button onClick={accept} disabled={!preview.data || accepting}>
                  {accepting ? "Joining…" : "Accept invite"}
                </Button>
                <Button variant="outline" asChild>
                  <Link href="/home">Decline</Link>
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
