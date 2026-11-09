import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiClient } from '../services/apiClient'
import * as authService from '../services/authService'
import { errorBody, fakeAdapter } from '../test/fakeAdapter'
import { getSession, SESSION_STORAGE_KEY, saveSession } from '../services/tokenStore'
import { SESSION_ENDED_MESSAGES, useAuth } from './authContext'
import AuthProvider from './AuthProvider'

const USER = { id: 'u-1', full_name: 'Asha Rao', email: 'asha@example.com', phone_number: null, is_active: true, created_at: '2026-11-09T10:00:00Z' }
const TOKEN = { access_token: 'tok-new', token_type: 'bearer', expires_in: 1800, expires_at: '2026-11-09T10:30:00Z' }

function Probe() {
  const auth = useAuth()
  return (
    <div>
      <p data-testid="status">{auth.status}</p>
      <p data-testid="user">{auth.user?.full_name ?? '-'}</p>
      <p data-testid="ended">{auth.endedReason ?? '-'}</p>
      <p data-testid="error">{auth.error?.code ?? '-'}</p>
      <button onClick={() => auth.login({ email: 'asha@example.com', password: 'pw-1234567890' }).catch(() => {})}>login</button>
      <button onClick={auth.logout}>logout</button>
      <button onClick={auth.retry}>retry</button>
    </div>
  )
}

function renderProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  )
}

const status = () => screen.getByTestId('status').textContent

const networkError = () => new ApiError({ status: 0, code: 'NETWORK_ERROR', message: 'Could not reach the server.' })

afterEach(() => {
  vi.useRealTimers()
})

describe('initial state', () => {
  it('is unauthenticated without a stored token, and does not call the API', () => {
    const me = vi.spyOn(authService, 'fetchCurrentUser')
    renderProvider()
    expect(status()).toBe('unauthenticated')
    expect(screen.getByTestId('ended')).toHaveTextContent('-')
    expect(me).not.toHaveBeenCalled()
  })

  it('clears an expired stored token without calling the API', () => {
    saveSession({ accessToken: 'old', expiresIn: 60 }, Date.now() - 120_000)
    const me = vi.spyOn(authService, 'fetchCurrentUser')
    renderProvider()
    expect(status()).toBe('unauthenticated')
    expect(screen.getByTestId('ended')).toHaveTextContent('expired')
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
    expect(me).not.toHaveBeenCalled()
  })

  it('throws a clear error when used outside the provider', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Probe />)).toThrow('useAuth() must be used inside <AuthProvider>.')
  })
})

describe('restoring a session on page load', () => {
  beforeEach(() => {
    saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
  })

  it('confirms the stored token with /auth/me and becomes authenticated', async () => {
    const me = vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(USER)
    renderProvider()
    expect(status()).toBe('restoring')
    await waitFor(() => expect(status()).toBe('authenticated'))
    expect(screen.getByTestId('user')).toHaveTextContent('Asha Rao')
    expect(me).toHaveBeenCalledOnce()
  })

  it('works under StrictMode (the first, aborted check is ignored)', async () => {
    vi.spyOn(authService, 'fetchCurrentUser').mockImplementation(({ signal }) =>
      new Promise((resolve, reject) => {
        const timer = setTimeout(() => resolve(USER), 5)
        signal?.addEventListener('abort', () => {
          clearTimeout(timer)
          reject(new ApiError({ status: 0, code: 'REQUEST_CANCELLED', message: 'cancelled' }))
        })
      }),
    )
    render(
      <StrictMode>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </StrictMode>,
    )
    await waitFor(() => expect(status()).toBe('authenticated'))
  })

  it.each(['INVALID_TOKEN', 'TOKEN_EXPIRED'])('a real 401 %s from /auth/me clears the token', async (code) => {
    const original = apiClient.defaults.adapter
    apiClient.defaults.adapter = fakeAdapter(() => [401, errorBody(code, 'No.')])
    try {
      renderProvider()
      await waitFor(() => expect(status()).toBe('unauthenticated'))
      expect(screen.getByTestId('ended')).toHaveTextContent(code === 'TOKEN_EXPIRED' ? 'expired' : 'invalid')
      expect(getSession()).toBeNull()
    } finally {
      apiClient.defaults.adapter = original
    }
  })

  it('a network failure keeps the token and offers a retry', async () => {
    const user = userEvent.setup()
    const me = vi.spyOn(authService, 'fetchCurrentUser').mockRejectedValueOnce(networkError()).mockResolvedValueOnce(USER)
    renderProvider()
    await waitFor(() => expect(status()).toBe('error'))
    expect(screen.getByTestId('error')).toHaveTextContent('NETWORK_ERROR')
    expect(getSession()).not.toBeNull()

    await user.click(screen.getByRole('button', { name: 'retry' }))
    await waitFor(() => expect(status()).toBe('authenticated'))
    expect(me).toHaveBeenCalledTimes(2)
  })

  it('a 503 also keeps the token', async () => {
    vi.spyOn(authService, 'fetchCurrentUser').mockRejectedValue(new ApiError({ status: 503, code: 'DATABASE_UNAVAILABLE', message: 'Later.' }))
    renderProvider()
    await waitFor(() => expect(status()).toBe('error'))
    expect(getSession()).not.toBeNull()
  })

  it('retry with no token left ends the session', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'fetchCurrentUser').mockRejectedValue(networkError())
    renderProvider()
    await waitFor(() => expect(status()).toBe('error'))
    sessionStorage.clear()
    await user.click(screen.getByRole('button', { name: 'retry' }))
    expect(status()).toBe('unauthenticated')
  })
})

describe('login and logout', () => {
  it('login stores the token, loads the profile and never stores the password', async () => {
    const user = userEvent.setup()
    const request = vi.spyOn(authService, 'requestAccessToken').mockResolvedValue(TOKEN)
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(USER)
    renderProvider()
    await user.click(screen.getByRole('button', { name: 'login' }))
    await waitFor(() => expect(status()).toBe('authenticated'))
    expect(request).toHaveBeenCalledWith({ email: 'asha@example.com', password: 'pw-1234567890' })
    expect(getSession().accessToken).toBe('tok-new')
    const everything = JSON.stringify({ ...sessionStorage }) + JSON.stringify({ ...localStorage })
    expect(everything).not.toContain('pw-1234567890')
    expect(everything).not.toContain('asha@example.com')
  })

  it('a failed login leaves the user signed out with nothing stored', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'requestAccessToken').mockRejectedValue(new ApiError({ status: 401, code: 'INVALID_CREDENTIALS', message: 'Invalid email or password.' }))
    renderProvider()
    await user.click(screen.getByRole('button', { name: 'login' }))
    expect(status()).toBe('unauthenticated')
    expect(getSession()).toBeNull()
  })

  it('if /auth/me fails right after login, the new token is discarded', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'requestAccessToken').mockResolvedValue(TOKEN)
    vi.spyOn(authService, 'fetchCurrentUser').mockRejectedValue(networkError())
    renderProvider()
    await user.click(screen.getByRole('button', { name: 'login' }))
    await waitFor(() => expect(getSession()).toBeNull())
    expect(status()).toBe('unauthenticated')
  })

  it('logout clears the token and the user', async () => {
    const user = userEvent.setup()
    saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(USER)
    renderProvider()
    await waitFor(() => expect(status()).toBe('authenticated'))
    await user.click(screen.getByRole('button', { name: 'logout' }))
    expect(status()).toBe('unauthenticated')
    expect(screen.getByTestId('user')).toHaveTextContent('-')
    expect(screen.getByTestId('ended')).toHaveTextContent('signedOut')
    expect(getSession()).toBeNull()
  })
})

describe('expiry while signed in', () => {
  it('ends the session exactly when the token expires', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    saveSession({ accessToken: 'tok-stored', expiresIn: 60 })
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(USER)
    renderProvider()
    await act(async () => {}) // resolve /auth/me
    expect(status()).toBe('authenticated')

    await act(async () => vi.advanceTimersByTime(59_000))
    expect(status()).toBe('authenticated')
    await act(async () => vi.advanceTimersByTime(1_000))
    expect(status()).toBe('unauthenticated')
    expect(screen.getByTestId('ended')).toHaveTextContent('expired')
    expect(getSession()).toBeNull()
  })

  it('re-checks when the tab becomes visible again (throttled timers)', async () => {
    saveSession({ accessToken: 'tok-stored', expiresIn: 60 })
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(USER)
    renderProvider()
    await waitFor(() => expect(status()).toBe('authenticated'))
    const later = Date.now() + 61_000
    vi.spyOn(Date, 'now').mockReturnValue(later)
    await act(async () => document.dispatchEvent(new Event('visibilitychange')))
    expect(status()).toBe('unauthenticated')
    expect(screen.getByTestId('ended')).toHaveTextContent('expired')
  })

  it('ends the session if the stored token disappears (e.g. cleared in DevTools)', async () => {
    saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(USER)
    renderProvider()
    await waitFor(() => expect(status()).toBe('authenticated'))
    sessionStorage.clear()
    await act(async () => window.dispatchEvent(new Event('focus')))
    expect(status()).toBe('unauthenticated')
    expect(screen.getByTestId('ended')).toHaveTextContent('invalid')
  })
})

describe('messages', () => {
  it('has a message for every way a session can end', () => {
    expect(Object.keys(SESSION_ENDED_MESSAGES).sort()).toEqual(['expired', 'invalid', 'signedOut'])
  })
})
