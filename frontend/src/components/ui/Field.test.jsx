import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import Field from './Field'
import Input from './Input'
import Label from './Label'

describe('Label', () => {
  it('says "(optional)" in words for optional fields', () => {
    render(
      <Label htmlFor="note" optional>
        Note
      </Label>,
    )
    expect(screen.getByText('(optional)')).toBeInTheDocument()
  })
})

describe('Input', () => {
  it('uses 16px text so mobile browsers do not zoom on focus', () => {
    render(<Input aria-label="Amount" />)
    expect(screen.getByRole('textbox', { name: 'Amount' })).toHaveClass('text-base')
  })

  it('marks invalid input for assistive technology and in colour', () => {
    const { container } = render(<Input aria-label="Email" invalid />)
    expect(screen.getByRole('textbox')).toHaveAttribute('aria-invalid', 'true')
    expect(container.firstChild).toHaveClass('border-danger')
  })

  it('valid input has no aria-invalid and the 3:1 outline token', () => {
    const { container } = render(<Input aria-label="Email" />)
    expect(screen.getByRole('textbox')).not.toHaveAttribute('aria-invalid')
    expect(container.firstChild).toHaveClass('border-line-input')
  })

  it('disabled input has only the muted background (no conflicting bg class)', () => {
    const { container } = render(<Input aria-label="Account" disabled />)
    expect(screen.getByRole('textbox')).toBeDisabled()
    expect(container.firstChild).toHaveClass('bg-surface-muted')
    expect(container.firstChild).not.toHaveClass('bg-surface-raised')
  })

  it('prefix is decorative and does not change the accessible name', () => {
    render(<Input aria-label="Amount" prefix="₹" />)
    expect(screen.getByText('₹')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('textbox')).toHaveAccessibleName('Amount')
  })

  it('accepts typing', async () => {
    const user = userEvent.setup()
    render(<Input aria-label="Name" />)
    await user.type(screen.getByRole('textbox'), 'Asha')
    expect(screen.getByRole('textbox')).toHaveValue('Asha')
  })
})

describe('Field', () => {
  const renderField = (props) =>
    render(<Field label="Email" {...props}>{(control) => <Input type="email" {...control} />}</Field>)

  it('associates the label with the control', () => {
    renderField()
    expect(screen.getByLabelText('Email')).toHaveAttribute('type', 'email')
  })

  it('marks fields required unless optional', () => {
    renderField()
    expect(screen.getByRole('textbox')).toHaveAttribute('aria-required', 'true')
  })

  it('optional fields are not marked required', () => {
    renderField({ optional: true })
    expect(screen.getByRole('textbox')).not.toHaveAttribute('aria-required')
    expect(screen.getByLabelText(/Email/)).toBeInTheDocument()
  })

  it('describes the control with its hint', () => {
    renderField({ hint: 'We never share it.' })
    expect(screen.getByRole('textbox')).toHaveAccessibleDescription('We never share it.')
  })

  it('describes the control with hint and error, and marks it invalid', () => {
    renderField({ hint: 'We never share it.', error: 'Enter a valid email address.' })
    const input = screen.getByRole('textbox')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('We never share it. Enter a valid email address.')
    expect(screen.getByText('Enter a valid email address.').parentElement).toHaveClass('text-danger')
  })

  it('uses a provided id', () => {
    renderField({ id: 'login-email' })
    expect(screen.getByRole('textbox')).toHaveAttribute('id', 'login-email')
  })

  it('gives each field a unique id', () => {
    render(
      <>
        <Field label="First">{(c) => <Input {...c} />}</Field>
        <Field label="Second">{(c) => <Input {...c} />}</Field>
      </>,
    )
    expect(screen.getByLabelText('First').id).not.toBe(screen.getByLabelText('Second').id)
  })
})
