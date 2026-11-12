import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../services/apiClient'
import * as authService from '../../services/authService'
import * as dashboardService from '../../services/dashboardService'
import * as systemService from '../../services/systemService'
import { getSession, saveSession } from '../../services/tokenStore'
import { renderApp, TEST_TOKEN, TEST_USER } from '../../test/renderApp'

beforeEach(() => {
  vi.spyOn(systemService, 'getHealth').mockReturnValue(new Promise(() => {}))
  // P-9: signing in now lands on the dashboard; keep its request off the network.
  vi.spyOn(dashboardService, 'getDashboardSummary').mockReturnValue(new Promise(() => {}))
})

const signIn = async (user, { email = 'asha@example.com', password = 'a-long-passphrase' } = {}) => {
  await user.type(screen.getByLabelText('Email address'), email)
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('protected pages', () => {
  it('a signed-out visitor to /account is sent to sign in', async () => {
    const app = renderApp('/account')
    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument()
    expect(app.pathname()).toBe('/login')
  })

  it('after signing in, the user returns to the page they asked for', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'requestAccessToken').mockResolvedValue(TEST_TOKEN)
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(TEST_USER)
    const app = renderApp('/account')
    await screen.findByRole('heading', { name: 'Sign in' })
    await signIn(user)
    expect(await screen.findByRole('heading', { level: 1, name: 'Your account' })).toBeInTheDocument()
    expect(app.pathname()).toBe('/account')
  })

  it('signing in from /login goes to the default signed-in page', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'requestAccessToken').mockResolvedValue(TEST_TOKEN)
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(TEST_USER)
    const app = renderApp('/login')
    await signIn(user)
    // P-9: the default signed-in page is the dashboard (was /account in P-8).
    await screen.findByRole('heading', { level: 1, name: 'Welcome back, Asha' })
    expect(app.pathname()).toBe('/dashboard')
  })

  it('shows a loading state while the stored session is checked, then the page', async () => {
    saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
    let resolve
    vi.spyOn(authService, 'fetchCurrentUser').mockReturnValue(new Promise((r) => (resolve = r)))
    const app = renderApp('/account')
    expect(screen.getByRole('status')).toHaveTextContent('Checking your session')
    resolve(TEST_USER)
    expect(await screen.findByRole('heading', { name: 'Your account' })).toBeInTheDocument()
    expect(app.pathname()).toBe('/account')
  })

  it('a refresh with a valid stored token restores the session (no sign-in needed)', async () => {
    saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(TEST_USER)
    renderApp('/account')
    expect(await screen.findByText('asha@example.com', { selector: 'dd' })).toBeInTheDocument()
  })

  it('an expired stored token sends the user to sign in with an explanation', async () => {
    saveSession({ accessToken: 'tok-old', expiresIn: 60 }, Date.now() - 120_000)
    const app = renderApp('/account')
    expect(await screen.findByText('Your session expired. Please sign in again.')).toBeInTheDocument()
    expect(app.pathname()).toBe('/login')
    expect(getSession()).toBeNull()
  })

  it('a temporary failure keeps the session and offers a retry', async () => {
    const user = userEvent.setup()
    saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
    vi.spyOn(authService, 'fetchCurrentUser')
      .mockRejectedValueOnce(new ApiError({ status: 0, code: 'TIMEOUT', message: 'The server took too long to respond.' }))
      .mockResolvedValueOnce(TEST_USER)
    const app = renderApp('/account')
    expect(await screen.findByRole('heading', { level: 1, name: "We couldn't confirm your session" })).toBeInTheDocument()
    expect(screen.getByText('The server took too long to respond.')).toBeInTheDocument()
    expect(getSession()).not.toBeNull()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'Your account' })).toBeInTheDocument()
    expect(app.pathname()).toBe('/account')
  })

  it('from the retry screen the user can sign out instead', async () => {
    const user = userEvent.setup()
    saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
    vi.spyOn(authService, 'fetchCurrentUser').mockRejectedValue(new ApiError({ status: 503, code: 'DATABASE_UNAVAILABLE', message: 'Later.' }))
    const app = renderApp('/account')
    await user.click(await screen.findByRole('button', { name: 'Sign out instead' }))
    expect(await screen.findByText('You have signed out.')).toBeInTheDocument()
    expect(app.pathname()).toBe('/login')
    expect(getSession()).toBeNull()
  })
})

describe('sign-in and registration pages for signed-in users', () => {
  beforeEach(() => {
    saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(TEST_USER)
  })

  it.each(['/login', '/register'])('%s redirects to the default page (P-9: the dashboard)', async (path) => {
    const app = renderApp(path)
    expect(await screen.findByRole('heading', { name: 'Welcome back, Asha' })).toBeInTheDocument()
    expect(app.pathname()).toBe('/dashboard')
  })
})

describe('signing out', () => {
  it('clears the session and lands on sign-in without a return path', async () => {
    const user = userEvent.setup()
    saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(TEST_USER)
    const app = renderApp('/account')
    await screen.findByRole('heading', { name: 'Your account' })

    // Header and page both offer sign-out; use the page's.
    await user.click(within(screen.getByRole('main')).getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByText('You have signed out.')).toBeInTheDocument()
    expect(app.pathname()).toBe('/login')
    expect(getSession()).toBeNull()
    expect(app.router.state.location.state).toBeNull()
  })

  it('the header switches between sign-in actions and the main navigation', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'requestAccessToken').mockResolvedValue(TEST_TOKEN)
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(TEST_USER)
    renderApp('/login')
    expect(screen.getByRole('navigation', { name: 'Account' })).toHaveTextContent('Sign in')
    await signIn(user)
    await screen.findByRole('heading', { name: 'Welcome back, Asha' })
    // P-9: signed-in users get the main navigation (Dashboard, Account) and Sign out.
    expect(screen.queryByRole('navigation', { name: 'Account' })).not.toBeInTheDocument()
    const main = screen.getByRole('navigation', { name: 'Main' })
    expect(within(main).getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page')
    expect(within(main).getByRole('link', { name: 'Account' })).not.toHaveAttribute('aria-current')
    await user.click(screen.getByRole('button', { name: 'Sign out' })) // the only one on the dashboard: the header's
    expect(await screen.findByText('You have signed out.')).toBeInTheDocument()
  })
})

describe('public pages are not blocked by the session check', () => {
  it('home renders while a stored session is still being checked', () => {
    saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
    vi.spyOn(authService, 'fetchCurrentUser').mockReturnValue(new Promise(() => {}))
    renderApp('/')
    expect(screen.getByRole('heading', { level: 1, name: 'Check a payment before it leaves.' })).toBeInTheDocument()
  })

  it('unknown paths still show the 404 page', () => {
    renderApp('/no-such-page')
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})
