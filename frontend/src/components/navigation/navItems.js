import { ACCOUNT_PATH, DASHBOARD_PATH } from '../../utils/authPaths'

/**
 * Main navigation for signed-in users, in display order. Later phases add their
 * pages here (P-10 payments, P-11 history, alerts) and every layout picks them up.
 * `end: true` makes the link active only on that exact path.
 */
export const SIGNED_IN_NAV_ITEMS = Object.freeze([
  { to: DASHBOARD_PATH, label: 'Dashboard', end: true },
  { to: ACCOUNT_PATH, label: 'Account', end: true },
])
