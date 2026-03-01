'use strict';

/**
 * Unit tests for shared formatter utilities extracted from renderer.js
 *
 * These test the same logic used by renderer.js without requiring Electron.
 * Run with: npm test (from desktop-app/)
 */

// ─── Inline the formatter functions (same logic as renderer.js) ──────────────
// We duplicate them here rather than requiring renderer.js (which references DOM)
// to keep tests fast and Electron-free.

function formatPlaytime(minutes) {
  if (!minutes) { return '0h played'; }
  if (minutes < 60) { return `${minutes}m played`; }
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h}h ${m}m played` : `${h}h played`;
}

function formatRelativeTime(isoString) {
  if (!isoString) { return ''; }
  const diff = Date.now() - new Date(isoString).getTime();
  const sec  = Math.floor(diff / 1000);
  if (sec < 60)     { return 'just now'; }
  const min = Math.floor(sec / 60);
  if (min < 60)     { return `${min}m ago`; }
  const h = Math.floor(min / 60);
  if (h < 24)       { return `${h}h ago`; }
  const d = Math.floor(h / 24);
  if (d < 7)        { return `${d}d ago`; }
  const w = Math.floor(d / 7);
  if (w < 5)        { return `${w}w ago`; }
  return new Date(isoString).toLocaleDateString();
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('formatPlaytime', () => {
  test('0 minutes', () => expect(formatPlaytime(0)).toBe('0h played'));
  test('null/undefined treated as 0', () => {
    expect(formatPlaytime(null)).toBe('0h played');
    expect(formatPlaytime(undefined)).toBe('0h played');
  });
  test('minutes only (< 60)', () => {
    expect(formatPlaytime(30)).toBe('30m played');
    expect(formatPlaytime(1)).toBe('1m played');
    expect(formatPlaytime(59)).toBe('59m played');
  });
  test('exactly 60 minutes', () => expect(formatPlaytime(60)).toBe('1h played'));
  test('whole hours', () => {
    expect(formatPlaytime(120)).toBe('2h played');
    expect(formatPlaytime(600)).toBe('10h played');
  });
  test('hours and minutes', () => {
    expect(formatPlaytime(90)).toBe('1h 30m played');
    expect(formatPlaytime(61)).toBe('1h 1m played');
    expect(formatPlaytime(125)).toBe('2h 5m played');
  });
});

describe('formatRelativeTime', () => {
  const now = Date.now();

  test('null returns empty string', () => expect(formatRelativeTime(null)).toBe(''));
  test('undefined returns empty string', () => expect(formatRelativeTime(undefined)).toBe(''));

  test('< 60 s → just now', () => {
    expect(formatRelativeTime(new Date(now - 10_000).toISOString())).toBe('just now');
  });
  test('1-59 min → Xm ago', () => {
    expect(formatRelativeTime(new Date(now - 10 * 60_000).toISOString())).toBe('10m ago');
  });
  test('1-23 h → Xh ago', () => {
    expect(formatRelativeTime(new Date(now - 5 * 3600_000).toISOString())).toBe('5h ago');
  });
  test('1-6 d → Xd ago', () => {
    expect(formatRelativeTime(new Date(now - 3 * 86400_000).toISOString())).toBe('3d ago');
  });
  test('1-4 w → Xw ago', () => {
    expect(formatRelativeTime(new Date(now - 14 * 86400_000).toISOString())).toBe('2w ago');
  });
  test('≥ 5 w → date string', () => {
    const result = formatRelativeTime(new Date(now - 50 * 86400_000).toISOString());
    expect(result).not.toMatch(/ago/);
    expect(result.length).toBeGreaterThan(0);
  });
});
