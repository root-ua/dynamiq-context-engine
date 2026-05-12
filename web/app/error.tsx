"use client";

import Link from "next/link";
import { useEffect } from "react";

import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";

/**
 * Global error boundary. Next.js renders this when a Server Component
 * or route handler throws. Captured errors should flow to Sentry via
 * the instrumentation hook — logging here is belt-and-suspenders.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("app.error.boundary", error);
  }, [error]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-6 text-center">
      <Logo className="text-base" subtitle="Context Engine" />
      <div className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">
          Something went wrong
        </h1>
        <p className="text-muted-foreground">
          The page ran into an error. We've logged it and will investigate.
        </p>
        {error.digest ? (
          <p className="font-mono text-xs text-muted-foreground">
            Ref: {error.digest}
          </p>
        ) : null}
      </div>
      <div className="flex gap-2">
        <Button onClick={() => reset()}>Try again</Button>
        <Button variant="outline" asChild>
          <Link href="/home">Back to workspace</Link>
        </Button>
        <Button variant="ghost" asChild>
          <Link href="/contact">Contact support</Link>
        </Button>
      </div>
    </main>
  );
}
