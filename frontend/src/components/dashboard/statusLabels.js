/** Plain-language names for the stored transaction states (backend TransactionStatus). */
export const STATUS_LABELS = Object.freeze({
  INITIATED: 'Started',
  ANALYSED: 'Checked',
  AWAITING_USER_ACTION: 'Awaiting your decision',
  APPROVED: 'Approved',
  CANCELLED: 'Cancelled',
  EXPIRED: 'Expired',
  FAILED: 'Failed',
})
