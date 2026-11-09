import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Plus, Trash2 } from 'lucide-react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import Button from './Button'
import IconButton from './IconButton'
import Spinner from './Spinner'

describe('Button', () => {
  it('is a real button that does not submit forms by default', () => {
    render(<Button>Continue</Button>)
    const button = screen.getByRole('button', { name: 'Continue' })
    expect(button).toHaveAttribute('type', 'button')
  })

  it('calls onClick when pressed with mouse or keyboard', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Continue</Button>)
    await user.tab()
    expect(screen.getByRole('button')).toHaveFocus()
    await user.keyboard('{Enter}')
    await user.keyboard(' ')
    await user.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledTimes(3)
  })

  it('can be a submit button', () => {
    render(<Button type="submit">Pay</Button>)
    expect(screen.getByRole('button', { name: 'Pay' })).toHaveAttribute('type', 'submit')
  })

  it.each([
    ['primary', 'bg-brand'],
    ['secondary', 'border-line-input'],
    ['ghost', 'text-brand'],
    ['danger', 'bg-danger'],
  ])('%s variant uses its token', (variant, token) => {
    render(<Button variant={variant}>Action</Button>)
    expect(screen.getByRole('button')).toHaveClass(token)
  })

  it.each([
    ['sm', 'h-8'],
    ['md', 'h-10'],
    ['lg', 'h-12'],
  ])('%s size has a fixed height', (size, height) => {
    render(<Button size={size}>Action</Button>)
    expect(screen.getByRole('button')).toHaveClass(height)
  })

  it('loading disables, marks busy and keeps its accessible name', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(
      <Button loading onClick={onClick} leadingIcon={Plus}>
        Saving
      </Button>,
    )
    const button = screen.getByRole('button', { name: 'Saving' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
    await user.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('icons are decorative', () => {
    const { container } = render(<Button leadingIcon={Trash2}>Remove</Button>)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('button')).toHaveAccessibleName('Remove')
  })

  it('renders a router link when given `to`', () => {
    render(
      <MemoryRouter>
        <Button to="/history" variant="secondary">
          History
        </Button>
      </MemoryRouter>,
    )
    const link = screen.getByRole('link', { name: 'History' })
    expect(link).toHaveAttribute('href', '/history')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})

describe('IconButton', () => {
  it('uses its label as the accessible name', () => {
    render(<IconButton icon={Plus} label="Add beneficiary" />)
    expect(screen.getByRole('button', { name: 'Add beneficiary' })).toBeInTheDocument()
  })

  it('warns in development when the label is missing', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<IconButton icon={Plus} />)
    expect(error).toHaveBeenCalledWith(expect.stringContaining('needs a `label`'))
  })
})

describe('Spinner', () => {
  it('is hidden from assistive technology', () => {
    const { container } = render(<Spinner />)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })
})
