import { useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { api, ApiError } from '@/api/client'
import type {
  AdminUser, AdminUserSearchResponse, ApiEndpointStat, ApiStatsResponse, AuditLogEntry,
} from '@/api/types'
import { useFetch } from '@/lib/useFetch'
import { useDebounce } from '@/lib/useDebounce'
import { fmtInt, fmtMs, fmtPct, fmtDateTime } from '@/lib/format'
import { SAMPLE_ADMIN_USERS, SAMPLE_API_STATS, SAMPLE_AUDIT_LOGS } from '@/lib/sampleData'
import { Card, CardHead, EmptyState } from '@/components/Card'
import { DataTable } from '@/components/DataTable'
import { TopBar } from '@/components/charts'

const PAGE_SIZE = 10
const ROLES = ['', 'admin', 'moderator', 'user'] as const
const STATUSES = ['', 'active', 'suspended'] as const

function isAuthError(e: unknown): e is ApiError {
  return e instanceof ApiError && (e.status === 401 || e.status === 403)
}

// ── Users (search + filters + pagination) ────────────────────────────────────
interface UsersResult { resp: AdminUserSearchResponse; sample: boolean; denied: boolean }

async function loadUsers(q: string, role: string, status: string, offset: number): Promise<UsersResult> {
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  if (role) params.set('role', role)
  if (status) params.set('status', status)
  params.set('limit', String(PAGE_SIZE))
  params.set('offset', String(offset))
  try {
    const resp = await api.get<AdminUserSearchResponse>(`/admin/users/search?${params.toString()}`)
    return { resp, sample: false, denied: false }
  } catch (e) {
    if (isAuthError(e)) {
      if (import.meta.env.DEV) {
        const filtered = SAMPLE_ADMIN_USERS.filter((u) =>
          (!q || u.username.toLowerCase().includes(q.toLowerCase())) &&
          (!role || u.roles?.includes(role) || u.role === role) &&
          (!status || u.status === status))
        return { resp: { users: filtered.slice(offset, offset + PAGE_SIZE), count: filtered.length }, sample: true, denied: true }
      }
      return { resp: { users: [], count: 0 }, sample: false, denied: true }
    }
    if (import.meta.env.DEV) {
      return { resp: { users: SAMPLE_ADMIN_USERS.slice(offset, offset + PAGE_SIZE), count: SAMPLE_ADMIN_USERS.length }, sample: true, denied: false }
    }
    throw e
  }
}

function UsersPanel() {
  const [query, setQuery] = useState('')
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(0)
  const q = useDebounce(query, 300)
  const offset = page * PAGE_SIZE

  // Reset to first page whenever the filter set changes.
  const filterKey = `${q}|${role}|${status}`
  const { data, loading, error } = useFetch(
    () => loadUsers(q, role, status, offset),
    [filterKey, offset],
  )

  const users = data?.resp.users ?? []
  const total = data?.resp.count ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const sample = data?.sample
  const denied = data?.denied && !sample

  const columns: ColumnDef<AdminUser, any>[] = [
    { accessorKey: 'username', header: 'Username', cell: (c) => <span style={{ fontWeight: 600 }}>{c.getValue() as string}</span> },
    {
      id: 'roles', header: 'Role(s)',
      accessorFn: (r) => (r.roles?.length ? r.roles.join(', ') : r.role ?? '—'),
      cell: (c) => {
        const list = (c.row.original.roles?.length ? c.row.original.roles : [c.row.original.role].filter(Boolean)) as string[]
        return list.length
          ? <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>{list.map((r) => <span key={r} className="pill">{r}</span>)}</span>
          : '—'
      },
    },
    {
      accessorKey: 'status', header: 'Status',
      cell: (c) => {
        const s = (c.getValue() as string) ?? 'unknown'
        return <span className={`badge badge-${s === 'active' ? 'ok' : s === 'suspended' ? 'danger' : 'muted'}`}>{s}</span>
      },
    },
    {
      id: 'actions', header: 'Actions', enableSorting: false,
      cell: (c) => (
        <button className="btn btn-sm" disabled aria-label={`Manage ${c.row.original.username}`} title="Management actions arrive with the admin-domain migration">
          Manage
        </button>
      ),
    },
  ]

  function changeFilter(setter: (v: string) => void, v: string) {
    setter(v)
    setPage(0)
  }

  return (
    <Card>
      <CardHead
        title="Users"
        action={sample ? <span className="pill">Sample data</span> : <span className="muted" style={{ fontSize: 'var(--fs-small)' }}>{fmtInt(total)} total</span>}
      />

      <div className="toolbar" role="search">
        <label className="sr-only" htmlFor="user-search">Search users</label>
        <input
          id="user-search"
          className="input"
          type="search"
          placeholder="Search username…"
          value={query}
          onChange={(e) => changeFilter(setQuery, e.target.value)}
          autoComplete="off"
        />
        <label className="sr-only" htmlFor="role-filter">Filter by role</label>
        <select id="role-filter" className="input" value={role} onChange={(e) => changeFilter(setRole, e.target.value)}>
          {ROLES.map((r) => <option key={r} value={r}>{r ? `Role: ${r}` : 'All roles'}</option>)}
        </select>
        <label className="sr-only" htmlFor="status-filter">Filter by status</label>
        <select id="status-filter" className="input" value={status} onChange={(e) => changeFilter(setStatus, e.target.value)}>
          {STATUSES.map((s) => <option key={s} value={s}>{s ? `Status: ${s}` : 'All statuses'}</option>)}
        </select>
      </div>

      {denied ? (
        <EmptyState icon="🔒" label="Admin access required. Sign in with an admin account to manage users." />
      ) : error ? (
        <div className="error-banner" style={{ marginBottom: 'var(--sp-3)' }}>Couldn’t load users: {error}</div>
      ) : (
        <>
          <DataTable columns={columns} data={users} loading={loading} empty="No users match these filters" />
          {total > PAGE_SIZE && (
            <nav className="pager" aria-label="User pages">
              <button className="btn btn-sm" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0 || loading}>← Prev</button>
              <span className="muted" style={{ fontSize: 'var(--fs-small)' }} aria-live="polite">Page {page + 1} of {pages}</span>
              <button className="btn btn-sm" onClick={() => setPage((p) => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1 || loading}>Next →</button>
            </nav>
          )}
        </>
      )}
    </Card>
  )
}

// ── API stats ────────────────────────────────────────────────────────────────
interface StatsResult { stats: ApiEndpointStat[]; sample: boolean; denied: boolean }

async function loadStats(): Promise<StatsResult> {
  try {
    const resp = await api.get<ApiStatsResponse>('/admin/api-stats')
    return { stats: resp.stats ?? [], sample: false, denied: false }
  } catch (e) {
    if (isAuthError(e)) {
      if (import.meta.env.DEV) return { stats: SAMPLE_API_STATS, sample: true, denied: true }
      return { stats: [], sample: false, denied: true }
    }
    if (import.meta.env.DEV) return { stats: SAMPLE_API_STATS, sample: true, denied: false }
    throw e
  }
}

function ApiStatsPanel() {
  const { data, loading, error } = useFetch(loadStats, [])
  const stats = data?.stats ?? []
  const sample = data?.sample
  const denied = data?.denied && !sample

  const byCalls = useMemo(() => [...stats].sort((a, b) => b.calls - a.calls), [stats])
  const topBars = useMemo(
    () => byCalls.slice(0, 7).map((s) => ({ name: shortEndpoint(s.endpoint), calls: s.calls })),
    [byCalls],
  )

  const columns: ColumnDef<ApiEndpointStat, any>[] = [
    { accessorKey: 'endpoint', header: 'Endpoint', cell: (c) => <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-small)' }}>{c.getValue() as string}</span> },
    { accessorKey: 'calls', header: 'Calls', cell: (c) => fmtInt(c.getValue() as number) },
    { accessorKey: 'avg_ms', header: 'Avg', cell: (c) => fmtMs(c.getValue() as number, 1) },
    {
      id: 'error_rate', header: 'Error rate',
      accessorFn: (r) => (r.calls ? (r.errors / r.calls) * 100 : 0),
      cell: (c) => {
        const pct = c.getValue() as number
        return <span className={pct >= 2 ? 'delta down' : 'muted'} style={{ fontSize: 'var(--fs-small)', fontWeight: 600 }}>{fmtPct(pct, 2)}</span>
      },
    },
  ]

  return (
    <Card>
      <CardHead
        title="API stats"
        action={sample ? <span className="pill">Sample data</span> : <span className="muted" style={{ fontSize: 'var(--fs-small)' }}>by calls</span>}
      />
      {denied ? (
        <EmptyState icon="🔒" label="Admin access required to view API stats." />
      ) : error ? (
        <div className="error-banner">Couldn’t load API stats: {error}</div>
      ) : (
        <>
          {loading ? <div className="skeleton" style={{ height: 240 }} />
            : topBars.length ? <TopBar data={topBars} xKey="name" yKey="calls" />
              : <EmptyState label="No endpoint activity recorded" />}
          <div style={{ marginTop: 'var(--sp-4)' }}>
            <DataTable columns={columns} data={byCalls} loading={loading} empty="No endpoint activity recorded" />
          </div>
        </>
      )}
    </Card>
  )
}

function shortEndpoint(ep: string): string {
  return ep.replace(/^\w+\s+/, '').replace(/^\/api\//, '/')
}

// ── Audit log ────────────────────────────────────────────────────────────────
interface AuditResult { entries: AuditLogEntry[]; sample: boolean; denied: boolean }

async function loadAudit(): Promise<AuditResult> {
  try {
    const resp = await api.get<AuditLogEntry[] | { logs?: AuditLogEntry[]; entries?: AuditLogEntry[] }>('/admin/audit-logs')
    const entries = Array.isArray(resp) ? resp : (resp.logs ?? resp.entries ?? [])
    return { entries, sample: false, denied: false }
  } catch (e) {
    if (isAuthError(e)) {
      if (import.meta.env.DEV) return { entries: SAMPLE_AUDIT_LOGS, sample: true, denied: true }
      return { entries: [], sample: false, denied: true }
    }
    if (import.meta.env.DEV) return { entries: SAMPLE_AUDIT_LOGS, sample: true, denied: false }
    throw e
  }
}

function AuditPanel() {
  const { data, loading, error } = useFetch(loadAudit, [])
  const entries = data?.entries ?? []
  const sample = data?.sample
  const denied = data?.denied && !sample

  const columns: ColumnDef<AuditLogEntry, any>[] = [
    { accessorKey: 'timestamp', header: 'When', cell: (c) => <span style={{ whiteSpace: 'nowrap' }}>{fmtDateTime(c.getValue() as string)}</span> },
    { accessorKey: 'actor', header: 'Actor', cell: (c) => (c.getValue() as string) ?? '—' },
    { accessorKey: 'action', header: 'Action', cell: (c) => <span className="badge badge-muted">{(c.getValue() as string) ?? '—'}</span> },
    { accessorKey: 'target', header: 'Target', cell: (c) => (c.getValue() as string) ?? '—' },
    { accessorKey: 'detail', header: 'Detail', cell: (c) => <span className="muted">{(c.getValue() as string) ?? '—'}</span> },
  ]

  return (
    <Card>
      <CardHead
        title="Audit log"
        action={sample ? <span className="pill">Sample data</span> : <span className="muted" style={{ fontSize: 'var(--fs-small)' }}>recent</span>}
      />
      {denied ? (
        <EmptyState icon="🔒" label="Admin access required to view the audit log." />
      ) : error ? (
        <div className="error-banner">Couldn’t load the audit log: {error}</div>
      ) : (
        <DataTable columns={columns} data={entries} loading={loading} empty="No audit entries yet" />
      )}
    </Card>
  )
}

export function Admin() {
  return (
    <>
      <div>
        <h1 className="page-title">Admin</h1>
        <p className="page-sub">User management, API health, and the audit trail</p>
      </div>

      <UsersPanel />

      <div className="grid cols-2">
        <ApiStatsPanel />
        <AuditPanel />
      </div>
    </>
  )
}
