import DashboardEmpty from '../components/dashboard/DashboardEmpty'
import DashboardSkeleton from '../components/dashboard/DashboardSkeleton'
import KeyFigures from '../components/dashboard/KeyFigures'
import StatusBreakdown from '../components/dashboard/StatusBreakdown'
import ErrorState from '../components/ui/ErrorState'
import { useAuth } from '../context/authContext'
import { useDashboardSummary } from '../hooks/useDashboardSummary'
import PageContainer from '../layouts/PageContainer'
import PageHeader from '../layouts/PageHeader'

/**
 * Signed-in home (P-9): the user's last 30 days from GET /dashboard/summary.
 *
 * Deliberately not here yet: risk statistics (until the risk engine produces real
 * assessments), recent transactions (P-11) and a new-payment action (P-10).
 */
export default function DashboardPage() {
  const { user } = useAuth()
  const { status, summary, error, retry } = useDashboardSummary()
  const firstName = user.full_name.split(' ')[0]

  return (
    <PageContainer className="py-10 sm:py-12">
      <title>Dashboard · SakshamPay</title>
      <PageHeader
        eyebrow="Dashboard"
        title={`Welcome back, ${firstName}`}
        description="Your payments over the last 30 days. All payments in SakshamPay are simulated."
      />

      <div className="mt-8">
        {status === 'loading' && <DashboardSkeleton />}

        {status === 'error' && (
          <ErrorState title="We couldn't load your summary" error={error} onRetry={retry} retryLabel="Try again" />
        )}

        {status === 'ready' && summary.total === 0 && <DashboardEmpty unreadAlerts={summary.unreadAlerts} />}

        {status === 'ready' && summary.total > 0 && (
          <div className="space-y-6">
            <KeyFigures summary={summary} />
            <StatusBreakdown summary={summary} />
          </div>
        )}
      </div>
    </PageContainer>
  )
}
