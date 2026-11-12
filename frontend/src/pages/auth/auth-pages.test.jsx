import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import PasswordInput from '../../components/ui/PasswordInput'
import { ApiError } from '../../services/apiClient'
import * as authService from '../../services/authService'
import * as dashboardService from '../../services/dashboardService'
import * as systemService from '../../services/systemService'
import { getSession, saveSession } from '../../services/tokenStore'
import { renderApp, TEST_TOKEN, TEST_USER } from '../../test/renderApp'
import { MESSAGES } from '../../utils/authValidation'

const PASSWORD = 'a-long-passphrase'

beforeEach(() => {
  vi.spyOn(systemService, 'getHealth').mockReturnValue(new Promise(() => {}))
  // P-9: signing in now lands on the dashboard; keep its request off the network.
  vi.spyOn(dashboardService, 'getDashboardSummary').mockReturnValue(new Promise(() => {}))
})

const apiError = (status, code, message, extra = {}) => new ApiError({ status, code, message, requestId: 'req-42', ...extra })

describe('PasswordInput', () => {
  it('toggles visibility with a stable, pressed-state button that never submits', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn((event) => event.preventDefault())
    render(
      <form onSubmit={onSubmit}>
        <label htmlFor="pw">Password</label>
        <PasswordInput id="pw" defaultValue="secret" />
      </form>,
    )
    const input = screen.getByLabelText('Password')
    const toggle = screen.getByRole('button', { name: 'Show password' })
    expect(input).toHaveAttribute('type', 'password')
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    expect(toggle).toHaveAttribute('aria-controls', 'pw')
    expect(toggle).toHaveAttribute('type', 'button')

    await user.click(toggle)
    expect(input).toHaveAttribute('type', 'text')
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    await user.click(toggle)
    expect(input).toHaveAttribute('type', 'password')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('the toggle is reachable by keyboard and is not hidden from assistive technology', async () => {
    const user = userEvent.setup()
    render(<PasswordInput aria-label="Password" />)
    await user.tab()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Show password' })).toHaveFocus()
    expect(screen.getByRole('button', { name: 'Show password' }).closest('[aria-hidden="true"]')).toBeNull()
  })
})

describe('LoginPage', () => {
  it('has labelled fields with the right autocomplete hints', () => {
    renderApp('/login')
    expect(screen.getByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByLabelText('Email address')).toHaveAttribute('autocomplete', 'username')
    expect(screen.getByLabelText('Email address')).toHaveAttribute('type', 'email')
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'current-password')
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password')
    expect(within(screen.getByRole('main')).getByRole('link', { name: 'Create an account' })).toHaveAttribute('href', '/register')
    expect(document.title).toBe('Sign in · SakshamPay')
  })

  it('validates before sending and focuses the first problem', async () => {
    const user = userEvent.setup()
    const request = vi.spyOn(authService, 'requestAccessToken')
    renderApp('/login')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(screen.getByLabelText('Email address')).toHaveAccessibleDescription(MESSAGES.emailRequired)
    expect(screen.getByLabelText('Email address')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Password')).toHaveAccessibleDescription(MESSAGES.passwordRequired)
    expect(screen.getByLabelText('Email address')).toHaveFocus()
    expect(request).not.toHaveBeenCalled()
  })

  it('clears an error as soon as the field is fixed', async () => {
    const user = userEvent.setup()
    renderApp('/login')
    await user.type(screen.getByLabelText('Email address'), 'asha')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(screen.getByText(MESSAGES.emailInvalid)).toBeInTheDocument()
    await user.type(screen.getByLabelText('Email address'), '@example.com')
    expect(screen.queryByText(MESSAGES.emailInvalid)).not.toBeInTheDocument()
  })

  it('shows a busy, disabled button while signing in (no double submits)', async () => {
    const user = userEvent.setup()
    let resolve
    const request = vi.spyOn(authService, 'requestAccessToken').mockReturnValue(new Promise((r) => (resolve = r)))
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(TEST_USER)
    renderApp('/login')
    await user.type(screen.getByLabelText('Email address'), 'asha@example.com')
    await user.type(screen.getByLabelText('Password'), PASSWORD)
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    const button = screen.getByRole('button', { name: 'Sign in' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
    await user.keyboard('{Enter}')
    expect(request).toHaveBeenCalledOnce()
    resolve(TEST_TOKEN)
    await screen.findByRole('heading', { name: 'Welcome back, Asha' }) // P-9 default page
  })

  it('sends the normalised email and the password exactly as typed', async () => {
    const user = userEvent.setup()
    const request = vi.spyOn(authService, 'requestAccessToken').mockResolvedValue(TEST_TOKEN)
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue(TEST_USER)
    renderApp('/login')
    await user.type(screen.getByLabelText('Email address'), '  Asha@Example.com ')
    await user.type(screen.getByLabelText('Password'), ' pass with spaces ')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('heading', { name: 'Welcome back, Asha' }) // P-9 default page
    expect(request).toHaveBeenCalledWith({ email: 'asha@example.com', password: ' pass with spaces ' })
  })

  it('wrong credentials: one generic message, password cleared and focused, email kept', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'requestAccessToken').mockRejectedValue(apiError(401, 'INVALID_CREDENTIALS', 'Invalid email or password.'))
    renderApp('/login')
    await user.type(screen.getByLabelText('Email address'), 'asha@example.com')
    await user.type(screen.getByLabelText('Password'), PASSWORD)
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.')
    expect(screen.getByRole('alert')).not.toHaveTextContent('req-42') // no reference for a 4xx
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByLabelText('Password')).toHaveFocus()
    expect(screen.getByLabelText('Email address')).toHaveValue('asha@example.com')
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled()
    expect(getSession()).toBeNull()
  })

  it.each([
    [apiError(503, 'AUTH_NOT_CONFIGURED', 'Authentication is not available right now.'), true],
    [apiError(0, 'NETWORK_ERROR', 'Could not reach the SakshamPay server. Check that the backend is running.', { requestId: undefined }), false],
  ])('server or network problems show the message (%s)', async (error, showsReference) => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'requestAccessToken').mockRejectedValue(error)
    renderApp('/login')
    await user.type(screen.getByLabelText('Email address'), 'asha@example.com')
    await user.type(screen.getByLabelText('Password'), PASSWORD)
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(error.message)
    expect(alert.textContent.includes('req-42')).toBe(showsReference)
    expect(screen.getByLabelText('Password')).toHaveValue(PASSWORD) // nothing wrong with what was typed
  })

  it('a backend 422 is shown on the field', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'requestAccessToken').mockRejectedValue(
      apiError(422, 'VALIDATION_ERROR', 'Some fields are missing or invalid.', {
        details: [{ location: ['body', 'email'], message: 'Value error, Enter a valid email address.' }],
      }),
    )
    renderApp('/login')
    await user.type(screen.getByLabelText('Email address'), 'asha@example.com')
    await user.type(screen.getByLabelText('Password'), PASSWORD)
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(screen.getByLabelText('Email address')).toHaveAccessibleDescription('Enter a valid email address.'))
  })
})

describe('RegisterPage', () => {
  async function fill(user, overrides = {}) {
    const values = {
      'Full name': 'Asha Rao',
      'Email address': 'Asha@Example.com',
      'Mobile number': '',
      Password: PASSWORD,
      'Confirm password': PASSWORD,
      ...overrides,
    }
    for (const [label, value] of Object.entries(values)) {
      if (value) await user.type(screen.getByLabelText(new RegExp(`^${label}`)), value)
    }
  }

  it('has labelled fields, an optional phone and the right autocomplete hints', () => {
    renderApp('/register')
    expect(screen.getByRole('heading', { level: 1, name: 'Create your account' })).toBeInTheDocument()
    expect(screen.getByLabelText('Full name')).toHaveAttribute('autocomplete', 'name')
    expect(screen.getByLabelText('Email address')).toHaveAttribute('autocomplete', 'username')
    const phone = screen.getByLabelText(/^Mobile number/)
    expect(phone).toHaveAttribute('type', 'tel')
    expect(phone).not.toHaveAttribute('aria-required')
    expect(screen.getByText('(optional)')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'new-password')
    expect(screen.getByLabelText('Confirm password')).toHaveAttribute('autocomplete', 'new-password')
    expect(screen.getAllByRole('button', { name: 'Show password' })).toHaveLength(2)
    expect(within(screen.getByRole('main')).getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
  })

  it('validates every field before sending', async () => {
    const user = userEvent.setup()
    const register = vi.spyOn(authService, 'registerAccount')
    renderApp('/register')
    await fill(user, { 'Full name': '', 'Mobile number': '12345', Password: 'short', 'Confirm password': 'other' })
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByLabelText('Full name')).toHaveAccessibleDescription(MESSAGES.fullNameRequired)
    expect(screen.getByLabelText(/^Mobile number/)).toHaveAccessibleDescription(expect.stringContaining(MESSAGES.phoneUnrecognised))
    expect(screen.getByLabelText('Password')).toHaveAccessibleDescription(expect.stringContaining(MESSAGES.passwordTooShort))
    expect(screen.getByLabelText('Confirm password')).toHaveAccessibleDescription(MESSAGES.confirmMismatch)
    expect(screen.getByLabelText('Full name')).toHaveFocus()
    expect(register).not.toHaveBeenCalled()
  })

  it('normalises an Indian mobile number and sends only the allowed fields', async () => {
    const user = userEvent.setup()
    const register = vi.spyOn(authService, 'registerAccount').mockResolvedValue(TEST_USER)
    renderApp('/register')
    await fill(user, { 'Mobile number': '98765 43210' })
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    await screen.findByRole('heading', { name: 'Sign in' })
    expect(register).toHaveBeenCalledWith({ fullName: 'Asha Rao', email: 'asha@example.com', phoneNumber: '+919876543210', password: PASSWORD })
  })

  it('on success: no sign-in, a success message, and only the email prefilled', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'registerAccount').mockResolvedValue(TEST_USER)
    const login = vi.spyOn(authService, 'requestAccessToken')
    const app = renderApp('/register')
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument()
    expect(app.pathname()).toBe('/login')
    expect(screen.getByRole('status')).toHaveTextContent('Account created')
    expect(screen.getByLabelText('Email address')).toHaveValue('asha@example.com')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(login).not.toHaveBeenCalled()
    expect(getSession()).toBeNull()
    expect(JSON.stringify(app.router.state.location.state)).not.toContain(PASSWORD)
    expect(app.router.state.location.state).toEqual({ registeredEmail: 'asha@example.com' })
  })

  it('the success message goes away once the user tries to sign in', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'registerAccount').mockResolvedValue(TEST_USER)
    vi.spyOn(authService, 'requestAccessToken').mockRejectedValue(apiError(401, 'INVALID_CREDENTIALS', 'Invalid email or password.'))
    renderApp('/register')
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    await screen.findByText('Account created')
    await user.type(screen.getByLabelText('Password'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('alert')
    expect(screen.queryByText('Account created')).not.toBeInTheDocument()
  })

  it.each([
    ['EMAIL_ALREADY_REGISTERED', 'An account with this email already exists.', 'Email address'],
    ['PHONE_ALREADY_REGISTERED', 'An account with this phone number already exists.', 'Mobile number'],
  ])('%s is shown on its field and focused', async (code, message, label) => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'registerAccount').mockRejectedValue(apiError(409, code, message))
    renderApp('/register')
    await fill(user, { 'Mobile number': '9876543210' })
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    const field = screen.getByLabelText(new RegExp(`^${label}`))
    await waitFor(() => expect(field).toHaveAccessibleDescription(expect.stringContaining(message)))
    expect(field).toHaveFocus()
    expect(field).toHaveAttribute('aria-invalid', 'true')
  })

  it('a server error shows an alert with a reference and keeps what was typed', async () => {
    const user = userEvent.setup()
    vi.spyOn(authService, 'registerAccount').mockRejectedValue(apiError(503, 'DATABASE_UNAVAILABLE', 'The database is temporarily unavailable. Please try again shortly.'))
    renderApp('/register')
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The database is temporarily unavailable.')
    expect(within(alert).getByText('req-42')).toBeInTheDocument()
    expect(screen.getByLabelText('Full name')).toHaveValue('Asha Rao')
    expect(screen.getByRole('button', { name: 'Create account' })).toBeEnabled()
  })
})

describe('AccountPage', () => {
  it('shows the profile from /auth/me', async () => {
    saveSession({ accessToken: 'tok', expiresIn: 1800 })
    vi.spyOn(authService, 'fetchCurrentUser').mockResolvedValue({ ...TEST_USER, phone_number: null })
    renderApp('/account')
    const profile = await screen.findByRole('region', { name: 'Profile' })
    expect(within(profile).getByText('Asha Rao')).toBeInTheDocument()
    expect(within(profile).getByText('asha@example.com')).toBeInTheDocument()
    expect(within(profile).getByText('Not added')).toBeInTheDocument()
    expect(within(profile).getByText('9 November 2026')).toBeInTheDocument()
    expect(within(profile).getByText('Active')).toBeInTheDocument()
    expect(document.title).toBe('Your account · SakshamPay')
  })
})
