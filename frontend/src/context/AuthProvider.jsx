import { useCallback, useEffect, useMemo, useState } from 'react'

import { setUnauthorizedHandler } from '../services/apiClient'
import { fetchCurrentUser, registerAccount, requestAccessToken } from '../services/authService'
import { clearSession, getSession, isExpired, saveSession } from '../services/tokenStore'
import { AuthContext } from './authContext'

function initialState() {
  const session = getSession()
  if (!session) return { status: 'unauthenticated', user: null, error: null, endedReason: null }
  if (isExpired(session)) {
    clearSession()
    return { status: 'unauthenticated', user: null, error: null, endedReason: 'expired' }
  }
  return { status: 'restoring', user: null, error: null, endedReason: null }
}

/**
 * The single owner of authentication state. Pages use `useAuth()`; nothing else
 * reads the token store or calls the auth endpoints directly.
 *
 * The provider does not navigate. Route guards react to `status`.
 */
export default function AuthProvider({ children }) {
  const [state, setState] = useState(initialState)
  const [checkCount, setCheckCount] = useState(0)

  const endSession = useCallback((reason) => {
    clearSession()
    setState({ status: 'unauthenticated', user: null, error: null, endedReason: reason })
  }, [])

  // Any authenticated request rejected with 401, or a token found expired, ends the session.
  useEffect(
    () => setUnauthorizedHandler((error) => endSession(error.code === 'TOKEN_EXPIRED' ? 'expired' : 'invalid')),
    [endSession],
  )

  // Restore: confirm a stored token with GET /auth/me (on load, and on retry()).
  useEffect(() => {
    if (state.status !== 'restoring') return undefined
    const controller = new AbortController()
    fetchCurrentUser({ signal: controller.signal })
      .then((user) => setState({ status: 'authenticated', user, error: null, endedReason: null }))
      .catch((error) => {
        if (error.code === 'REQUEST_CANCELLED') return
        if (error.status === 401) return // the 401 handler has already ended the session
        // Network failure, timeout or server error: keep the token; the user can retry.
        setState({ status: 'error', user: null, error, endedReason: null })
      })
    return () => controller.abort()
  }, [state.status, checkCount])

  // Expiry: a timer for the exact moment, plus a re-check when the tab becomes active
  // again (browsers throttle timers in background tabs).
  useEffect(() => {
    if (state.status !== 'authenticated' && state.status !== 'error') return undefined
    const check = () => {
      const session = getSession()
      if (!session) endSession('invalid')
      else if (isExpired(session)) endSession('expired')
    }
    const session = getSession()
    const timer = session ? window.setTimeout(check, Math.max(0, session.expiresAt - Date.now())) : undefined
    if (!session) check()
    const onVisible = () => {
      if (document.visibilityState === 'visible') check()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', check)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', check)
    }
  }, [state.status, endSession])

  const login = useCallback(async ({ email, password }) => {
    const token = await requestAccessToken({ email, password })
    saveSession({ accessToken: token.access_token, expiresIn: token.expires_in })
    try {
      const user = await fetchCurrentUser()
      setState({ status: 'authenticated', user, error: null, endedReason: null })
      return user
    } catch (error) {
      clearSession()
      setState({ status: 'unauthenticated', user: null, error: null, endedReason: null })
      throw error
    }
  }, [])

  // Registration does not sign in: the page sends the user to sign in (P-8 decision).
  const register = useCallback((details) => registerAccount(details), [])

  const logout = useCallback(() => endSession('signedOut'), [endSession])

  const retry = useCallback(() => {
    if (!getSession()) {
      endSession('invalid')
      return
    }
    setState((current) => ({ ...current, status: 'restoring', error: null }))
    setCheckCount((n) => n + 1)
  }, [endSession])

  const value = useMemo(() => ({ ...state, login, register, logout, retry }), [state, login, register, logout, retry])

  return <AuthContext value={value}>{children}</AuthContext>
}
