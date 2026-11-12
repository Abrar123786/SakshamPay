import { ShieldCheck } from 'lucide-react'

import { formatNumber } from '../../utils/format'
import { Card, CardBody } from '../ui/Card'

/**
 * Shown when the user has no payments in the last 30 days. No placeholder
 * figures or empty charts; unread alerts are mentioned only if there are any.
 */
export default function DashboardEmpty({ unreadAlerts }) {
  return (
    <Card aria-labelledby="dashboard-empty-heading">
      <CardBody>
        <div className="flex flex-col items-center py-6 text-center">
          <ShieldCheck aria-hidden="true" focusable="false" strokeWidth={1.75} className="size-10 text-brand" />
          <h2 id="dashboard-empty-heading" className="mt-4 text-lg font-semibold text-ink">
            No payments in the last 30 days
          </h2>
          <p className="mt-2 max-w-md text-sm text-ink-muted">
            When you check a payment with SakshamPay, a summary of the last 30 days appears here: how many you
            checked, what was approved and anything waiting for your decision.
          </p>
          {unreadAlerts > 0 && (
            <p className="mt-4 text-sm font-medium text-ink">
              {unreadAlerts === 1 ? 'You have 1 unread alert.' : `You have ${formatNumber(unreadAlerts)} unread alerts.`}
            </p>
          )}
        </div>
      </CardBody>
    </Card>
  )
}
