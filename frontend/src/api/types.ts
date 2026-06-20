// Hand-mirrored from backend/schemas/analytics.py. Once the SPA can reach a
// running backend, `npm run gen:api` regenerates exact types from /openapi.json
// into schema.d.ts; these stay as the curated, hand-friendly view.

export interface DashboardSummary {
  total_users: number
  active_users_7d: number
  active_users_30d: number
  total_picks: number
  picks_7d: number
  avg_picks_per_user: number
  total_games: number
  total_reviews: number
}

export interface PickTrendPoint { date: string; picks: number }
export interface ActiveUsersPoint { date: string; active_users: number }
export interface TopGame { game_id: string | null; game_name: string | null; pick_count: number }
export interface EngagementMetrics {
  total_users: number
  active_users_7d: number
  engagement_rate: string
  users_reviewed: number
  users_picked: number
}
export interface ReviewStats { total: number; average_rating: number; distribution: Record<string, number> }

export interface AnalyticsDashboard {
  timestamp: string
  summary: DashboardSummary
  pick_trends_7d: PickTrendPoint[]
  active_users_7d: ActiveUsersPoint[]
  top_games: TopGame[]
  platform_stats: Record<string, number>
  engagement: EngagementMetrics
  review_stats: ReviewStats
}

// ── Auth / profile ──────────────────────────────────────────────────────────
export interface CurrentUser {
  username: string | null
  role?: string | null
  roles?: string[]
}

export interface UserProfile {
  username: string
  email?: string | null
  role?: string | null
  roles?: string[]
  created_at?: string | null
  bio?: string | null
  pick_count?: number | null
  review_count?: number | null
  reputation?: number | null
  [key: string]: unknown
}

// ── Admin ───────────────────────────────────────────────────────────────────
export interface AdminUser {
  username: string
  role?: string | null
  roles?: string[]
  status?: string | null
  email?: string | null
  created_at?: string | null
}

export interface AdminUserSearchResponse {
  users: AdminUser[]
  count: number
}

export interface ApiEndpointStat {
  endpoint: string
  calls: number
  errors: number
  avg_ms: number
  [key: string]: unknown
}

export interface ApiStatsResponse {
  stats: ApiEndpointStat[]
  endpoint_count: number
}

export interface AuditLogEntry {
  timestamp?: string | null
  actor?: string | null
  action?: string | null
  target?: string | null
  detail?: string | null
  [key: string]: unknown
}
