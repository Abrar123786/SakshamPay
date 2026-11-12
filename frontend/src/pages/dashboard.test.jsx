import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { STATUS_LABELS } from '../components/dashboard/statusLabels'
import { ApiError, apiClient } from '../services/apiClient'
import * as authService from '../services/authService'
import * as dashboardService from '../services/dashboardService'
import { parseDashboardSummary, TRANSACTION_STATUSES } from '../services/dashboardService'
import * as systemService from '../services/systemService'
import { getSession, saveSession } from '../services/tokenStore'
import { EMPTY_SUMMARY_RESPONSE, SUMMARY_RESPONSE } from '../test/dashboardFixtures'
import { errorBody, fakeAdapter } from '../test/fakeAdapter'
import { renderApp, TEST_USER } from '../test/renderApp'
import { formatDate, formatNumber } from '../utils/format'

const summary = (response = SUMMARY_RESPONSE) => parseDashboardSummary(structuredClone(response))
const withChange = (change) => {
  const copy = structuredClone(SUMMARY_RESPONSE)
  change(copy)
  return copy
}

beforeEach(() => {
  vi.spyOn(systemService, 'getHealth').mockReturnValue(new Promise(() => {}))
  saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
  vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(TEST_USER)
})

async function openDashboard() {
  const app = renderApp('/dashboard')
  await screen.findByRole('heading', { level: 1, name: 'Welcome back, Asha' })
  return app
}

function figure(label) {
  const term = within(screen.getByRole('region', { name: 'Last 30 days' })).getByText(label, { selector: 'dt' })
  const [value, note] = term.parentElement.querySelectorAll('dd')
  return { value: value.textContent, note: note.textContent }
}

describe('populated dashboard', () => {
  beforeEach(() => {
    vi.spyOn(dashboardService, 'getDashboardSummary').mockResolvedValue(summary())
  })

  it('shows the page title and a single h1', async () => {
    await openDashboard()
    expect(document.title).toBe('Dashboard · SakshamPay')
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })

  it('shows the four key figures with Indian formatting', async () => {
    await openDashboard()
    await screen.findByRole('region', { name: 'Last 30 days' })
    expect(figure('Payments checked')).toEqual({ value: '10', note: 'Submitted in the last 30 days' })
    expect(figure('Approved amount')).toEqual({ value: '₹44,590.00', note: '7 approved payments · simulated' })
    expect(figure('Needs your action')).toEqual({ value: '1', note: 'Waiting for your decision' })
    expect(figure('Unread alerts')).toEqual({ value: '3', note: 'All time' })
  })

  it('shows the 30-day window as dates', async () => {
    await openDashboard()
    const region = await screen.findByRole('region', { name: 'Last 30 days' })
    expect(region).toHaveTextContent(/10 Oct – 9 Nov 2026|11 Oct – 10 Nov 2026/) // depends on the viewer's time zone
  })

  it('shows every stored status in lifecycle order, including zeros', async () => {
    await openDashboard()
    const region = await screen.findByRole('region', { name: 'Payments by status' })
    const rows = [...region.querySelectorAll('dt')].map((dt) => [dt.textContent, dt.nextElementSibling.textContent])
    expect(rows).toEqual(TRANSACTION_STATUSES.map((s) => [STATUS_LABELS[s], String(SUMMARY_RESPONSE.transactions.by_status[s])]))
  })

  it('bars are decorative and proportional', async () => {
    await openDashboard()
    const region = await screen.findByRole('region', { name: 'Payments by status' })
    const bars = region.querySelectorAll('dd[aria-hidden="true"] > div')
    expect(bars).toHaveLength(7)
    expect(bars[3].style.width).toBe('70%') // APPROVED: 7 of 10
    expect(bars[0].style.width).toBe('0%')
  })

  it('formats large values with Indian grouping', async () => {
    dashboardService.getDashboardSummary.mockResolvedValue(
      summary(withChange((d) => {
        d.transactions.total = 1_234_567
        d.transactions.by_status.APPROVED = 1_234_566
        d.transactions.approved_amount_paise = 12_34_56_789_00
      })),
    )
    await openDashboard()
    await screen.findByRole('region', { name: 'Last 30 days' })
    expect(figure('Payments checked').value).toBe('12,34,567')
    expect(figure('Approved amount').value).toBe('₹12,34,56,789.00')
  })

  it('uses singular wording for one approved payment and nothing waiting', async () => {
    dashboardService.getDashboardSummary.mockResolvedValue(
      summary(withChange((d) => {
        d.transactions = { total: 1, by_status: { ...EMPTY_SUMMARY_RESPONSE.transactions.by_status, APPROVED: 1 }, awaiting_action: 0, approved_amount_paise: 50_000 }
      })),
    )
    await openDashboard()
    await screen.findByRole('region', { name: 'Last 30 days' })
    expect(figure('Approved amount')).toEqual({ value: '₹500.00', note: '1 approved payment · simulated' })
    expect(figure('Needs your action')).toEqual({ value: '0', note: 'Nothing waiting' })
  })

  it('explains payments that passed their decision deadline but are not yet expired', async () => {
    dashboardService.getDashboardSummary.mockResolvedValue(
      summary(withChange((d) => {
        d.transactions.by_status.AWAITING_USER_ACTION = 3
        d.transactions.total = 12
        d.transactions.awaiting_action = 1
      })),
    )
    await openDashboard()
    expect(await screen.findByText('2 payments awaiting your decision have passed their deadline and will be marked as expired.')).toBeInTheDocument()
    expect(figure('Needs your action').value).toBe('1')
  })

  it('has no risk statistics, recent transactions or new-payment action (later phases)', async () => {
    await openDashboard()
    await screen.findByRole('region', { name: 'Last 30 days' })
    const main = screen.getByRole('main')
    expect(main).not.toHaveTextContent(/low risk|medium risk|high risk|risk score/i)
    expect(main.innerHTML).not.toMatch(/risk-(low|medium|high)/)
    expect(within(main).queryByRole('table')).not.toBeInTheDocument()
    expect(within(main).queryByRole('link')).not.toBeInTheDocument()
    expect(within(main).queryByRole('button')).not.toBeInTheDocument()
  })
})

describe('new user (no payments)', () => {
  it('shows the empty state, no figures and no zero-filled breakdown', async () => {
    vi.spyOn(dashboardService, 'getDashboardSummary').mockResolvedValue(summary(EMPTY_SUMMARY_RESPONSE))
    await openDashboard()
    expect(await screen.findByRole('region', { name: 'No payments in the last 30 days' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Last 30 days' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Payments by status' })).not.toBeInTheDocument()
    expect(screen.queryByText(/unread alert/)).not.toBeInTheDocument()
  })

  it('still mentions unread alerts if there are any', async () => {
    vi.spyOn(dashboardService, 'getDashboardSummary').mockResolvedValue(summary(withChange((d) => {
      d.transactions = structuredClone(EMPTY_SUMMARY_RESPONSE.transactions)
      d.alerts.unread = 2
    })))
    await openDashboard()
    expect(await screen.findByText('You have 2 unread alerts.')).toBeInTheDocument()
  })
})

describe('loading, errors and retry', () => {
  it('shows a skeleton with a screen-reader status while loading', async () => {
    vi.spyOn(dashboardService, 'getDashboardSummary').mockReturnValue(new Promise(() => {}))
    await openDashboard()
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('Loading your summary')
    expect(status.parentElement).toHaveAttribute('aria-busy', 'true')
    expect(screen.queryByRole('region', { name: 'Last 30 days' })).not.toBeInTheDocument()
  })

  it.each([
    [new ApiError({ status: 0, code: 'NETWORK_ERROR', message: 'Could not reach the SakshamPay server.' }), false],
    [new ApiError({ status: 503, code: 'DATABASE_UNAVAILABLE', message: 'The database is temporarily unavailable.', requestId: 'req-9' }), true],
    [new ApiError({ status: 200, code: 'INVALID_RESPONSE', message: 'The dashboard summary could not be read. Please try again.' }), false],
  ])('shows an error with retry (%s), keeps the session, and recovers', async (error, hasReference) => {
    const user = userEvent.setup()
    vi.spyOn(dashboardService, 'getDashboardSummary').mockRejectedValueOnce(error).mockResolvedValueOnce(summary())
    await openDashboard()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("We couldn't load your summary")
    expect(alert).toHaveTextContent(error.message)
    expect(alert.textContent.includes('req-9')).toBe(hasReference)
    expect(getSession()).not.toBeNull()

    await user.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('region', { name: 'Last 30 days' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

describe('protected routing', () => {
  let originalAdapter
  beforeEach(() => {
    originalAdapter = apiClient.defaults.adapter
  })
  afterEach(() => {
    apiClient.defaults.adapter = originalAdapter
  })

  it('signed-out visitors are sent to sign in, then return to the dashboard', async () => {
    sessionStorage.clear()
    const user = userEvent.setup()
    vi.spyOn(dashboardService, 'getDashboardSummary').mockResolvedValue(summary())
    vi.spyOn(authService, 'requestAccessToken').mockResolvedValue({ access_token: 't', token_type: 'bearer', expires_in: 1800, expires_at: '2026-11-09T10:30:00Z' })
    const app = renderApp('/dashboard')
    await screen.findByRole('heading', { name: 'Sign in' })
    expect(app.pathname()).toBe('/login')
    await user.type(screen.getByLabelText('Email address'), 'asha@example.com')
    await user.type(screen.getByLabelText('Password'), 'a-long-passphrase')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('heading', { name: 'Welcome back, Asha' })
    expect(app.pathname()).toBe('/dashboard')
  })

  it('a 401 from the summary ends the session and returns to sign in (real API client)', async () => {
    apiClient.defaults.adapter = fakeAdapter(() => [401, errorBody('TOKEN_EXPIRED', 'The access token has expired. Please sign in again.')])
    const app = renderApp('/dashboard')
    expect(await screen.findByText('Your session expired. Please sign in again.')).toBeInTheDocument()
    expect(app.pathname()).toBe('/login')
    expect(getSession()).toBeNull()
  })

  it('the summary request is aborted when the user signs out', async () => {
    const user = userEvent.setup()
    let signal
    vi.spyOn(dashboardService, 'getDashboardSummary').mockImplementation((options) => {
      signal = options.signal
      return new Promise(() => {})
    })
    await openDashboard()
    await user.click(screen.getAllByRole('button', { name: 'Sign out' })[0])
    await screen.findByText('You have signed out.')
    await waitFor(() => expect(signal.aborted).toBe(true))
  })
})

describe('format helpers', () => {
  it('formatNumber uses Indian grouping and rejects non-integers', () => {
    expect(formatNumber(0)).toBe('0')
    expect(formatNumber(1_234_567)).toBe('12,34,567')
    expect(() => formatNumber(1.5)).toThrow(TypeError)
  })

  it('formatDate is unchanged', () => {
    expect(formatDate('2026-11-09T10:00:00Z')).toBe('9 November 2026')
  })
})
