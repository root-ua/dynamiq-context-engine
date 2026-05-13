"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { slugify } from "@/lib/utils-slug";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { workspacesApi } from "@/lib/api/endpoints";
import { useSession } from "@/lib/auth-client";
import { useWorkspace } from "@/lib/workspace-context";

type OntologyMode = "strict" | "flexible" | "auto";

const MODE_COPY: Record<OntologyMode, { title: string; description: string }> =
  {
    strict: {
      title: "Strict ontology",
      description:
        "Start from the built-in types and only allow additions through the ontology editor. Best when schemas are well-understood.",
    },
    flexible: {
      title: "Flexible ontology",
      description:
        "Extraction can extend the ontology as needed, but human review is encouraged. Good default.",
    },
    auto: {
      title: "Auto-detect ontology",
      description:
        "Let the extractor freely invent new entity and relation types from ingested content. Best for open-ended exploration.",
    },
  };

export default function OnboardingPage() {
  const router = useRouter();
  const { push } = useToast();
  const { data: session } = useSession();
  const { workspaces, refresh, setWorkspaceId } = useWorkspace();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [mode, setMode] = useState<OntologyMode>("flexible");
  const [loadDemo, setLoadDemo] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!session?.user && typeof window !== "undefined") {
      void router.replace("/login");
    }
  }, [session, router]);

  // If the user already has a workspace, bounce them to /home. They can
  // create additional workspaces via the switcher.
  useEffect(() => {
    if (session?.user && workspaces.length > 0) {
      void router.replace("/home");
    }
  }, [session, workspaces, router]);

  useEffect(() => {
    if (!slug && name) setSlug(slugify(name));
  }, [name, slug]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const ws = await workspacesApi.create({
        slug,
        name,
        ontology_mode: mode,
      });

      if (loadDemo) {
        try {
          const demoSlug = `demo-halcyon-${Math.random().toString(36).slice(2, 8)}`;
          const demo = await workspacesApi.create({
            slug: demoSlug,
            name: "Demo — Halcyon Labs",
            ontology_mode: "flexible",
          });
          await workspacesApi.seedDemo(demo.id);
          push({
            title: "Workspace ready, demo loaded",
            description:
              "Switch to 'Demo — Halcyon Labs' from the sidebar to explore.",
          });
        } catch (demoErr: unknown) {
          // Demo seeding is best-effort — don't block the user.
          push({
            title: "Demo workspace couldn't be created",
            description:
              demoErr instanceof Error ? demoErr.message : String(demoErr),
            variant: "destructive",
          });
        }
      } else {
        push({ title: "Workspace created" });
      }

      setWorkspaceId(ws.id);
      void refresh();
      void router.push("/home");
    } catch (err: unknown) {
      push({
        title: "Failed to create workspace",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  }

  // While redirect is in flight, render nothing to avoid a stutter.
  if (workspaces.length > 0) return null;

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-2xl">
        <CardHeader>
          <CardTitle>Create your first workspace</CardTitle>
          <CardDescription>
            A workspace holds your ontology, entities, documents, and agent
            memory.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="name">Workspace name</Label>
                <Input
                  id="name"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Acme Research"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="slug">URL slug</Label>
                <Input
                  id="slug"
                  required
                  pattern="[a-z0-9-]+"
                  value={slug}
                  onChange={(e) => setSlug(e.target.value.toLowerCase())}
                />
              </div>
            </div>

            <div className="space-y-3">
              <Label>Ontology mode</Label>
              <div className="grid gap-3 sm:grid-cols-3">
                {(Object.keys(MODE_COPY) as OntologyMode[]).map((m) => {
                  const active = mode === m;
                  return (
                    <button
                      type="button"
                      key={m}
                      onClick={() => setMode(m)}
                      aria-pressed={active}
                      className={
                        "relative rounded-lg border p-4 text-left transition-all " +
                        (active
                          ? "border-brand bg-brand/5 shadow-sm ring-1 ring-brand/40"
                          : "border-border bg-card hover:border-border hover:bg-accent/50")
                      }
                    >
                      {active && (
                        <span className="absolute inset-x-0 top-0 h-0.5 rounded-t-lg bg-brand" />
                      )}
                      <div className="text-sm font-semibold">
                        {MODE_COPY[m].title}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {MODE_COPY[m].description}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            <label className="flex cursor-pointer items-start gap-3 rounded-lg border bg-card/40 p-4">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 cursor-pointer"
                checked={loadDemo}
                onChange={(e) => setLoadDemo(e.target.checked)}
              />
              <span>
                <span className="block text-sm font-semibold">
                  Also create a demo workspace{" "}
                  <span className="text-xs font-normal text-muted-foreground">
                    (recommended)
                  </span>
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  A sandbox populated with realistic data (a fictional AI
                  startup — entities, docs with @-mentions, bi-temporal edges,
                  agent sessions) so you can explore every feature before adding
                  your own content. Appears alongside your workspace in the
                  switcher; delete anytime.
                </span>
              </span>
            </label>

            <Button type="submit" disabled={submitting}>
              {submitting ? "Creating…" : "Create workspace"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
