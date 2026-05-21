"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, CardContent } from "@/components/ui/card";
import { googleDocsApi } from "@/lib/api/endpoints";
import type { GoogleDocSyncState, GoogleDocsSyncJob } from "@/lib/api/types";

interface SyncProgressProps {
  workspaceId: string;
  jobId: string;
  connectionId?: string;
  onDone?: (job: GoogleDocsSyncJob) => void;
}

/**
 * Polls /jobs/{id} until the job reaches a terminal state.
 *
 * Poll interval is short while the job is queued/running (750ms) so the
 * counters and progress bar feel alive. Stops polling on
 * completed / failed / cancelled. The parent component gets onDone fired
 * on terminal so it can refresh the per-doc list.
 *
 * When `connectionId` is provided, the component also polls the per-doc
 * list so it can surface "Currently processing: <title>" while syncing.
 */
export function SyncProgress({
  workspaceId,
  jobId,
  connectionId,
  onDone,
}: SyncProgressProps) {
  const { data } = useQuery({
    queryKey: ["gdocs-sync-job", jobId],
    queryFn: () => googleDocsApi.getJob(workspaceId, jobId),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const job = q.state.data?.data;
      if (!job) return 750;
      if (job.status === "queued" || job.status === "running") return 750;
      // Terminal — stop polling, fire callback once.
      if (onDone) onDone(job);
      return false;
    },
  });

  const job = data?.data;

  // Per-doc query (best-effort): used only to surface the currently-
  // processing title. We poll on the same cadence while the job is live
  // so the label tracks reality.
  const docsQuery = useQuery({
    queryKey: ["gdocs-docs", connectionId],
    queryFn: () => googleDocsApi.listDocs(workspaceId, connectionId ?? ""),
    enabled: !!connectionId,
    refetchInterval: () => {
      if (!job) return 1500;
      if (job.status === "queued" || job.status === "running") return 1500;
      return false;
    },
  });

  if (!job) return null;

  const total = job.total_docs;
  const done = job.processed_docs + job.failed_docs + job.skipped_docs;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const terminal =
    job.status === "completed" ||
    job.status === "failed" ||
    job.status === "cancelled";

  const headerLabel = terminal
    ? statusLabel(job.status)
    : job.status === "queued"
      ? "Queued — waiting for worker"
      : "Syncing";

  const eta = !terminal ? computeEta(job) : null;
  const currentDocTitle = !terminal
    ? pickCurrentDocTitle(docsQuery.data?.data)
    : null;

  return (
    <Card>
      <CardContent className="space-y-2 py-4">
        <div className="flex items-center justify-between">
          <div className="text-sm">
            <span className="font-medium">{headerLabel}</span>
            {total > 0 && (
              <span className="ml-2 text-muted-foreground">
                {done} of {total} docs
              </span>
            )}
            {eta && (
              <span className="ml-2 text-muted-foreground">
                · ~{eta} remaining
              </span>
            )}
          </div>
          <span className="text-xs text-muted-foreground">{pct}%</span>
        </div>

        <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted">
          {/* When the job is live but no docs have been processed yet,
              show an indeterminate sweep so the bar doesn't sit at 0%. */}
          {!terminal && done === 0 && (
            <div className="absolute inset-0 animate-pulse bg-blue-500/20" />
          )}
          <div
            className={`h-full transition-all duration-300 ${
              job.status === "failed" ? "bg-red-500" : "bg-blue-500"
            }`}
            style={{ width: `${Math.max(pct, terminal ? 0 : 2)}%` }}
          />
        </div>

        {currentDocTitle && (
          <div
            className="truncate text-xs text-muted-foreground"
            title={currentDocTitle}
          >
            Currently processing: {currentDocTitle}
          </div>
        )}

        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>✓ {job.processed_docs} processed</span>
          {job.skipped_docs > 0 && <span>↷ {job.skipped_docs} skipped</span>}
          {job.failed_docs > 0 && (
            <span className="text-red-600">✗ {job.failed_docs} failed</span>
          )}
        </div>

        {job.status === "completed" && (
          <div className="text-xs text-muted-foreground">
            Episodes created. Extraction is running in the background — facts
            usually take ~30–60 seconds to appear in search.
          </div>
        )}
        {job.status === "failed" && job.error && (
          <div className="text-xs text-red-600">Error: {job.error}</div>
        )}
      </CardContent>
    </Card>
  );
}

function statusLabel(s: GoogleDocsSyncJob["status"]): string {
  switch (s) {
    case "completed":
      return "Sync complete";
    case "failed":
      return "Sync failed";
    case "cancelled":
      return "Sync cancelled";
    case "queued":
      return "Queued";
    default:
      return "Syncing";
  }
}

/**
 * Rough remaining-time estimate. Only meaningful once we've actually
 * processed a couple of docs — otherwise the per-doc rate is dominated
 * by worker spin-up cost and would lie. Returns a short human string
 * like "30s" or "2 min", or null if we can't (or shouldn't) compute it.
 */
function computeEta(job: GoogleDocsSyncJob): string | null {
  if (job.processed_docs < 2) return null;
  if (!job.started_at) return null;
  const total = job.total_docs;
  const remaining =
    total - (job.processed_docs + job.failed_docs + job.skipped_docs);
  if (remaining <= 0) return null;
  const startedMs = Date.parse(job.started_at);
  if (Number.isNaN(startedMs)) return null;
  const elapsedSec = (Date.now() - startedMs) / 1000;
  if (elapsedSec <= 0) return null;
  const perDoc = elapsedSec / job.processed_docs;
  const remainingSec = Math.round(perDoc * remaining);
  if (remainingSec < 60) return `${Math.max(remainingSec, 5)}s`;
  const mins = Math.round(remainingSec / 60);
  return `${mins} min`;
}

/**
 * Best-guess "what's the worker on right now". Prefer an actively-
 * syncing doc; fall back to the most recently completed one so the
 * user sees activity rather than an empty line.
 */
function pickCurrentDocTitle(
  docs: GoogleDocSyncState[] | undefined,
): string | null {
  if (!docs || docs.length === 0) return null;
  const syncing = docs.find((d) => d.status === "syncing");
  if (syncing) return syncing.doc_title ?? syncing.google_doc_id;
  // Fall back to the most recently synced completed doc.
  const completed = docs
    .filter((d) => d.status === "completed" && d.last_synced_at)
    .sort((a, b) => {
      const ta = a.last_synced_at ? Date.parse(a.last_synced_at) : 0;
      const tb = b.last_synced_at ? Date.parse(b.last_synced_at) : 0;
      return tb - ta;
    })[0];
  if (completed) return completed.doc_title ?? completed.google_doc_id;
  return null;
}
