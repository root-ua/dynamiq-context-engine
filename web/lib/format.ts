/**
 * Date/time formatting helpers. Use these everywhere instead of
 * inline `toLocaleString` / `toLocaleDateString` so the UI stays
 * visually consistent across pages.
 *
 * The product is English-only for now; the Intl API uses the browser's
 * locale when available and falls back to `en-US`.
 */

const LOCALE = typeof navigator !== "undefined" ? navigator.language : "en-US";

const DATE_TIME_FMT = new Intl.DateTimeFormat(LOCALE, {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const DATE_FMT = new Intl.DateTimeFormat(LOCALE, {
  year: "numeric",
  month: "short",
  day: "numeric",
});

const RELATIVE_FMT = new Intl.RelativeTimeFormat(LOCALE, {
  numeric: "auto",
});

function coerce(d: Date | string | number | null | undefined): Date | null {
  if (d == null) return null;
  const parsed = d instanceof Date ? d : new Date(d);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatDateTime(
  d: Date | string | number | null | undefined,
  fallback = "",
): string {
  const parsed = coerce(d);
  return parsed ? DATE_TIME_FMT.format(parsed) : fallback;
}

export function formatDate(
  d: Date | string | number | null | undefined,
  fallback = "",
): string {
  const parsed = coerce(d);
  return parsed ? DATE_FMT.format(parsed) : fallback;
}

export function formatRelative(
  d: Date | string | number | null | undefined,
  fallback = "",
): string {
  const parsed = coerce(d);
  if (!parsed) return fallback;
  const diffMs = parsed.getTime() - Date.now();
  const absSec = Math.abs(diffMs) / 1000;
  if (absSec < 60)
    return RELATIVE_FMT.format(Math.round(diffMs / 1000), "second");
  if (absSec < 3600)
    return RELATIVE_FMT.format(Math.round(diffMs / 60_000), "minute");
  if (absSec < 86_400)
    return RELATIVE_FMT.format(Math.round(diffMs / 3_600_000), "hour");
  if (absSec < 86_400 * 30)
    return RELATIVE_FMT.format(Math.round(diffMs / 86_400_000), "day");
  if (absSec < 86_400 * 365)
    return RELATIVE_FMT.format(Math.round(diffMs / (86_400_000 * 30)), "month");
  return RELATIVE_FMT.format(Math.round(diffMs / (86_400_000 * 365)), "year");
}
