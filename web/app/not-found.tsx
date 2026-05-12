import Link from "next/link";

import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";

// Skip prerender for the global 404 — Next.js 15's static export of the
// App-Router not-found page intermittently pulls in `next/document`
// internals from a chunked dependency, triggering a "Html should not be
// imported outside pages/_document" error. Forcing dynamic avoids the
// SSG path entirely; the page still renders correctly on real requests.
export const dynamic = "force-dynamic";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-6 text-center">
      <Logo className="text-base" subtitle="Context Engine" />
      <div className="space-y-2">
        <h1 className="text-5xl font-semibold tracking-tight">404</h1>
        <p className="text-muted-foreground">
          This page doesn't exist — or it moved.
        </p>
      </div>
      <div className="flex gap-2">
        <Button asChild>
          <Link href="/home">Back to workspace</Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href="/contact">Contact support</Link>
        </Button>
      </div>
    </main>
  );
}
