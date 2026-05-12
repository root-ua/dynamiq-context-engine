"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { PiBrain, PiCubeTransparent, PiPlugsConnected } from "react-icons/pi";

import { Footer } from "@/components/app-shell/Footer";
import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";
import { useSession } from "@/lib/auth-client";

export default function Landing() {
  const router = useRouter();
  const { data: session, isPending } = useSession();

  useEffect(() => {
    if (!isPending && session?.user) router.replace("/home");
  }, [session, isPending, router]);

  return (
    <div className="flex min-h-screen flex-col">
      {/* Top nav */}
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-5">
        <Logo className="text-base" subtitle="Context Engine" />
        <nav className="flex items-center gap-2">
          <Button variant="ghost" asChild>
            <Link href="/pricing">Pricing</Link>
          </Button>
          <Button variant="ghost" asChild>
            <Link href="/login">Sign in</Link>
          </Button>
          <Button asChild>
            <Link href="/signup">Get started</Link>
          </Button>
        </nav>
      </header>

      {/* Hero */}
      <section className="flex flex-1 flex-col">
        <div className="mx-auto w-full max-w-4xl px-6 pb-20 pt-16 text-center">
          <h1 className="text-balance text-5xl font-semibold leading-[1.05] tracking-tight sm:text-6xl">
            A memory layer your agents can actually use.
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">
            Edit like Notion. Reason like a database. One typed, bi-temporal
            knowledge graph shared between you and every agent you connect —
            served natively over MCP to Claude Code, Cursor, and Claude Desktop.
          </p>
          <div className="mt-8 flex justify-center gap-3">
            <Button size="lg" asChild>
              <Link href="/signup">Start free</Link>
            </Button>
            <Button size="lg" variant="outline" asChild>
              <Link href="/pricing">View pricing</Link>
            </Button>
          </div>
          <p className="mt-4 text-xs text-muted-foreground">
            Self-host free. Cloud trial — no credit card.
          </p>
        </div>

        {/* Feature cards */}
        <div className="mx-auto grid w-full max-w-5xl gap-4 px-6 pb-20 sm:grid-cols-3">
          <FeatureCard
            icon={<PiBrain className="h-5 w-5" />}
            title="Edit like Notion"
            body="Block-based docs with BlockNote. @-mention entities, embed files, backlinks. Humans don't fight the data model."
          />
          <FeatureCard
            icon={<PiCubeTransparent className="h-5 w-5" />}
            title="Reason like a database"
            body="Typed entities, typed edges, bi-temporal validity. Graphiti-style contradiction handling. Query via search or SQL."
          />
          <FeatureCard
            icon={<PiPlugsConnected className="h-5 w-5" />}
            title="MCP-native for agents"
            body="Long-lived tokens, WWW-Authenticate discovery, RFC 9728 Protected Resource Metadata. Claude Code + Cursor just work."
          />
        </div>

        {/* How it works */}
        <div className="mx-auto w-full max-w-4xl px-6 pb-24">
          <h2 className="text-center text-2xl font-semibold tracking-tight">
            How it works
          </h2>
          <ol className="mx-auto mt-6 grid max-w-3xl gap-4 sm:grid-cols-3">
            <Step
              n={1}
              title="Capture"
              body="Write notes. Ingest episodes (conversations, emails, transcripts). The extractor distills entities + facts."
            />
            <Step
              n={2}
              title="Shape"
              body="Typed ontology with JSON Schema validation. Subtypes via ltree. Workspace-scoped or standard."
            />
            <Step
              n={3}
              title="Share"
              body="One memory, many agents. Every MCP tool call lands in the same bi-temporal graph humans see."
            />
          </ol>
        </div>
      </section>

      <Footer />
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-lg border bg-card/60 p-5 text-left">
      <div className="flex h-9 w-9 items-center justify-center rounded-md bg-brand/10 text-brand">
        {icon}
      </div>
      <div className="mt-4 font-semibold tracking-tight">{title}</div>
      <p className="mt-1 text-sm text-muted-foreground">{body}</p>
    </div>
  );
}

function Step({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <div className="rounded-lg border bg-card/40 p-4 text-left">
      <div className="font-mono text-xs text-muted-foreground">0{n}</div>
      <div className="mt-1 font-semibold tracking-tight">{title}</div>
      <p className="mt-1 text-sm text-muted-foreground">{body}</p>
    </div>
  );
}
