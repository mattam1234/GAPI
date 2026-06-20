import { Card, CardHead, EmptyState } from '@/components/Card'

export function Admin() {
  return (
    <>
      <div>
        <h1 className="page-title">Admin</h1>
        <p className="page-sub">User management, audit log, and moderation</p>
      </div>
      <div className="grid cols-2">
        <Card>
          <CardHead title="User management" action={<span className="pill">Soon</span>} />
          <EmptyState icon="⚙" label="Wires to /api/admin/users/search — coming with the admin-domain migration." />
        </Card>
        <Card>
          <CardHead title="Audit log" action={<span className="pill">Soon</span>} />
          <EmptyState icon="🗒" label="Activity & moderation timeline." />
        </Card>
      </div>
    </>
  )
}
