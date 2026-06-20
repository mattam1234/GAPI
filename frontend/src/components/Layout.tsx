import { NavLink, Outlet } from 'react-router-dom'
import { useTheme } from '@/lib/theme'

const NAV = [
  { to: '/', label: 'Dashboard', icon: '◫', end: true },
  { to: '/analytics', label: 'Analytics', icon: '📈' },
  { to: '/admin', label: 'Admin', icon: '⚙' },
  { to: '/profile', label: 'Profile', icon: '◐' },
]

export function Layout() {
  const { mode, toggle } = useTheme()
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo">G</span>
          <span>GAPI<span className="muted" style={{ fontWeight: 500 }}> Console</span></span>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}
              className={({ isActive }) => (isActive ? 'active' : '')}>
              <span className="ico" aria-hidden>{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div style={{ marginTop: 'auto', fontSize: 'var(--fs-small)' }} className="muted">
          <span className="pill">v2.0 · FastAPI</span>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="muted" style={{ fontSize: 'var(--fs-small)' }}>Game library intelligence</div>
          <button className="btn btn-icon" onClick={toggle} title="Toggle theme" aria-label="Toggle theme">
            {mode === 'dark' ? '☀' : '☾'}
          </button>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
