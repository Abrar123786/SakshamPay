/** A /dashboard/summary response (as the backend sends it) for tests. */
export const SUMMARY_RESPONSE = Object.freeze({
  period: { days: 30, start: '2026-10-10T18:00:00Z', end: '2026-11-09T18:00:00Z' },
  transactions: {
    total: 10,
    by_status: { INITIATED: 0, ANALYSED: 0, AWAITING_USER_ACTION: 1, APPROVED: 7, CANCELLED: 1, EXPIRED: 1, FAILED: 0 },
    awaiting_action: 1,
    approved_amount_paise: 4_459_000,
  },
  alerts: { unread: 3 },
})

export const EMPTY_SUMMARY_RESPONSE = Object.freeze({
  period: SUMMARY_RESPONSE.period,
  transactions: {
    total: 0,
    by_status: { INITIATED: 0, ANALYSED: 0, AWAITING_USER_ACTION: 0, APPROVED: 0, CANCELLED: 0, EXPIRED: 0, FAILED: 0 },
    awaiting_action: 0,
    approved_amount_paise: 0,
  },
  alerts: { unread: 0 },
})
