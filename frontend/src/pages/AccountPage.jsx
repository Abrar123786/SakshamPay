import { LogOut } from 'lucide-react'

import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { useAuth } from '../context/authContext'
import PageContainer from '../layouts/PageContainer'
import PageHeader from '../layouts/PageHeader'
import { formatDate } from '../utils/format'

/** Minimal signed-in page (P-8): the profile from GET /auth/me and a way to sign out. */
export default function AccountPage() {
  const { user, logout } = useAuth()

  const rows = [
    ['Full name', user.full_name],
    ['Email address', user.email],
    ['Mobile number', user.phone_number ?? <span key="none" className="text-ink-subtle">Not added</span>],
    ['Member since', formatDate(user.created_at)],
    ['Status', <Badge key="status" tone={user.is_active ? 'brand' : 'neutral'}>{user.is_active ? 'Active' : 'Inactive'}</Badge>],
  ]

  return (
    <PageContainer size="narrow" className="py-10 sm:py-16">
      <title>Your account · SakshamPay</title>
      <PageHeader
        title="Your account"
        description={`Signed in as ${user.email}`}
        actions={
          <Button variant="secondary" leadingIcon={LogOut} onClick={logout}>
            Sign out
          </Button>
        }
      />

      <Card aria-labelledby="profile-heading" className="mt-8">
        <CardHeader titleId="profile-heading" title="Profile" description="The details on your SakshamPay account." />
        <CardBody>
          <dl className="divide-y divide-line">
            {rows.map(([label, value]) => (
              <div key={label} className="grid gap-1 py-3 first:pt-0 last:pb-0 sm:grid-cols-3 sm:gap-4">
                <dt className="text-sm font-medium text-ink-muted">{label}</dt>
                <dd className="text-base break-words text-ink sm:col-span-2">{value}</dd>
              </div>
            ))}
          </dl>
        </CardBody>
      </Card>
    </PageContainer>
  )
}
