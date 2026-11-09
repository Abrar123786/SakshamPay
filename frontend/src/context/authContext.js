import { createContext, useContext } from 'react'

/**
 * status:
 *   'restoring'       a stored token exists and GET /auth/me is confirming it
 *   'authenticated'   `user` is the profile from GET /auth/me
 *   'unauthenticated' no valid session; `endedReason` says why one just ended, if it did
 *   'error'           the token could not be checked (network, timeout, 5xx); the
 *                     session is kept and `retry()` checks again
 *
 * endedReason: 'expired' | 'invalid' | 'signedOut' | null
 */
export const AuthContext = createContext(null)

export function useAuth() {
  const auth = useContext(AuthContext)
  if (!auth) throw new Error('useAuth() must be used inside <AuthProvider>.')
  return auth
}

export const SESSION_ENDED_MESSAGES = Object.freeze({
  expired: 'Your session expired. Please sign in again.',
  invalid: 'Your session has ended. Please sign in again.',
  signedOut: 'You have signed out.',
})
