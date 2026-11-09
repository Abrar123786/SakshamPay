import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../services/apiClient'
import ErrorState from './ErrorState'
import InlineAlert from './InlineAlert'
import LoadingState from './LoadingState'
import Skeleton from './Skeleton'

describe('LoadingState', () => {
  it('is a polite live status with visible text', () => {
    render(<LoadingState label="Assessing payment" />)
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('Assessing payment')
    expect(status).toHaveAttribute('aria-live', 'polite')
  })

  it('has a sensible default label', () => {
    render(<LoadingState />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading')
  })
})

describe('Skeleton', () => {
  it('is decorative and respects size classes', () => {
    const { container } = render(<Skeleton className="h-4 w-1/2" />)
    expect(container.firstChild).toHaveAttribute('aria-hidden', 'true')
    expect(container.firstChild).toHaveClass('h-4', 'w-1/2', 'animate-pulse')
  })
})

describe('ErrorState', () => {
  it('announces itself and shows the message', () => {
    render(<ErrorState title="Could not load" message="Server unavailable." />)
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load')
    expect(screen.getByRole('heading', { level: 2, name: 'Could not load' })).toBeInTheDocument()
    expect(screen.getByText('Server unavailable.')).toBeInTheDocument()
  })

  it('takes message and request ID from an ApiError', () => {
    const error = new ApiError({ status: 503, code: 'DATABASE_UNAVAILABLE', message: 'Try again shortly.', requestId: 'req-123' })
    render(<ErrorState error={error} />)
    expect(screen.getByText('Try again shortly.')).toBeInTheDocument()
    expect(screen.getByText('req-123')).toBeInTheDocument()
  })

  it('offers a retry only when a handler is given', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    const { rerender } = render(<ErrorState message="x" />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    rerender(<ErrorState message="x" onRetry={onRetry} retryLabel="Reload transactions" />)
    await user.click(screen.getByRole('button', { name: 'Reload transactions' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('uses danger tokens, never risk colours', () => {
    const { container } = render(<ErrorState message="x" />)
    expect(container.innerHTML).toMatch(/text-danger/)
    expect(container.innerHTML).not.toMatch(/risk-/)
  })
})

describe('InlineAlert', () => {
  it('danger alerts are assertive', () => {
    render(<InlineAlert tone="danger" title="Invalid email or password." />)
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid email or password.')
  })

  it.each(['info', 'success', 'neutral'])('%s alerts are polite', (tone) => {
    render(<InlineAlert tone={tone}>Message</InlineAlert>)
    expect(screen.getByRole('status')).toHaveTextContent('Message')
  })

  it('success uses brand teal, not a risk green', () => {
    render(<InlineAlert tone="success" title="Saved" />)
    expect(screen.getByRole('status')).toHaveClass('bg-success-soft')
    expect(screen.getByRole('status').className).not.toMatch(/risk-/)
  })
})
