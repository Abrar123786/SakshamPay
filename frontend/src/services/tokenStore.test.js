import { afterEach, describe, expect, it, vi } from 'vitest'

import { clearSession, getSession, isExpired, SESSION_STORAGE_KEY, saveSession } from './tokenStore'

const NOW = Date.UTC(2026, 10, 9, 10, 0, 0)

afterEach(() => {
  vi.restoreAllMocks()
  clearSession()
})

describe('tokenStore', () => {
  it('saves to sessionStorage with an expiry computed from expires_in', () => {
    const session = saveSession({ accessToken: 'tok', expiresIn: 1800 }, NOW)
    expect(session).toEqual({ accessToken: 'tok', expiresAt: NOW + 1_800_000 })
    expect(JSON.parse(sessionStorage.getItem(SESSION_STORAGE_KEY))).toEqual(session)
    expect(getSession()).toEqual(session)
  })

  it('never writes to localStorage', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    saveSession({ accessToken: 'tok', expiresIn: 60 }, NOW)
    expect(setItem).toHaveBeenCalledTimes(1)
    expect(setItem.mock.contexts[0]).toBe(window.sessionStorage)
    expect(localStorage.length).toBe(0)
  })

  it('stores only the token and its expiry', () => {
    saveSession({ accessToken: 'tok', expiresIn: 60, password: 'never', user: { email: 'x' } }, NOW)
    expect(Object.keys(JSON.parse(sessionStorage.getItem(SESSION_STORAGE_KEY)))).toEqual(['accessToken', 'expiresAt'])
  })

  it('returns null when nothing is stored', () => {
    expect(getSession()).toBeNull()
  })

  it.each([
    ['not JSON', '{oops'],
    ['wrong shape', JSON.stringify({ token: 'x' })],
    ['empty token', JSON.stringify({ accessToken: '', expiresAt: NOW })],
    ['non-numeric expiry', JSON.stringify({ accessToken: 'x', expiresAt: 'soon' })],
    ['oversized token', JSON.stringify({ accessToken: 'x'.repeat(5000), expiresAt: NOW })],
  ])('deletes a malformed stored value (%s)', (_label, raw) => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, raw)
    expect(getSession()).toBeNull()
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
  })

  it('treats a session removed from storage as signed out (storage is the source of truth)', () => {
    saveSession({ accessToken: 'tok', expiresIn: 60 }, NOW)
    sessionStorage.removeItem(SESSION_STORAGE_KEY)
    expect(getSession()).toBeNull()
  })

  it('rejects invalid input', () => {
    expect(() => saveSession({ accessToken: '', expiresIn: 60 })).toThrow(TypeError)
    expect(() => saveSession({ accessToken: 'tok', expiresIn: 0 })).toThrow(TypeError)
    expect(() => saveSession({ accessToken: 'tok' })).toThrow(TypeError)
  })

  it('knows when a session has expired', () => {
    const session = saveSession({ accessToken: 'tok', expiresIn: 60 }, NOW)
    expect(isExpired(session, NOW + 59_999)).toBe(false)
    expect(isExpired(session, NOW + 60_000)).toBe(true)
    expect(isExpired(null)).toBe(true)
  })

  it('clears the session', () => {
    saveSession({ accessToken: 'tok', expiresIn: 60 }, NOW)
    clearSession()
    expect(getSession()).toBeNull()
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
  })

  it('falls back to memory when sessionStorage cannot be written', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError')
    })
    const session = saveSession({ accessToken: 'tok', expiresIn: 60 }, NOW)
    expect(getSession()).toEqual(session)
    clearSession()
    expect(getSession()).toBeNull()
  })
})
