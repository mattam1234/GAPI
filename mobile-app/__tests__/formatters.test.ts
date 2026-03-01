/**
 * Unit tests for formatters.ts
 * Run with: npm test (from mobile-app/)
 */
import {formatPlaytime, formatRelativeTime} from '../src/utils/formatters';

describe('formatPlaytime', () => {
  test('zero minutes', () => {
    expect(formatPlaytime(0)).toBe('0h played');
  });

  test('null / undefined treated as 0', () => {
    expect(formatPlaytime(undefined)).toBe('0h played');
    expect(formatPlaytime(null)).toBe('0h played');
  });

  test('less than 60 minutes', () => {
    expect(formatPlaytime(45)).toBe('45m played');
    expect(formatPlaytime(1)).toBe('1m played');
    expect(formatPlaytime(59)).toBe('59m played');
  });

  test('exactly 60 minutes', () => {
    expect(formatPlaytime(60)).toBe('1h played');
  });

  test('whole hours', () => {
    expect(formatPlaytime(120)).toBe('2h played');
    expect(formatPlaytime(600)).toBe('10h played');
  });

  test('hours and minutes', () => {
    expect(formatPlaytime(90)).toBe('1h 30m played');
    expect(formatPlaytime(125)).toBe('2h 5m played');
    expect(formatPlaytime(61)).toBe('1h 1m played');
  });
});

describe('formatRelativeTime', () => {
  const now = Date.now();

  test('null/undefined returns empty string', () => {
    expect(formatRelativeTime(null)).toBe('');
    expect(formatRelativeTime(undefined)).toBe('');
  });

  test('less than 60 seconds → just now', () => {
    const iso = new Date(now - 30_000).toISOString();
    expect(formatRelativeTime(iso)).toBe('just now');
  });

  test('1-59 minutes → Xm ago', () => {
    const iso = new Date(now - 5 * 60_000).toISOString();
    expect(formatRelativeTime(iso)).toBe('5m ago');
  });

  test('1-23 hours → Xh ago', () => {
    const iso = new Date(now - 3 * 3600_000).toISOString();
    expect(formatRelativeTime(iso)).toBe('3h ago');
  });

  test('1-6 days → Xd ago', () => {
    const iso = new Date(now - 2 * 86400_000).toISOString();
    expect(formatRelativeTime(iso)).toBe('2d ago');
  });

  test('1-4 weeks → Xw ago', () => {
    const iso = new Date(now - 14 * 86400_000).toISOString();
    expect(formatRelativeTime(iso)).toBe('2w ago');
  });

  test('more than 4 weeks → date string', () => {
    const iso = new Date(now - 60 * 86400_000).toISOString();
    const result = formatRelativeTime(iso);
    // Should be a formatted date like "1/1/2025", not a relative string
    expect(result).not.toMatch(/ago/);
    expect(result.length).toBeGreaterThan(0);
  });
});
