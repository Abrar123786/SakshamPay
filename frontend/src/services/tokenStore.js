/**
 * The access-token session: `{ accessToken, expiresAt }` (expiresAt = epoch milliseconds).
 *
 * Stored in sessionStorage (P-1 decision D12): it survives a page refresh, is
 * scoped to one browser tab and is cleared when the tab closes. It is NOT in
 * localStorage, so it does not persist across browser restarts. Passwords and the
 * user profile are never stored. The JWT is opaque here and is never decoded.
 *
 * sessionStorage is the single source of truth. Only when it cannot be written
 * (blocked storage, some private modes) is the session kept in memory instead,
 * in which case it is lost on refresh.
 */

export const SESSION_STORAGE_KEY = 'sakshampay.session'
const MAX_TOKEN_LENGTH = 4096

let memoryOnly = null

function storage() {
  try {
    return window.sessionStorage ?? null
  } catch {
    return null
  }
}

function isValidSession(value) {
  return (
    value !== null &&
    typeof value === 'object' &&
    typeof value.accessToken === 'string' &&
    value.accessToken.length > 0 &&
    value.accessToken.length <= MAX_TOKEN_LENGTH &&
    Number.isFinite(value.expiresAt)
  )
}

/**
 * Save the token from POST /auth/login. Expiry is computed from `expires_in` and the
 * local clock, so a device clock that is wrong does not end the session early or late.
 */
export function saveSession({ accessToken, expiresIn }, now = Date.now()) {
  const session = { accessToken, expiresAt: now + expiresIn * 1000 }
  if (!isValidSession(session) || !(expiresIn > 0)) throw new TypeError('Invalid access-token session')
  try {
    const store = storage()
    if (!store) throw new Error('sessionStorage unavailable')
    store.setItem(SESSION_STORAGE_KEY, JSON.stringify(session))
    memoryOnly = null
  } catch {
    memoryOnly = session
  }
  return session
}

/** The stored session, or null. Malformed stored values are deleted. Expiry is not checked here. */
export function getSession() {
  if (memoryOnly) return memoryOnly
  let raw = null
  try {
    raw = storage()?.getItem(SESSION_STORAGE_KEY) ?? null
  } catch {
    return null
  }
  if (raw === null) return null
  try {
    const session = JSON.parse(raw)
    if (isValidSession(session)) return session
  } catch {
    // malformed JSON: fall through
  }
  clearSession()
  return null
}

export function isExpired(session, now = Date.now()) {
  return !session || now >= session.expiresAt
}

export function clearSession() {
  memoryOnly = null
  try {
    storage()?.removeItem(SESSION_STORAGE_KEY)
  } catch {
    // nothing to clear
  }
}
