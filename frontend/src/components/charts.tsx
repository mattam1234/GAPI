import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { useTheme, readTokens } from '@/lib/theme'
import { fmtCompact, fmtDate } from '@/lib/format'

function useTokens() {
  // Re-read on theme change (useTheme triggers re-render).
  useTheme()
  return readTokens()
}

const tooltipStyle = (t: ReturnType<typeof readTokens>) => ({
  background: t.surface,
  border: `1px solid ${t.border}`,
  borderRadius: 10,
  color: t.text,
  fontSize: 12,
})

/** Trend over time as a soft gradient area. */
export function TrendArea({ data, xKey, yKey, color }: {
  data: any[]; xKey: string; yKey: string; color?: string
}) {
  const t = useTokens()
  const c = color ?? t.series[0]
  return (
    <ResponsiveContainer width="100%" height={240}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <defs>
          <linearGradient id={`g-${yKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={c} stopOpacity={0.35} />
            <stop offset="100%" stopColor={c} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={t.grid} vertical={false} />
        <XAxis dataKey={xKey} tickFormatter={(v) => fmtDate(v as string)} stroke={t.muted}
          fontSize={11} tickLine={false} axisLine={false} minTickGap={24} />
        <YAxis tickFormatter={(v) => fmtCompact(v as number)} stroke={t.muted}
          fontSize={11} tickLine={false} axisLine={false} width={40} />
        <Tooltip contentStyle={tooltipStyle(t)} labelFormatter={(v) => fmtDate(v as string)} />
        <Area type="monotone" dataKey={yKey} stroke={c} strokeWidth={2}
          fill={`url(#g-${yKey})`} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

/** Horizontal-feel ranked bars (top N). */
export function TopBar({ data, xKey, yKey }: {
  data: any[]; xKey: string; yKey: string
}) {
  const t = useTokens()
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, left: 8, bottom: 0 }}>
        <CartesianGrid stroke={t.grid} horizontal={false} />
        <XAxis type="number" tickFormatter={(v) => fmtCompact(v as number)} stroke={t.muted}
          fontSize={11} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey={xKey} stroke={t.muted} fontSize={11}
          tickLine={false} axisLine={false} width={130} />
        <Tooltip contentStyle={tooltipStyle(t)} cursor={{ fill: t.grid }} />
        <Bar dataKey={yKey} radius={[0, 6, 6, 0]} barSize={16}>
          {data.map((_, i) => <Cell key={i} fill={t.series[i % t.series.length]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** Categorical breakdown as a donut with a legend. */
export function DonutBreakdown({ data, nameKey, valueKey }: {
  data: any[]; nameKey: string; valueKey: string
}) {
  const t = useTokens()
  const total = data.reduce((s, d) => s + Number(d[valueKey] ?? 0), 0)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
      <ResponsiveContainer width={200} height={200}>
        <PieChart>
          <Pie data={data} dataKey={valueKey} nameKey={nameKey} innerRadius={58} outerRadius={86}
            paddingAngle={2} stroke="none">
            {data.map((_, i) => <Cell key={i} fill={t.series[i % t.series.length]} />)}
          </Pie>
          <Tooltip contentStyle={tooltipStyle(t)} />
        </PieChart>
      </ResponsiveContainer>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8, flex: 1, minWidth: 160 }}>
        {data.map((d, i) => {
          const val = Number(d[valueKey] ?? 0)
          const pct = total ? Math.round((val / total) * 100) : 0
          return (
            <li key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, background: t.series[i % t.series.length] }} />
              <span style={{ flex: 1, color: 'var(--text-muted)' }}>{String(d[nameKey])}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{pct}%</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
