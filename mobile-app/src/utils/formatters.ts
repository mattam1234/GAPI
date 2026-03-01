/**
 * formatters.ts — shared display-formatting utilities.
 */

/** Format playtime (minutes) → "Xh Ym played" */
export function formatPlaytime(minutes: number | undefined | null): string {
  if (!minutes) {
    return '0h played';
  }
  if (minutes < 60) {
    return `${minutes}m played`;
  }
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h}h ${m}m played` : `${h}h played`;
}

/** Format an ISO timestamp → relative string "X minutes ago", etc. */
export function formatRelativeTime(isoString: string | undefined | null): string {
  if (!isoString) {
    return '';
  }
  const diff = Date.now() - new Date(isoString).getTime();
  const sec  = Math.floor(diff / 1000);
  if (sec < 60) {
    return 'just now';
  }
  const min = Math.floor(sec / 60);
  if (min < 60) {
    return `${min}m ago`;
  }
  const h = Math.floor(min / 60);
  if (h < 24) {
    return `${h}h ago`;
  }
  const d = Math.floor(h / 24);
  if (d < 7) {
    return `${d}d ago`;
  }
  const w = Math.floor(d / 7);
  if (w < 5) {
    return `${w}w ago`;
  }
  return new Date(isoString).toLocaleDateString();
}
