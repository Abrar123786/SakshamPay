/** Authentication routes and the safe post-sign-in redirect. */

export const LOGIN_PATH = '/login'
export const REGISTER_PATH = '/register'
export const ACCOUNT_PATH = '/account'
export const DASHBOARD_PATH = '/dashboard'

/** Where a signed-in user goes by default (P-9: the dashboard). */
export const DEFAULT_SIGNED_IN_PATH = DASHBOARD_PATH

/**
 * The page to return to after signing in. Only in-app paths are accepted (a single
 * leading slash, never "//host" or "/\host"), and never the auth pages themselves;
 * anything else falls back to the default. The value comes from router state set by
 * RequireAuth, never from the URL, so it cannot be used as an open redirect.
 */
export function safeReturnPath(from) {
  const pathname = from?.pathname
  if (typeof pathname !== 'string' || !/^\/(?![/\\])/.test(pathname)) return DEFAULT_SIGNED_IN_PATH
  if (pathname === LOGIN_PATH || pathname === REGISTER_PATH) return DEFAULT_SIGNED_IN_PATH
  const search = typeof from.search === 'string' && from.search.startsWith('?') ? from.search : ''
  const hash = typeof from.hash === 'string' && from.hash.startsWith('#') ? from.hash : ''
  return `${pathname}${search}${hash}`
}
