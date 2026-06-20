// Bundled demo data so views render without a backend session (DEV only — gated by
// import.meta.env.DEV at the call sites). Shown with a "Sample data" badge.
import type {
  AnalyticsDashboard, AdminUser, ApiEndpointStat, AuditLogEntry,
} from '@/api/types'

function lastDays(n: number, base: number, jitter: number) {
  const out: { date: string; v: number }[] = []
  const today = new Date('2026-06-20')
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(today.getDate() - i)
    out.push({ date: d.toISOString().slice(0, 10), v: Math.round(base + Math.sin(i) * jitter + (n - i) * 3) })
  }
  return out
}

export const SAMPLE_DASHBOARD: AnalyticsDashboard = {
  timestamp: '2026-06-20T12:00:00Z',
  summary: {
    total_users: 4218,
    active_users_7d: 1184,
    active_users_30d: 2671,
    total_picks: 38942,
    picks_7d: 1843,
    avg_picks_per_user: 9.2,
    total_games: 1276,
    total_reviews: 5310,
  },
  pick_trends_7d: lastDays(7, 220, 40).map((p) => ({ date: p.date, picks: p.v })),
  active_users_7d: lastDays(7, 160, 25).map((p) => ({ date: p.date, active_users: p.v })),
  top_games: [
    { game_id: '1', game_name: 'Elden Ring', pick_count: 1893 },
    { game_id: '2', game_name: 'Baldur’s Gate 3', pick_count: 1654 },
    { game_id: '3', game_name: 'Hades II', pick_count: 1207 },
    { game_id: '4', game_name: 'Stardew Valley', pick_count: 988 },
    { game_id: '5', game_name: 'Hollow Knight', pick_count: 742 },
  ],
  platform_stats: { PC: 2410, PlayStation: 940, Xbox: 612, Switch: 256 },
  engagement: {
    total_users: 4218,
    active_users_7d: 1184,
    engagement_rate: '28.1%',
    users_reviewed: 1320,
    users_picked: 2980,
  },
  review_stats: {
    total: 5310,
    average_rating: 4.2,
    distribution: { '5': 2480, '4': 1610, '3': 720, '2': 310, '1': 190 },
  },
}

export const SAMPLE_ADMIN_USERS: AdminUser[] = [
  { username: 'ada.lovelace', role: 'admin', roles: ['admin', 'user'], status: 'active', email: 'ada@example.com', created_at: '2025-01-12T09:00:00Z' },
  { username: 'grace.hopper', role: 'moderator', roles: ['moderator', 'user'], status: 'active', email: 'grace@example.com', created_at: '2025-02-03T11:30:00Z' },
  { username: 'alan.turing', role: 'user', roles: ['user'], status: 'active', email: 'alan@example.com', created_at: '2025-03-19T14:10:00Z' },
  { username: 'katherine.j', role: 'user', roles: ['user'], status: 'suspended', email: 'kj@example.com', created_at: '2025-04-22T08:45:00Z' },
  { username: 'linus.t', role: 'user', roles: ['user'], status: 'active', email: 'linus@example.com', created_at: '2025-05-01T17:20:00Z' },
  { username: 'margaret.h', role: 'moderator', roles: ['moderator', 'user'], status: 'active', email: 'margaret@example.com', created_at: '2025-05-30T10:05:00Z' },
  { username: 'dennis.r', role: 'user', roles: ['user'], status: 'suspended', email: 'dennis@example.com', created_at: '2025-06-08T13:00:00Z' },
  { username: 'barbara.l', role: 'user', roles: ['user'], status: 'active', email: 'barbara@example.com', created_at: '2025-06-15T16:40:00Z' },
]

export const SAMPLE_API_STATS: ApiEndpointStat[] = [
  { endpoint: 'GET /api/analytics/dashboard', calls: 18420, errors: 42, avg_ms: 86.4 },
  { endpoint: 'GET /api/games/search', calls: 14210, errors: 130, avg_ms: 142.1 },
  { endpoint: 'POST /api/picks', calls: 9810, errors: 12, avg_ms: 54.8 },
  { endpoint: 'GET /api/users/all', calls: 6740, errors: 310, avg_ms: 201.3 },
  { endpoint: 'GET /api/recommendations', calls: 5120, errors: 8, avg_ms: 233.7 },
  { endpoint: 'GET /api/auth/current', calls: 4980, errors: 4, avg_ms: 11.2 },
  { endpoint: 'GET /api/reviews', calls: 3210, errors: 26, avg_ms: 73.5 },
]

export const SAMPLE_AUDIT_LOGS: AuditLogEntry[] = [
  { timestamp: '2026-06-20T11:42:00Z', actor: 'ada.lovelace', action: 'user.suspend', target: 'dennis.r', detail: 'Spam reports threshold reached' },
  { timestamp: '2026-06-20T10:18:00Z', actor: 'grace.hopper', action: 'review.remove', target: 'review#8821', detail: 'Hate speech' },
  { timestamp: '2026-06-20T09:05:00Z', actor: 'ada.lovelace', action: 'role.grant', target: 'margaret.h', detail: 'Granted moderator' },
  { timestamp: '2026-06-19T22:31:00Z', actor: 'system', action: 'auth.login_failed', target: 'unknown', detail: '5 failed attempts from 10.0.0.42' },
  { timestamp: '2026-06-19T18:12:00Z', actor: 'margaret.h', action: 'report.resolve', target: 'report#114', detail: 'No action needed' },
  { timestamp: '2026-06-19T14:50:00Z', actor: 'ada.lovelace', action: 'user.suspend', target: 'katherine.j', detail: 'Manual review' },
]
