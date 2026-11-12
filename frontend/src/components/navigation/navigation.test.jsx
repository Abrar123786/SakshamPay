import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as authService from '../../services/authService'
import * as dashboardService from '../../services/dashboardService'
import * as systemService from '../../services/systemService'
import { getSession, saveSession } from '../../services/tokenStore'
import { renderApp, TEST_USER } from '../../test/renderApp'
import { SIGNED_IN_NAV_ITEMS } from './navItems'

beforeEach(() => {
  vi.spyOn(systemService, 'getHealth').mockReturnValue(new Promise(() => {}))
  vi.spyOn(dashboardService, 'getDashboardSummary').mockReturnValue(new Promise(() => {}))
  saveSession({ accessToken: 'tok-stored', expiresIn: 1800 })
  vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(TEST_USER)
})

const menuButton = () => screen.getByRole('button', { name: 'Menu' })

async function openApp(path = '/dashboard') {
  const app = renderApp(path)
  await screen.findByRole('heading', { level: 1 })
  return app
}

describe('navigation items', () => {
  it('lists Dashboard then Account, each pointing at a real route', () => {
    expect(SIGNED_IN_NAV_ITEMS.map((item) => [item.label, item.to])).toEqual([
      ['Dashboard', '/dashboard'],
      ['Account', '/account'],
    ])
  })
})

describe('desktop navigation', () => {
  it('marks the current page with aria-current', async () => {
    const user = userEvent.setup()
    const app = await openApp('/dashboard')
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Dashboard' })).toHaveAttribute('aria-current', 'page')

    await user.click(within(nav).getByRole('link', { name: 'Account' }))
    await screen.findByRole('heading', { name: 'Your account' })
    expect(app.pathname()).toBe('/account')
    expect(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Account' })).toHaveAttribute('aria-current', 'page')
    expect(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Dashboard' })).not.toHaveAttribute('aria-current')
  })

  it('the logo goes to the dashboard when signed in', async () => {
    await openApp('/account')
    expect(screen.getByRole('link', { name: 'SakshamPay home' })).toHaveAttribute('href', '/dashboard')
  })
})

describe('phone menu', () => {
  it('is a disclosure button that starts closed', async () => {
    await openApp()
    expect(menuButton()).toHaveAttribute('aria-expanded', 'false')
    expect(menuButton()).toHaveAttribute('aria-controls', 'signed-in-menu')
    expect(document.getElementById('signed-in-menu')).toBeNull()
  })

  it('opens a panel with the links, the signed-in email and Sign out', async () => {
    const user = userEvent.setup()
    await openApp()
    await user.click(menuButton())
    expect(menuButton()).toHaveAttribute('aria-expanded', 'true')
    const panel = document.getElementById('signed-in-menu')
    const nav = within(panel).getByRole('navigation', { name: 'Main' })
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual(['Dashboard', 'Account'])
    expect(within(panel).getByText('Signed in as asha@example.com')).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  })

  it('is fully usable with the keyboard; Escape closes it and returns focus to the button', async () => {
    const user = userEvent.setup()
    await openApp()
    menuButton().focus()
    await user.keyboard('{Enter}')
    expect(menuButton()).toHaveAttribute('aria-expanded', 'true')
    await user.tab()
    expect(within(document.getElementById('signed-in-menu')).getByRole('link', { name: 'Dashboard' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(document.getElementById('signed-in-menu')).toBeNull()
    expect(menuButton()).toHaveFocus()
    expect(menuButton()).toHaveAttribute('aria-expanded', 'false')
  })

  it('closes after navigating', async () => {
    const user = userEvent.setup()
    const app = await openApp()
    await user.click(menuButton())
    await user.click(within(document.getElementById('signed-in-menu')).getByRole('link', { name: 'Account' }))
    await screen.findByRole('heading', { name: 'Your account' })
    expect(app.pathname()).toBe('/account')
    expect(document.getElementById('signed-in-menu')).toBeNull()
  })

  it('closes on a click outside', async () => {
    const user = userEvent.setup()
    await openApp()
    await user.click(menuButton())
    await user.click(screen.getByRole('heading', { level: 1 }))
    expect(document.getElementById('signed-in-menu')).toBeNull()
  })

  it('a second press closes it', async () => {
    const user = userEvent.setup()
    await openApp()
    await user.click(menuButton())
    await user.click(menuButton())
    expect(menuButton()).toHaveAttribute('aria-expanded', 'false')
  })

  it('Sign out in the menu signs out', async () => {
    const user = userEvent.setup()
    const app = await openApp()
    await user.click(menuButton())
    await user.click(within(document.getElementById('signed-in-menu')).getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByText('You have signed out.')).toBeInTheDocument()
    expect(app.pathname()).toBe('/login')
    expect(getSession()).toBeNull()
  })
})

describe('signed-out header is unchanged from P-8', () => {
  it('shows Sign in and Create account, and no main navigation', () => {
    sessionStorage.clear()
    renderApp('/login')
    const nav = screen.getByRole('navigation', { name: 'Account' })
    expect(within(nav).getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
    expect(within(nav).getByRole('link', { name: 'Create account' })).toHaveAttribute('href', '/register')
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'SakshamPay home' })).toHaveAttribute('href', '/')
  })
})
