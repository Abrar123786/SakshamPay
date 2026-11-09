import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { env } from '../utils/env'
import { errorBody, fakeAdapter } from '../test/fakeAdapter'
import { apiClient, setUnauthorizedHandler } from './apiClient'
import { AUTH_PATHS, fetchCurrentUser, registerAccount, requestAccessToken } from './authService'
import { getHealth } from './systemService'
import { clearSession, getSession, saveSession } from './tokenStore'

const PROFILE = {
  id: '9f1c2a5e-0000-4000-8000-000000000001',
  full_name: 'Asha Rao',
  email: 'asha@example.com',
  phone_number: '+919876543210',
  is_active: true,
  created_at: '2026-11-09T10:00:00Z',
}
const TOKEN_RESPONSE = { access_token: 'tok-123', token_type: 'bearer', expires_in: 1800, expires_at: '2026-11-09T10:30:00Z' }

let originalAdapter
let adapter
let unauthorized

function serve(handler) {
  adapter = fakeAdapter(handler)
  apiClient.defaults.adapter = adapter
}

function authHeader(config) {
  return config.headers.get('Authorization')
}

beforeEach(() => {
  originalAdapter = apiClient.defaults.adapter
  unauthorized = vi.fn()
  setUnauthorizedHandler(unauthorized)
})

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter
  setUnauthorizedHandler(null)
  clearSession()
})

describe('authService uses only the P-6 endpoints', () => {
  it('has exactly register, login and me', () => {
    expect(AUTH_PATHS).toEqual({ register: '/auth/register', login: '/auth/login', me: '/auth/me' })
  })

  it('register posts only the allowed keys (no confirmPassword) and sends no token', async () => {
    saveSession({ accessToken: 'stale', expiresIn: 60 })
    serve(() => [201, PROFILE])
    const profile = await registerAccount({
      fullName: 'Asha Rao',
      email: 'asha@example.com',
      phoneNumber: '+919876543210',
      password: 'a-long-passphrase',
      confirmPassword: 'a-long-passphrase',
    })
    const [request] = adapter.requests
    expect(request.method).toBe('post')
    expect(request.url).toBe('/auth/register')
    expect(JSON.parse(request.data)).toEqual({
      full_name: 'Asha Rao',
      email: 'asha@example.com',
      phone_number: '+919876543210',
      password: 'a-long-passphrase',
    })
    expect(authHeader(request)).toBeFalsy()
    expect(profile).toEqual(PROFILE)
  })

  it('register sends null for an empty phone number', async () => {
    serve(() => [201, PROFILE])
    await registerAccount({ fullName: 'A', email: 'a@b.co', phoneNumber: '', password: 'x'.repeat(10) })
    expect(JSON.parse(adapter.requests[0].data).phone_number).toBeNull()
  })

  it('login posts email and password only, with no token', async () => {
    saveSession({ accessToken: 'stale', expiresIn: 60 })
    serve(() => [200, TOKEN_RESPONSE])
    const token = await requestAccessToken({ email: 'asha@example.com', password: 'secret-pass' })
    expect(JSON.parse(adapter.requests[0].data)).toEqual({ email: 'asha@example.com', password: 'secret-pass' })
    expect(authHeader(adapter.requests[0])).toBeFalsy()
    expect(token).toEqual(TOKEN_RESPONSE)
  })

  it('a failed login does not end the session handler (INVALID_CREDENTIALS is not a token failure)', async () => {
    serve(() => [401, errorBody('INVALID_CREDENTIALS', 'Invalid email or password.')])
    await expect(requestAccessToken({ email: 'a@b.co', password: 'nope' })).rejects.toMatchObject({ code: 'INVALID_CREDENTIALS' })
    expect(unauthorized).not.toHaveBeenCalled()
  })
})

describe('bearer token handling', () => {
  it('attaches the stored token to API requests', async () => {
    saveSession({ accessToken: 'tok-123', expiresIn: 60 })
    serve(() => [200, PROFILE])
    await fetchCurrentUser()
    expect(authHeader(adapter.requests[0])).toBe('Bearer tok-123')
  })

  it('sends no Authorization header when signed out', async () => {
    serve(() => [401, errorBody('NOT_AUTHENTICATED', 'Authentication is required.')])
    await expect(fetchCurrentUser()).rejects.toMatchObject({ status: 401 })
    expect(authHeader(adapter.requests[0])).toBeFalsy()
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it('never sends the token to /health (outside /api/v1)', async () => {
    saveSession({ accessToken: 'tok-123', expiresIn: 60 })
    serve(() => [200, { status: 'healthy' }])
    await getHealth()
    expect(adapter.requests[0].url).toBe(`${env.apiOrigin}/health`)
    expect(authHeader(adapter.requests[0])).toBeFalsy()
  })

  it('never sends the token to another origin', async () => {
    saveSession({ accessToken: 'tok-123', expiresIn: 60 })
    serve(() => [200, {}])
    await apiClient.get('https://evil.example/api/v1/auth/me')
    expect(authHeader(adapter.requests[0])).toBeFalsy()
  })

  it('does not send an expired token, clears it and reports the expiry', async () => {
    saveSession({ accessToken: 'old', expiresIn: 60 }, Date.now() - 61_000)
    serve(() => [401, errorBody('NOT_AUTHENTICATED', 'Authentication is required.')])
    await expect(fetchCurrentUser()).rejects.toMatchObject({ status: 401 })
    expect(authHeader(adapter.requests[0])).toBeFalsy()
    expect(getSession()).toBeNull()
    expect(unauthorized).toHaveBeenCalledWith(expect.objectContaining({ code: 'TOKEN_EXPIRED' }))
  })

  it.each(['TOKEN_EXPIRED', 'INVALID_TOKEN'])('a 401 %s on an authenticated request clears the session', async (code) => {
    saveSession({ accessToken: 'tok-123', expiresIn: 60 })
    serve(() => [401, errorBody(code, 'No.')])
    await expect(fetchCurrentUser()).rejects.toMatchObject({ code })
    expect(getSession()).toBeNull()
    expect(unauthorized).toHaveBeenCalledWith(expect.objectContaining({ code }))
  })

  it.each([
    [503, 'DATABASE_UNAVAILABLE'],
    [500, 'INTERNAL_ERROR'],
  ])('a %s error keeps the session', async (status, code) => {
    saveSession({ accessToken: 'tok-123', expiresIn: 60 })
    serve(() => [status, errorBody(code, 'Later.')])
    await expect(fetchCurrentUser()).rejects.toMatchObject({ code })
    expect(getSession()).not.toBeNull()
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it('a network failure keeps the session', async () => {
    saveSession({ accessToken: 'tok-123', expiresIn: 60 })
    apiClient.defaults.adapter = fakeAdapter(() => {
      throw Object.assign(new Error('Network Error'), { isAxiosError: true, code: 'ERR_NETWORK' })
    })
    await expect(fetchCurrentUser()).rejects.toMatchObject({ code: 'NETWORK_ERROR' })
    expect(getSession()).not.toBeNull()
    expect(unauthorized).not.toHaveBeenCalled()
  })
})
