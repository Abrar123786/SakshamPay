/* Regression tests: P-2/P-3 components keep their behaviour after the P-7 refactor. */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../services/apiClient'
import * as systemService from '../services/systemService'
import NotFoundPage from '../pages/NotFoundPage'
import BackendStatus from './BackendStatus'
import ErrorBoundary from './ErrorBoundary'
import ErrorFallback from './ErrorFallback'

describe('BackendStatus', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows the connected API and its version', async () => {
    vi.spyOn(systemService, 'getHealth').mockResolvedValue({ status: 'healthy', application: 'SakshamPay', version: '1.0.0' })
    render(<BackendStatus />)
    expect(screen.getByText('Contacting the server')).toBeInTheDocument()
    expect(await screen.findByTestId('backend-status')).toHaveTextContent('Connected to SakshamPay API v1.0.0')
    expect(screen.getByText('Server reports status: healthy')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'API connection' })).toBeInTheDocument()
  })

  it('shows the API client error message when offline, and retries', async () => {
    const user = userEvent.setup()
    const health = vi
      .spyOn(systemService, 'getHealth')
      .mockRejectedValueOnce(new ApiError({ status: 0, code: 'NETWORK_ERROR', message: 'Could not reach the SakshamPay server.' }))
      .mockResolvedValueOnce({ status: 'healthy', application: 'SakshamPay', version: '1.0.0' })
    render(<BackendStatus />)
    expect(await screen.findByTestId('backend-status')).toHaveTextContent('Not connected')
    expect(screen.getByText('Could not reach the SakshamPay server.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Check again' }))
    await waitFor(() => expect(screen.getByTestId('backend-status')).toHaveTextContent('Connected to SakshamPay'))
    expect(health).toHaveBeenCalledTimes(2)
  })

  it('shows the health endpoint it calls', () => {
    vi.spyOn(systemService, 'getHealth').mockReturnValue(new Promise(() => {}))
    render(<BackendStatus />)
    expect(screen.getByText(systemService.HEALTH_URL)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check again' })).toBeDisabled()
  })
})

describe('ErrorFallback', () => {
  it('is an alert with a reload action and uses danger, not risk, colours', () => {
    const { container } = render(<ErrorFallback />)
    expect(screen.getByRole('alert')).toHaveTextContent('No payment was made')
    expect(screen.getByRole('button', { name: 'Reload page' })).toBeInTheDocument()
    expect(container.innerHTML).toMatch(/text-danger/)
    expect(container.innerHTML).not.toMatch(/risk-/)
  })
})

describe('ErrorBoundary', () => {
  it('catches a render error and shows the fallback', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    function Broken() {
      throw new Error('boom')
    }
    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
  })
})

describe('NotFoundPage', () => {
  it('explains the 404 and links home', () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { level: 1, name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to home' })).toHaveAttribute('href', '/')
  })
})
