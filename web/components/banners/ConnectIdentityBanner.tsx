"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { PiX as X, PiWarning as Warning } from "react-icons/pi";

import { connectorsApi, identityApi } from "@/lib/api/endpoints";
import { useWorkspace } from "@/lib/workspace-context";

/**
 * Surfaces a one-line nudge whenever the workspace has at least one
 * active connector but the current user has no external identity yet.
 *
 * Without an identity bridge, the per-source ACL filter excludes every
 * connector-derived fact for this user — they'd see an unexpectedly
 * empty graph. The banner explains why and links to /settings/identity.
 *
 * Dismissal is per-workspace and stored in localStorage. The banner
 * reappears on a different workspace or after a clear.
 */
export function ConnectIdentityBanner() {
  const { workspace } = useWorkspace();
  const wsId = workspace?.id ?? "";
  const wsSlug = workspace?.slug ?? "";

  const connectors = useQuery({
    queryKey: ["connectors", wsId],
    queryFn: () => connectorsApi.list(wsId),
    enabled: !!wsId,
  });
  const identities = useQuery({
    queryKey: ["identity", wsId],
    queryFn: () => identityApi.list(wsId),
    enabled: !!wsId,
  });

  const dismissedKey = `dismissed_identity_banner_${wsId}`;
  const [dismissed, setDismissed] = React.useState(false);

  React.useEffect(() => {
    if (!wsId) return;
    setDismissed(localStorage.getItem(dismissedKey) === "1");
  }, [wsId, dismissedKey]);

  const hasConnectors = (connectors.data ?? []).some(
    (c) => c.status === "active" || c.status === "authorizing",
  );
  const hasIdentity = (identities.data ?? []).length > 0;

  if (!wsId) return null;
  if (dismissed) return null;
  if (!hasConnectors) return null;
  if (hasIdentity) return null;

  return (
    <div className="border-b bg-amber-50 px-4 py-2 text-sm text-amber-900">
      <div className="mx-auto flex max-w-6xl items-center gap-3">
        <Warning className="h-4 w-4 shrink-0" />
        <p className="flex-1">
          Connect a Google account to see facts from your Drive documents.
          Without it, ACL-protected sources stay hidden.{" "}
          <Link
            href={`/${wsSlug}/settings/identity`}
            className="underline font-medium"
          >
            Connect now
          </Link>
        </p>
        <button
          type="button"
          aria-label="Dismiss"
          className="rounded p-1 hover:bg-amber-100"
          onClick={() => {
            localStorage.setItem(dismissedKey, "1");
            setDismissed(true);
          }}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
