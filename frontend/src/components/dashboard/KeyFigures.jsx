import { formatDateRange, formatINR, formatNumber } from '../../utils/format'
import { Card, CardBody, CardHeader } from '../ui/Card'

const plural = (count, one, many) => `${formatNumber(count)} ${count === 1 ? one : many}`

/**
 * The four headline figures for the last 30 days, in one card (P-1: a row of key
 * figures, not separate icon tiles). 4 columns from 1024px, 2 from 640px, 1 below.
 */
export default function KeyFigures({ summary }) {
  const figures = [
    {
      label: 'Payments checked',
      value: formatNumber(summary.total),
      note: 'Submitted in the last 30 days',
    },
    {
      label: 'Approved amount',
      value: formatINR(summary.approvedAmountPaise),
      note: `${plural(summary.byStatus.APPROVED, 'approved payment', 'approved payments')} · simulated`,
    },
    {
      label: 'Needs your action',
      value: formatNumber(summary.awaitingAction),
      note: summary.awaitingAction > 0 ? 'Waiting for your decision' : 'Nothing waiting',
    },
    {
      label: 'Unread alerts',
      value: formatNumber(summary.unreadAlerts),
      note: 'All time',
    },
  ]

  return (
    <Card aria-labelledby="key-figures-heading">
      <CardHeader
        titleId="key-figures-heading"
        title="Last 30 days"
        description={formatDateRange(summary.period.start, summary.period.end)}
      />
      <CardBody>
        <dl className="grid gap-x-6 gap-y-6 sm:grid-cols-2 lg:grid-cols-4">
          {figures.map((figure) => (
            <div key={figure.label} className="min-w-0">
              <dt className="text-sm font-medium text-ink-muted">{figure.label}</dt>
              <dd className="mt-1 text-2xl font-semibold tracking-tight break-words text-ink sm:text-3xl">{figure.value}</dd>
              <dd className="mt-1 text-sm text-ink-subtle">{figure.note}</dd>
            </div>
          ))}
        </dl>
      </CardBody>
    </Card>
  )
}
