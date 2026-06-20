import { api } from '@/api/client'
import { useFetch } from '@/lib/useFetch'
import { Card, CardHead } from '@/components/Card'

interface CurrentUser { username: string | null; role?: string; roles?: string[] }

export function Profile() {
  const { data, loading, error } = useFetch(() => api.get<CurrentUser>('/auth/current'), [])

  return (
    <>
      <div>
        <h1 className="page-title">Profile</h1>
        <p className="page-sub">Your account</p>
      </div>
      <Card>
        <CardHead title="Account" />
        {loading ? (
          <div className="skeleton" style={{ height: 60 }} />
        ) : error ? (
          <p className="muted">Not signed in. Log in via the main app, then return here.</p>
        ) : (
          <div style={{ display: 'grid', gap: 12 }}>
            <Row label="Username" value={data?.username ?? '—'} />
            <Row label="Role" value={data?.role ?? '—'} />
            <Row label="Roles" value={(data?.roles ?? []).join(', ') || '—'} />
          </div>
        )}
      </Card>
    </>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border)', paddingBottom: 8 }}>
      <span className="muted">{label}</span>
      <span style={{ fontWeight: 600 }}>{value}</span>
    </div>
  )
}
