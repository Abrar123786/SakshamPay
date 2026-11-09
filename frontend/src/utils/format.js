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

export function formatINR(paise, { showPaise = true } = {}) {
  if (!Number.isSafeInteger(paise)) {
    throw new TypeError(`formatINR expects integer paise, received ${paise}`)
  }
  const rupees = paise / 100
  return (showPaise ? withPaise : wholeRupees).format(rupees)
}
