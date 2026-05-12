"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { identityApi } from "@/lib/api/endpoints";

// Same reasoning as the connector OAuth callback: every visit has
// unique query params, so static prerendering is meaningless.
export const dynamic = "force-dynamic";

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
      setErrorMsg("Missing code or state.");
      return;
    }
    const wsId = sessionStorage.getItem("identity_oauth_workspace_id");
    const wsSlug = sessionStorage.getItem("identity_oauth_workspace_slug");
    if (!wsId || !wsSlug) {
      setPhase("error");
      setErrorMsg("Lost workspace context. Try reconnecting from settings.");
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        await identityApi.googleCallback(wsId, { code, state });
        if (cancelled) return;
        setPhase("done");
        sessionStorage.removeItem("identity_oauth_workspace_id");
        sessionStorage.removeItem("identity_oauth_workspace_slug");
        router.replace(`/${wsSlug}/settings/identity`);
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
              <h1 className="text-lg font-semibold">Connecting your Google account…</h1>
              <p className="text-sm text-muted-foreground">
                We&apos;re recording the link so the visibility filter can
                resolve you against source-document permissions.
              </p>
            </>
          )}
          {phase === "done" && (
            <>
              <h1 className="text-lg font-semibold">Connected</h1>
              <p className="text-sm text-muted-foreground">Redirecting…</p>
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

export default function IdentityGoogleCallbackPage() {
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
