"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { PiMoon, PiSun, PiMonitor } from "react-icons/pi";

import { Button } from "@/components/ui/button";

type Theme = "light" | "dark" | "system";

const ORDER: Theme[] = ["system", "light", "dark"];

function labelFor(theme: Theme): string {
  if (theme === "light") return "Light";
  if (theme === "dark") return "Dark";
  return "System";
}

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => setMounted(true), []);

  const current = (mounted ? (theme as Theme) : "system") ?? "system";
  const Icon =
    current === "dark" ? PiMoon : current === "light" ? PiSun : PiMonitor;

  function cycle() {
    const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length]!;
    setTheme(next);
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={cycle}
      title={`Theme: ${labelFor(current)}`}
      aria-label="Toggle theme"
    >
      <Icon className="h-4 w-4" />
    </Button>
  );
}
