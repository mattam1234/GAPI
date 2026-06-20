import { lazy, Suspense } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { Layout } from '@/components/Layout'

// Route-level code splitting: each page becomes its own chunk, and the heavy
// charting (recharts) only loads with the routes that use it.
const Dashboard = lazy(() => import('@/pages/Dashboard').then((m) => ({ default: m.Dashboard })))
const Analytics = lazy(() => import('@/pages/Analytics').then((m) => ({ default: m.Analytics })))
const Admin = lazy(() => import('@/pages/Admin').then((m) => ({ default: m.Admin })))
const Profile = lazy(() => import('@/pages/Profile').then((m) => ({ default: m.Profile })))

function PageFallback() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-5)' }} aria-busy="true" aria-label="Loading page">
      <div className="skeleton" style={{ height: 44, width: 240 }} />
      <div className="stat-grid">
        {Array.from({ length: 4 }).map((_, i) => <div key={i} className="skeleton" style={{ height: 96 }} />)}
      </div>
      <div className="skeleton" style={{ height: 280 }} />
    </div>
  )
}

const withSuspense = (el: React.ReactNode) => <Suspense fallback={<PageFallback />}>{el}</Suspense>

const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <Layout />,
      children: [
        { index: true, element: withSuspense(<Dashboard />) },
        { path: 'analytics', element: withSuspense(<Analytics />) },
        { path: 'admin', element: withSuspense(<Admin />) },
        { path: 'profile', element: withSuspense(<Profile />) },
      ],
    },
  ],
  { basename: '/app' },
)

export function App() {
  return <RouterProvider router={router} />
}
