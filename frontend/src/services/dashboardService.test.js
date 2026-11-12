import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useDashboardSummary } from '../hooks/useDashboardSummary'
import { SUMMARY_RESPONSE } from '../test/dashboardFixtures'
import { errorBody, fakeAdapter, networkFailure } from '../test/fakeAdapter'
import { apiClient, setUnauthorizedHandler } from './apiClient'
import * as dashboardService from './dashboardService'
import { getDashboardSummary, parseDashboardSummary, TRANSACTION_STATUSES } from './dashboardService'
import { clearSession, getSession, saveSession } from './tokenStore'


let originalAdapter
let adapter

function serve(handler) {
  adapter = fakeAdapter(handler)
  apiClient.defaults.adapter = adapter
}

beforeEach(() => {
  originalAdapter = apiClient.defaults.adapter
})

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter
  setUnauthorizedHandler(null)
  clearSession()
})

describe('getDashboardSummary', () => {
  it('calls GET /dashboard/summary with the bearer token and maps the response', async () => {
    saveSession({ accessToken: 'tok-1', expiresIn: 60 })
    serve(() => [200, SUMMARY_RESPONSE])
    const summary = await getDashboardSummary()
    const [request] = adapter.requests
    expect(request.method).toBe('get')
    expect(request.url).toBe('/dashboard/summary')
    expect(request.headers.get('Authorization')).toBe('Bearer tok-1')
    expect(summary).toEqual({
      period: SUMMARY_RESPONSE.period,
      total: 10,
      byStatus: SUMMARY_RESPONSE.transactions.by_status,
      awaitingAction: 1,
      approvedAmountPaise: 4_459_000,
      unreadAlerts: 3,
    })
  })

  it('a 401 ends the session (P-8 behaviour) and rejects', async () => {
    saveSession({ accessToken: 'tok-1', expiresIn: 60 })
    const unauthorized = vi.fn()
    setUnauthorizedHandler(unauthorized)
    serve(() => [401, errorBody('TOKEN_EXPIRED', 'Expired.')])
    await expect(getDashboardSummary()).rejects.toMatchObject({ code: 'TOKEN_EXPIRED' })
    expect(getSession()).toBeNull()
    expect(unauthorized).toHaveBeenCalledOnce()
  })

  it.each([
    ['a server error', () => [503, errorBody('DATABASE_UNAVAILABLE', 'Later.')], 'DATABASE_UNAVAILABLE'],
    ['a network failure', networkFailure(), 'NETWORK_ERROR'],
  ])('%s rejects and keeps the session', async (_label, handler, code) => {
    saveSession({ accessToken: 'tok-1', expiresIn: 60 })
    serve(handler)
    await expect(getDashboardSummary()).rejects.toMatchObject({ code })
    expect(getSession()).not.toBeNull()
  })
})

describe('parseDashboardSummary never invents figures', () => {
  const withChange = (change) => {
    const copy = structuredClone(SUMMARY_RESPONSE)
    change(copy)
    return copy
  }

  it('keeps zero values', () => {
    const zero = withChange((d) => {
      d.transactions = { total: 0, by_status: Object.fromEntries(TRANSACTION_STATUSES.map((s) => [s, 0])), awaiting_action: 0, approved_amount_paise: 0 }
      d.alerts.unread = 0
    })
    expect(parseDashboardSummary(zero)).toMatchObject({ total: 0, approvedAmountPaise: 0, unreadAlerts: 0 })
  })

  it.each([
    ['no body', () => null],
    ['missing status key', (d) => delete d.transactions.by_status.FAILED],
    ['negative count', (d) => (d.transactions.total = -1)],
    ['fractional paise', (d) => (d.transactions.approved_amount_paise = 12.5)],
    ['amount as a string', (d) => (d.transactions.approved_amount_paise = '4459000')],
    ['missing unread count', (d) => delete d.alerts],
    ['different window', (d) => (d.period.days = 7)],
    ['bad date', (d) => (d.period.end = 'yesterday')],
  ])('rejects a response with %s', (_label, change) => {
    const data = change.length ? withChange(change) : change()
    expect(() => parseDashboardSummary(data)).toThrow(expect.objectContaining({ code: 'INVALID_RESPONSE' }))
  })

  it('ignores extra fields (such as future risk statistics) without showing them', () => {
    const extra = withChange((d) => (d.risk_levels = { LOW: 5 }))
    expect(parseDashboardSummary(extra)).not.toHaveProperty('risk_levels')
  })
})

describe('useDashboardSummary', () => {
  it('loads, then is ready', async () => {
    vi.spyOn(dashboardService, 'getDashboardSummary').mockResolvedValue(parseDashboardSummary(SUMMARY_RESPONSE))
    const { result } = renderHook(() => useDashboardSummary())
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.summary.total).toBe(10)
  })

  it('reports errors and retries', async () => {
    const error = { code: 'NETWORK_ERROR', message: 'Could not reach the server.' }
    const get = vi
      .spyOn(dashboardService, 'getDashboardSummary')
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce(parseDashboardSummary(SUMMARY_RESPONSE))
    const { result } = renderHook(() => useDashboardSummary())
    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.error).toBe(error)
    act(() => result.current.retry())
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('aborts the request on unmount and ignores the cancellation', async () => {
    let signal
    vi.spyOn(dashboardService, 'getDashboardSummary').mockImplementation((options) => {
      signal = options.signal
      return new Promise(() => {})
    })
    const { result, unmount } = renderHook(() => useDashboardSummary())
    expect(signal.aborted).toBe(false)
    unmount()
    expect(signal.aborted).toBe(true)
    expect(result.current.status).toBe('loading')
  })
})
