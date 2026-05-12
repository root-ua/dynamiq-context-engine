import { cn } from "@/lib/utils";

/**
 * Brand wordmark for Dynamiq Context Engine.
 *
 * Uses `currentColor` for both the mark and the wordmark so it inherits
 * from its parent text color — that's how we get clean dark/light theme
 * switching without a separate image asset per theme.
 */
export function Logo({
  className,
  showWordmark = true,
  wordmark = "Dynamiq",
  subtitle,
}: {
  className?: string;
  showWordmark?: boolean;
  wordmark?: string;
  subtitle?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 font-semibold tracking-tight",
        className,
      )}
    >
      <LogoMark className="h-5 w-5" />
      {showWordmark ? (
        <span className="leading-none">
          <span className="text-[0.95em]">{wordmark}</span>
          {subtitle ? (
            <span className="ml-1.5 text-[0.82em] font-normal text-muted-foreground">
              {subtitle}
            </span>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}

export function LogoMark({ className }: { className?: string }) {
  // Rounded square containing a tight "D" formed from two bars — a minimal,
  // symbol-first mark that reads as "D" but also as a bracket/bar pair,
  // nodding to the bi-temporal + typed-graph theme.
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <rect
        x="1.5"
        y="1.5"
        width="21"
        height="21"
        rx="5.5"
        fill="currentColor"
      />
      <path
        d="M7 6.5h6.25c2.9 0 5.25 2.46 5.25 5.5s-2.35 5.5-5.25 5.5H7V6.5z"
        fill="none"
        stroke="var(--background, #ffffff)"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
    </svg>
  );
}
