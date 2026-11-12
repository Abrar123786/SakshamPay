/**
 * Money and number formatting for India (en-IN).
 *
 * The backend stores money as integer paise (P-4), so formatting starts from paise:
 *   formatINR(10000000)  -> '₹1,00,000.00'
 *   formatINR(4850, { showPaise: false }) -> '₹49'
 */

const withPaise = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const wholeRupees = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
})

const longDate = new Intl.DateTimeFormat('en-IN', { dateStyle: 'long' })
const shortDate = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
const wholeNumber = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })

/** Counts with Indian digit grouping: 1234567 -> '12,34,567'. */
export function formatNumber(value) {
  if (!Number.isSafeInteger(value)) throw new TypeError(`formatNumber expects an integer, received ${value}`)
  return wholeNumber.format(value)
}

/** Two ISO timestamps as a compact range in the viewer's time zone, e.g. '11 Oct – 10 Nov 2026'. */
export function formatDateRange(startIso, endIso) {
  const start = new Date(startIso)
  const end = new Date(endIso)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    throw new TypeError(`formatDateRange expects ISO dates, received ${startIso}, ${endIso}`)
  }
  return shortDate.formatRange(start, end)
}

/** '2026-11-09T10:00:00Z' -> '9 November 2026' (in the viewer's time zone). */
export function formatDate(isoString) {
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) throw new TypeError(`formatDate expects an ISO date, received ${isoString}`)
  return longDate.format(date)
}

export function formatINR(paise, { showPaise = true } = {}) {
  if (!Number.isSafeInteger(paise)) {
    throw new TypeError(`formatINR expects integer paise, received ${paise}`)
  }
  const rupees = paise / 100
  return (showPaise ? withPaise : wholeRupees).format(rupees)
}
