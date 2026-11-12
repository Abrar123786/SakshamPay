import { TRANSACTION_STATUSES } from '../../services/dashboardService'
import { formatNumber } from '../../utils/format'
import { Card, CardBody, CardHeader } from '../ui/Card'
import { STATUS_LABELS } from './statusLabels'

/**
 * Count of each stored status, with a proportion bar. The bars are decorative
 * (hidden from assistive technology); the numbers carry the meaning. One neutral
 * colour for every status: a status is not a risk level.
 */
export default function StatusBreakdown({ summary }) {
  const pastDeadline = summary.byStatus.AWAITING_USER_ACTION - summary.awaitingAction

  return (
    <Card aria-labelledby="status-breakdown-heading">
      <CardHeader
        titleId="status-breakdown-heading"
        title="Payments by status"
        description="The current status of each payment submitted in the last 30 days."
      />
      <CardBody>
        <dl className="space-y-3">
          {TRANSACTION_STATUSES.map((status) => {
            const count = summary.byStatus[status]
            const share = summary.total > 0 ? (count / summary.total) * 100 : 0
            return (
              <div key={status} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1.5 sm:grid-cols-[12rem_minmax(0,1fr)_3rem]">
                <dt className="text-sm text-ink">{STATUS_LABELS[status]}</dt>
                <dd className="text-right text-sm font-semibold text-ink tabular-nums sm:order-last">{formatNumber(count)}</dd>
                <dd aria-hidden="true" className="col-span-2 h-2 rounded-full bg-surface-muted sm:col-span-1">
                  <div className="h-2 rounded-full bg-brand" style={{ width: `${share}%` }} />
                </dd>
              </div>
            )
          })}
        </dl>
        {pastDeadline > 0 && (
          <p className="mt-4 text-sm text-ink-muted">
            {pastDeadline === 1
              ? '1 payment awaiting your decision has passed its deadline and will be marked as expired.'
              : `${formatNumber(pastDeadline)} payments awaiting your decision have passed their deadline and will be marked as expired.`}
          </p>
        )}
      </CardBody>
    </Card>
  )
}
