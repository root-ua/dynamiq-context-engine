"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { connectorsApi } from "@/lib/api/endpoints";

// Force dynamic rendering — this page is meaningless to prerender
// because every visit comes from Google with unique ?code=...&state=...
// query params. Statically generating it confuses Next.js into trying
// to evaluate useSearchParams without a request scope.
export const dynamic = "force-dynamic";

/**
 * Lands here after Google OAuth consent. Pulls ?code=...&state=...
 * from the URL, looks up the workspace + connector instance from
 * sessionStorage (set by the "Add connector" flow), then POSTs to the
 * backend to exchange the code and kick off the initial crawl.
 *
 * The page is mounted at /connectors/oauth-callback (no workspace
 * prefix) because Google redirect URIs have to be whitelisted on the
 * OAuth client; one fixed path is easier to operate than per-workspace.
 */
function CallbackInner() {
  const params = useSearchParams();
  const router = useRouter();
  const code = params.get("code");
  const state = params.get("state");
  const oauthError = params.get("error");

  const [phase, setPhase] = React.useState<"working" | "done" | "error">(
    oauthError ? "error" : "working",
  );
  const [errorMsg, setErrorMsg] = React.useState<string>(oauthError ?? "");

  React.useEffect(() => {
    if (oauthError) return;
    if (!code || !state) {
      setPhase("error");
      setErrorMsg("Missing code or state in callback URL.");
      return;
    }

    const wsId = sessionStorage.getItem("connector_oauth_workspace_id");
    const wsSlug = sessionStorage.getItem("connector_oauth_workspace_slug");
    if (!wsId || !wsSlug) {
      setPhase("error");
      setErrorMsg(
        "Lost workspace context. Try installing the connector again from the same browser tab.",
      );
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        await connectorsApi.oauthCallback(wsId, state, { code, state });
        if (cancelled) return;
        setPhase("done");
        // Tidy up so a stale workspace doesn't leak into a future install.
        sessionStorage.removeItem("connector_oauth_workspace_id");
        sessionStorage.removeItem("connector_oauth_workspace_slug");
        sessionStorage.removeItem("connector_oauth_instance");
        router.replace(
          `/${wsSlug}/settings/integrations/connectors/${state}`,
        );
      } catch (e) {
        if (cancelled) return;
        setPhase("error");
        setErrorMsg(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code, state, oauthError, router]);

  return (
    <div className="mx-auto max-w-md p-8">
      <Card>
        <CardContent className="space-y-4 p-6">
          {phase === "working" && (
            <>
              <h1 className="text-lg font-semibold">Completing connection…</h1>
              <p className="text-sm text-muted-foreground">
                Exchanging the authorization code with the backend and
                scheduling the initial crawl. This usually takes a moment.
              </p>
            </>
          )}
          {phase === "done" && (
            <>
              <h1 className="text-lg font-semibold">Connected</h1>
              <p className="text-sm text-muted-foreground">
                Redirecting to the connector page…
              </p>
            </>
          )}
          {phase === "error" && (
            <>
              <h1 className="text-lg font-semibold">Connection failed</h1>
              <p className="text-sm text-muted-foreground">{errorMsg}</p>
              <Button variant="outline" onClick={() => router.push("/home")}>
                Back to home
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function ConnectorOAuthCallbackPage() {
  return (
    <React.Suspense
      fallback={
        <div className="mx-auto max-w-md p-8 text-sm text-muted-foreground">
          Loading…
        </div>
      }
    >
      <CallbackInner />
    </React.Suspense>
  );
}
