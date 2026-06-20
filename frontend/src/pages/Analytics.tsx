import { useMemo } from 'react'
import { api } from '@/api/client'
import type { AnalyticsDashboard } from '@/api/types'
import { useFetch } from '@/lib/useFetch'
import { SAMPLE_DASHBOARD } from '@/lib/sampleData'
import { fmtInt } from '@/lib/format'
import { Card, CardHead } from '@/components/Card'
import { StatCard } from '@/components/StatCard'
import { TopBar, TrendArea } from '@/components/charts'

async function load() {
  try {
    return { data: await api.get<AnalyticsDashboard>('/analytics/dashboard'), sample: false }
  } catch (e) {
    if (import.meta.env.DEV) return { data: SAMPLE_DASHBOARD, sample: true }
    throw e
  }
}

export function Analytics() {
  const { data, loading, error } = useFetch(load, [])
  const d = data?.data

  const ratingDist = useMemo(() => {
    const dist = d?.review_stats.distribution ?? {}
    return ['5', '4', '3', '2', '1'].map((r) => ({ name: `${r}★`, count: dist[r] ?? 0 }))
  }, [d])

  return (
    <>
      <div>
        <h1 className="page-title">Analytics</h1>
        <p className="page-sub">Engagement, reviews, and activity trends{data?.sample && <> · <span className="pill">Sample data</span></>}</p>
      </div>

      {error && <div className="error-banner">Couldn’t load analytics: {error}</div>}

      <div className="stat-grid">
        <StatCard loading={loading} label="Avg rating" value={(d?.review_stats.average_rating ?? 0).toFixed(1)} />
        <StatCard loading={loading} label="Total reviews" value={fmtInt(d?.review_stats.total)} />
        <StatCard loading={loading} label="Users reviewed" value={fmtInt(d?.engagement.users_reviewed)} />
        <StatCard loading={loading} label="Active (30d)" value={fmtInt(d?.summary.active_users_30d)} />
      </div>

      <div className="grid cols-2">
        <Card>
          <CardHead title="Rating distribution" />
          {loading ? <div className="skeleton" style={{ height: 240 }} />
            : <TopBar data={ratingDist} xKey="name" yKey="count" />}
        </Card>
        <Card>
          <CardHead title="Pick trend · 7 days" />
          {loading ? <div className="skeleton" style={{ height: 240 }} />
            : <TrendArea data={d?.pick_trends_7d ?? []} xKey="date" yKey="picks" />}
        </Card>
      </div>
    </>
  )
}
