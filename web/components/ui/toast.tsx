"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

type Toast = {
  id: number;
  title: string;
  description?: string;
  variant?: "default" | "destructive";
};
type Ctx = { toasts: Toast[]; push: (t: Omit<Toast, "id">) => void };
const ToastContext = React.createContext<Ctx | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const push = React.useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, ...t }]);
    setTimeout(
      () => setToasts((prev) => prev.filter((x) => x.id !== id)),
      5000,
    );
  }, []);
  return (
    <ToastContext.Provider value={{ toasts, push }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "w-80 rounded-md border p-3 shadow-lg",
              t.variant === "destructive"
                ? "border-destructive/40 bg-destructive text-destructive-foreground"
                : "bg-background",
            )}
          >
            <div className="text-sm font-medium">{t.title}</div>
            {t.description && (
              <div className="text-xs text-muted-foreground">
                {t.description}
              </div>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = React.useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
