"use client";

import Link from "next/link";
import { PiCheckCircle, PiEyeSlash, PiPlugsConnected } from "react-icons/pi";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useWorkspace } from "@/lib/workspace-context";

/**
 * Integrations hub page.
 *
 * V1 lists one provider — Google Docs. Each tile is a `<Link>` into the
 * provider's own settings sub-page. Connection status is intentionally
 * not surfaced here yet; the user lands on the sub-page and sees state
 * inline.
 */
export default function IntegrationsHubPage() {
  const { workspace } = useWorkspace();
  if (!workspace) return null;

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-6 py-8">
      <div>
        <h1 className="text-xl font-semibold">Integrations</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect external sources so their content lands in this workspace as
          episodes — searchable and graphable like anything else you add.
        </p>
      </div>

      <Link
        href={`/${workspace.slug}/integrations/google-docs`}
        className="block"
      >
        <Card className="cursor-pointer transition-colors hover:bg-accent/30">
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-md bg-blue-50 dark:bg-blue-950">
                <PiPlugsConnected className="size-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div className="flex-1">
                <CardTitle className="text-base">Google Docs</CardTitle>
                <CardDescription>
                  Sync your Google Docs into this workspace's memory.
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-1 text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <PiCheckCircle className="size-3.5" /> Per-user OAuth — only docs
              you can read are pulled
            </div>
            <div className="flex items-center gap-1.5">
              <PiCheckCircle className="size-3.5" /> Pick folders or individual
              files
            </div>
            <div className="flex items-center gap-1.5">
              <PiCheckCircle className="size-3.5" /> Manual "Sync now" — re-runs
              skip unchanged docs
            </div>
          </CardContent>
        </Card>
      </Link>

      <Link
        href={`/${workspace.slug}/integrations/permissions`}
        className="block"
      >
        <Card className="cursor-pointer transition-colors hover:bg-accent/30">
          <CardHeader>
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-md bg-amber-50 dark:bg-amber-950">
                <PiEyeSlash className="size-5 text-amber-600 dark:text-amber-400" />
              </div>
              <div className="flex-1">
                <CardTitle className="text-base">
                  Permissions inspector
                </CardTitle>
                <CardDescription>
                  See the source-system ACL for every ingested episode and which
                  workspace members can see it. Owner/admin only.
                </CardDescription>
              </div>
            </div>
          </CardHeader>
        </Card>
      </Link>

      <Card className="bg-muted/20">
        <CardHeader>
          <CardTitle className="text-sm font-medium">More coming</CardTitle>
          <CardDescription>
            Slack, Notion, Gmail, and Drive folders shared with you (not just
            your My Drive) are on the roadmap. Each follows the same connect →
            pick → sync flow.
          </CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}
