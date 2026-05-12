"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Minimal shadcn-style toggle switch. Rail uses `bg-muted` when off and
 * our brand accent when on, so the state is unambiguous in both themes.
 * Thumb is always `bg-background` — keeps contrast against both rails.
 */
export const Switch = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, disabled, ...props }, ref) => (
  <label
    className={cn(
      "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center",
      disabled && "cursor-not-allowed opacity-50",
      className,
    )}
  >
    <input
      type="checkbox"
      ref={ref}
      disabled={disabled}
      className="peer sr-only"
      {...props}
    />
    <span
      className={cn(
        "absolute inset-0 rounded-full bg-muted transition-colors",
        "peer-checked:bg-brand",
        "peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-background",
      )}
    />
    <span className="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-background shadow-sm transition-transform peer-checked:translate-x-4" />
  </label>
));
Switch.displayName = "Switch";
