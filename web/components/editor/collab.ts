"use client";
import { HocuspocusProvider, WebSocketStatus } from "@hocuspocus/provider";
import type * as Y from "yjs";

import { getToken, invalidateTokenCache } from "@/lib/api/client";

const COLLAB_URL = process.env.NEXT_PUBLIC_COLLAB_URL || "ws://localhost:1234";

export type CollabStatus =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "offline";

export interface CreateCollabProviderOptions {
  documentId: string;
  ydoc: Y.Doc;
  onStatusChange?: (status: CollabStatus) => void;
  onSynced?: (provider: HocuspocusProvider) => void;
}

export interface CollabHandle {
  provider: HocuspocusProvider;
  destroy: () => void;
}

/**
 * Fetch a fresh JWT for the Hocuspocus handshake from the shared API client
 * cache. Returns `null` when unauthenticated so the provider surfaces an
 * auth error rather than connecting anonymously.
 */
async function fetchCollabToken(): Promise<string | null> {
  return getToken(null);
}

function mapStatus(
  status: WebSocketStatus,
  firstSynced: boolean,
): CollabStatus {
  if (status === WebSocketStatus.Connected)
    return firstSynced ? "connected" : "connecting";
  if (status === WebSocketStatus.Connecting) return "reconnecting";
  return "offline";
}

/**
 * Build a HocuspocusProvider bound to the given Y.Doc. The token is fetched
 * once up front and re-fetched whenever the server rejects the socket
 * (token rotation). The helper returns the provider plus a `destroy` that
 * tears down listeners and the socket cleanly.
 */
export function createCollabProvider(
  options: CreateCollabProviderOptions,
): CollabHandle {
  const { documentId, ydoc, onStatusChange, onSynced } = options;
  const docName = `doc:${documentId}`;

  let disposed = false;
  let firstSynced = false;
  let currentToken: string | null = null;
  // HocuspocusProvider fires an `onStatus` with "Connecting" synchronously
  // from its constructor. That happens during React's render pass when
  // the provider is built inside a `useMemo`, before the host component
  // has committed — so any setState it triggers warns "Can't perform a
  // React state update on a component that hasn't mounted yet."
  //
  // Suppressing the constructor-time callback is safe: the consumer's
  // initial state is already "connecting" (see Editor.tsx), and every
  // subsequent status change flows through normally.
  let suppressInitialStatus = true;

  const provider = new HocuspocusProvider({
    url: `${COLLAB_URL}/collab`,
    name: docName,
    document: ydoc,
    // Start in a "pending" state; we will connect once the token resolves.
    connect: false,
    token: async () => {
      currentToken = await fetchCollabToken();
      return currentToken ?? "";
    },
    onStatus: ({ status }) => {
      if (disposed) return;
      if (suppressInitialStatus) return;
      queueMicrotask(() => {
        if (disposed) return;
        onStatusChange?.(mapStatus(status, firstSynced));
      });
    },
    onSynced: () => {
      if (disposed) return;
      firstSynced = true;
      queueMicrotask(() => {
        if (disposed) return;
        onStatusChange?.("connected");
        onSynced?.(provider);
      });
    },
    onAuthenticationFailed: () => {
      if (disposed) return;
      // Likely token rotation: force a refetch and reconnect. Kick off
      // asynchronously — Hocuspocus ignores the return value of this hook.
      void (async () => {
        try {
          provider.disconnect();
        } catch {
          // ignore
        }
        invalidateTokenCache();
        await fetchCollabToken();
        if (!disposed) void provider.connect();
      })();
    },
    onDisconnect: () => {
      if (disposed) return;
      queueMicrotask(() => {
        if (disposed) return;
        onStatusChange?.("offline");
      });
    },
  });

  // Constructor has returned — future status callbacks are real and
  // should flow through to the host component.
  suppressInitialStatus = false;

  // Kick off the initial connection asynchronously so React's render pass
  // finishes before any network/socket side effect.
  queueMicrotask(() => {
    if (!disposed) void provider.connect();
  });

  return {
    provider,
    destroy: () => {
      if (disposed) return;
      disposed = true;
      try {
        provider.destroy();
      } catch {
        // ignore
      }
    },
  };
}
