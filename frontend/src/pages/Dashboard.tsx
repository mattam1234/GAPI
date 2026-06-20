import { useMemo } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { api } from '@/api/client'
import type { AnalyticsDashboard, TopGame } from '@/api/types'
import { useFetch } from '@/lib/useFetch'
import { SAMPLE_DASHBOARD } from '@/lib/sampleData'
import { fmtCompact, fmtInt, fmtPct } from '@/lib/format'
import { StatCard } from '@/components/StatCard'
import { Card, CardHead, EmptyState } from '@/components/Card'
import { DonutBreakdown, TopBar, TrendArea } from '@/components/charts'
import { DataTable } from '@/components/DataTable'

async function load(): Promise<{ data: AnalyticsDashboard; sample: boolean }> {
  try {
    return { data: await api.get<AnalyticsDashboard>('/analytics/dashboard'), sample: false }
  } catch (e) {
    if (import.meta.env.DEV) return { data: SAMPLE_DASHBOARD, sample: true }
    throw e
  }
}

export function Dashboard() {
  const { data, loading, error, reload } = useFetch(load, [])
  const d = data?.data
  const sample = data?.sample

  const topGames = useMemo(
    () => (d?.top_games ?? []).map((g: TopGame) => ({ name: g.game_name ?? g.game_id ?? '—', picks: g.pick_count })),
    [d],
  )
  const platforms = useMemo(
    () => Object.entries(d?.platform_stats ?? {}).map(([name, value]) => ({ name, value })),
    [d],
  )
  const totalPicks = d?.summary.total_picks ?? 0

  const columns: ColumnDef<TopGame, any>[] = [
    { id: 'rank', header: '#', cell: (c) => <span className="rank">{c.row.index + 1}</span> },
    { accessorKey: 'game_name', header: 'Game', cell: (c) => c.getValue() ?? c.row.original.game_id ?? '—' },
    { accessorKey: 'pick_count', header: 'Picks', cell: (c) => fmtInt(c.getValue() as number) },
    {
      id: 'share', header: 'Share',
      accessorFn: (r) => (totalPicks ? r.pick_count / totalPicks : 0),
      cell: (c) => fmtPct((c.getValue() as number) * 100, 1),
    },
  ]

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-sub">Library activity at a glance{sample && <> · <span className="pill">Sample data</span></>}</p>
        </div>
        <button className="btn" onClick={reload}>↻ Refresh</button>
      </div>

      {error && <div className="error-banner">Couldn’t load analytics: {error}</div>}

      <div className="stat-grid">
        <StatCard loading={loading} label="Total users" value={fmtInt(d?.summary.total_users)}
          delta={{ dir: 'up', text: `${fmtInt(d?.summary.active_users_7d)} active 7d` }} />
        <StatCard loading={loading} label="Picks (7d)" value={fmtInt(d?.summary.picks_7d)}
          delta={{ dir: 'up', text: `${fmtCompact(d?.summary.total_picks)} all-time` }} />
        <StatCard loading={loading} label="Avg picks / user" value={(d?.summary.avg_picks_per_user ?? 0).toFixed(1)} />
        <StatCard loading={loading} label="Games tracked" value={fmtInt(d?.summary.total_games)} />
        <StatCard loading={loading} label="Reviews" value={fmtInt(d?.summary.total_reviews)} />
        <StatCard loading={loading} label="Engagement" value={d?.engagement.engagement_rate ?? '—'}
          delta={{ dir: 'flat', text: `${fmtInt(d?.engagement.users_picked)} picked` }} />
      </div>

      <div className="grid cols-2">
        <Card>
          <CardHead title="Pick trend · 7 days" action={<span className="pill">Daily</span>} />
          {loading ? <div className="skeleton" style={{ height: 240 }} />
            : <TrendArea data={d?.pick_trends_7d ?? []} xKey="date" yKey="picks" />}
        </Card>
        <Card>
          <CardHead title="Active users · 7 days" />
          {loading ? <div className="skeleton" style={{ height: 240 }} />
            : <TrendArea data={d?.active_users_7d ?? []} xKey="date" yKey="active_users" color="var(--c2)" />}
        </Card>
      </div>

      <div className="grid cols-2">
        <Card>
          <CardHead title="Top games" action={<span className="muted" style={{ fontSize: 'var(--fs-small)' }}>by picks</span>} />
          {loading ? <div className="skeleton" style={{ height: 240 }} />
            : topGames.length ? <TopBar data={topGames} xKey="name" yKey="picks" />
              : <EmptyState label="No picks recorded yet" />}
        </Card>
        <Card>
          <CardHead title="Platform distribution" />
          {loading ? <div className="skeleton" style={{ height: 200 }} />
            : platforms.length ? <DonutBreakdown data={platforms} nameKey="name" valueKey="value" />
              : <EmptyState label="No platform data" />}
        </Card>
      </div>

      <Card>
        <CardHead title="Top games · detail" />
        <DataTable columns={columns} data={d?.top_games ?? []} loading={loading} empty="No picks recorded yet" />
      </Card>
    </>
  )
}
