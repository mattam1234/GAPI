import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import { Dashboard } from '@/pages/Dashboard'
import { Analytics } from '@/pages/Analytics'
import { Admin } from '@/pages/Admin'
import { Profile } from '@/pages/Profile'

const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <Layout />,
      children: [
        { index: true, element: <Dashboard /> },
        { path: 'analytics', element: <Analytics /> },
        { path: 'admin', element: <Admin /> },
        { path: 'profile', element: <Profile /> },
      ],
    },
  ],
  { basename: '/app' },
)

export function App() {
  return <RouterProvider router={router} />
}
