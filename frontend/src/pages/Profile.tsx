import { useMemo } from 'react'
import { api, ApiError } from '@/api/client'
import type { CurrentUser, UserProfile } from '@/api/types'
import { useFetch } from '@/lib/useFetch'
import { fmtInt, fmtDate } from '@/lib/format'
import { Card, CardHead } from '@/components/Card'
import { StatCard } from '@/components/StatCard'

interface ProfileData {
  current: CurrentUser
  profile: UserProfile | null
  notSignedIn: boolean
}

async function load(): Promise<ProfileData> {
  let current: CurrentUser
  try {
    current = await api.get<CurrentUser>('/auth/current')
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
      return { current: { username: null }, profile: null, notSignedIn: true }
    }
    throw e
  }

  if (!current.username) {
    return { current, profile: null, notSignedIn: true }
  }

  // The richer profile endpoint may not exist for every user; treat any failure
  // as "no extended profile" rather than a hard error.
  let profile: UserProfile | null = null
  try {
    profile = await api.get<UserProfile>(`/user-profile/${encodeURIComponent(current.username)}`)
  } catch {
    profile = null
  }

  return { current, profile, notSignedIn: false }
}

function initials(name: string): string {
  return name.split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase() ?? '').join('') || name[0]?.toUpperCase() || '?'
}

export function Profile() {
  const { data, loading, error, reload } = useFetch(load, [])

  const roles = useMemo(() => {
    const set = new Set<string>()
    if (data?.current.role) set.add(data.current.role)
    data?.current.roles?.forEach((r) => set.add(r))
    data?.profile?.role && set.add(data.profile.role)
    data?.profile?.roles?.forEach((r) => set.add(r))
    return [...set]
  }, [data])

  const username = data?.profile?.username ?? data?.current.username ?? null
  const profile = data?.profile

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <h1 className="page-title">Profile</h1>
          <p className="page-sub">Your account and activity</p>
        </div>
        <button className="btn" onClick={reload}>↻ Refresh</button>
      </div>

      {error && <div className="error-banner">Couldn’t load your profile: {error}</div>}

      {loading ? (
        <Card>
          <div className="skeleton" style={{ height: 120 }} />
        </Card>
      ) : data?.notSignedIn || !username ? (
        <Card>
          <CardHead title="Not signed in" />
          <p className="muted">
            You’re not signed in. Log in via the main GAPI app, then return here — your
            session cookie is shared, so no separate login is needed.
          </p>
        </Card>
      ) : (
        <>
          <Card>
            <div style={{ display: 'flex', gap: 'var(--sp-5)', alignItems: 'center', flexWrap: 'wrap' }}>
              <div className="avatar" aria-hidden>{initials(username)}</div>
              <div style={{ display: 'grid', gap: 4 }}>
                <h2 style={{ fontSize: '1.4rem', fontWeight: 700, letterSpacing: '-.02em' }}>{username}</h2>
                {profile?.email && <span className="muted">{profile.email}</span>}
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                  {roles.length ? roles.map((r) => <span key={r} className="pill">{r}</span>)
                    : <span className="muted">No roles</span>}
                </div>
              </div>
            </div>
          </Card>

          <div className="stat-grid">
            <StatCard label="Picks" value={fmtInt(profile?.pick_count)} />
            <StatCard label="Reviews" value={fmtInt(profile?.review_count)} />
            <StatCard label="Reputation" value={fmtInt(profile?.reputation)} />
            <StatCard label="Member since" value={profile?.created_at ? fmtDate(profile.created_at) : '—'} />
          </div>

          <Card>
            <CardHead title="Account details" />
            <dl style={{ display: 'grid', gap: 12, margin: 0 }}>
              <Row label="Username" value={username} />
              <Row label="Email" value={profile?.email ?? '—'} />
              <Row label="Primary role" value={data?.current.role ?? profile?.role ?? '—'} />
              <Row label="All roles" value={roles.join(', ') || '—'} />
              {profile?.bio && <Row label="Bio" value={profile.bio} />}
            </dl>
            {!profile && (
              <p className="muted" style={{ marginTop: 'var(--sp-4)', fontSize: 'var(--fs-small)' }}>
                Extended profile not available — showing session info only.
              </p>
            )}
          </Card>
        </>
      )}
    </>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, borderBottom: '1px solid var(--border)', paddingBottom: 8 }}>
      <dt className="muted">{label}</dt>
      <dd style={{ margin: 0, fontWeight: 600, textAlign: 'right' }}>{value}</dd>
    </div>
  )
}
