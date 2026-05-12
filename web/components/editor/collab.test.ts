import { describe, expect, it, vi, afterEach } from "vitest";

const statusHandlers: Array<(e: { status: string }) => void> = [];
const syncHandlers: Array<() => void> = [];

vi.mock("@hocuspocus/provider", () => {
  class HocuspocusProvider {
    constructor(opts: {
      onStatus?: (e: { status: string }) => void;
      onSynced?: () => void;
    }) {
      if (opts.onStatus) statusHandlers.push(opts.onStatus);
      if (opts.onSynced) syncHandlers.push(opts.onSynced);
      // Fire the first onStatus synchronously from the constructor — this is
      // the real-world behavior that created our render-phase setState bug.
      opts.onStatus?.({ status: "connecting" });
    }
    connect() {}
    disconnect() {}
    destroy() {}
  }
  return {
    HocuspocusProvider,
    WebSocketStatus: {
      Connected: "connected",
      Connecting: "connecting",
      Disconnected: "disconnected",
    },
  };
});

vi.mock("@/lib/api/client", () => ({
  getToken: vi.fn(async () => "tok"),
  invalidateTokenCache: vi.fn(),
}));

import { createCollabProvider } from "./collab";

afterEach(() => {
  statusHandlers.length = 0;
  syncHandlers.length = 0;
});

describe("createCollabProvider", () => {
  it("suppresses the constructor-time onStatus so it can't setState mid-render", async () => {
    const onStatusChange = vi.fn();

    const handle = createCollabProvider({
      documentId: "doc-1",
      // Minimal stand-in; the collab helper never reads Y.Doc methods
      // before the provider connects.
      ydoc: {} as unknown as never,
      onStatusChange,
    });

    // The mock provider fires onStatus synchronously in its constructor.
    // The real bug was: that callback triggered setState during the host
    // component's render pass. Fix: swallow it entirely. The component
    // already initialises state to "connecting", so nothing is lost.
    expect(onStatusChange).not.toHaveBeenCalled();
    await Promise.resolve();
    expect(onStatusChange).not.toHaveBeenCalled();

    // Real status changes that arrive *after* construction flow through.
    statusHandlers.forEach((h) => h({ status: "connected" }));
    await Promise.resolve();
    expect(onStatusChange).toHaveBeenCalled();

    handle.destroy();
  });

  it("destroy() suppresses any later onStatus / onSynced events", async () => {
    const onStatusChange = vi.fn();

    const handle = createCollabProvider({
      documentId: "doc-1",
      ydoc: {} as unknown as never,
      onStatusChange,
    });

    handle.destroy();
    onStatusChange.mockClear();

    // Fire a new status event post-destroy.
    statusHandlers.forEach((h) => h({ status: "connecting" }));
    await Promise.resolve();
    expect(onStatusChange).not.toHaveBeenCalled();
  });
});
