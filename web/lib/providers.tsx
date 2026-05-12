"use client";
import * as React from "react";
import {
  QueryClient,
  QueryClientProvider,
  type QueryClientConfig,
} from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";

import { ToastProvider } from "@/components/ui/toast";
import { WorkspaceProvider } from "@/lib/workspace-context";

const config: QueryClientConfig = {
  defaultOptions: {
    queries: {
      // 1 minute — lists and detail views don't refetch on remount
      // during normal navigation. Mutations explicitly invalidate the
      // keys they affect, so stale data doesn't linger after user edits.
      // Polling queries (episodes, agent sessions) opt into shorter
      // refetchInterval per-call and are unaffected.
      staleTime: 60_000,
      // Keep data around for 5 min even after all observers unmount, so
      // navigating away-and-back within that window is cache-hit fast.
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
};

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(() => new QueryClient(config));
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      <QueryClientProvider client={client}>
        <ToastProvider>
          <WorkspaceProvider>{children}</WorkspaceProvider>
        </ToastProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
