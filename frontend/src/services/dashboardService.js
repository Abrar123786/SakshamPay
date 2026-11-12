import { ApiError, apiClient } from './apiClient'

export const DASHBOARD_SUMMARY_PATH = '/dashboard/summary'

/** Stored transaction states, in lifecycle order (backend TransactionStatus). */
export const TRANSACTION_STATUSES = Object.freeze([
  'INITIATED',
  'ANALYSED',
  'AWAITING_USER_ACTION',
  'APPROVED',
  'CANCELLED',
  'EXPIRED',
  'FAILED',
])

const isCount = (value) => Number.isSafeInteger(value) && value >= 0
const isDate = (value) => typeof value === 'string' && !Number.isNaN(Date.parse(value))

function invalidResponse() {
  return new ApiError({
    status: 200,
    code: 'INVALID_RESPONSE',
    message: 'The dashboard summary could not be read. Please try again.',
  })
}

/**
 * Check the response before showing it. A missing or malformed figure is an
 * error, never shown as 0, so the dashboard cannot display numbers the server
 * did not send.
 */
export function parseDashboardSummary(data) {
  const period = data?.period
  const transactions = data?.transactions
  const byStatus = transactions?.by_status
  const valid =
    period?.days === 30 &&
    isDate(period.start) &&
    isDate(period.end) &&
    isCount(transactions?.total) &&
    byStatus !== null &&
    typeof byStatus === 'object' &&
    TRANSACTION_STATUSES.every((status) => isCount(byStatus[status])) &&
    isCount(transactions.awaiting_action) &&
    isCount(transactions.approved_amount_paise) &&
    isCount(data?.alerts?.unread)
  if (!valid) throw invalidResponse()

  return Object.freeze({
    period: { days: period.days, start: period.start, end: period.end },
    total: transactions.total,
    byStatus: Object.fromEntries(TRANSACTION_STATUSES.map((status) => [status, byStatus[status]])),
    awaitingAction: transactions.awaiting_action,
    approvedAmountPaise: transactions.approved_amount_paise,
    unreadAlerts: data.alerts.unread,
  })
}

/** GET /dashboard/summary for the signed-in user (bearer token added by apiClient). */
export async function getDashboardSummary({ signal } = {}) {
  const { data } = await apiClient.get(DASHBOARD_SUMMARY_PATH, { signal })
  return parseDashboardSummary(data)
}
