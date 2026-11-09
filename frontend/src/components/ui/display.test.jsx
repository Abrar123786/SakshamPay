import { render, screen } from '@testing-library/react'
import { BadgeCheck } from 'lucide-react'
import { describe, expect, it, vi } from 'vitest'

import Badge from './Badge'
import { Card, CardBody, CardFooter, CardHeader } from './Card'
import RiskBadge from './RiskBadge'

describe('Card', () => {
  it('is a named region when labelled by its title', () => {
    render(
      <Card aria-labelledby="t">
        <CardHeader titleId="t" title="Payment limits" description="Simulated" actions={<button>Edit</button>} />
        <CardBody>Body</CardBody>
        <CardFooter>Footer</CardFooter>
      </Card>,
    )
    expect(screen.getByRole('region', { name: 'Payment limits' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Payment limits' })).toBeInTheDocument()
    expect(screen.getByText('Simulated')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
  })

  it('heading level can change with the page structure', () => {
    render(<CardHeader title="Nested" titleAs="h3" />)
    expect(screen.getByRole('heading', { level: 3 })).toBeInTheDocument()
  })

  it('uses a border, not a shadow', () => {
    const { container } = render(<Card>x</Card>)
    expect(container.firstChild).toHaveClass('border-line')
    expect(container.firstChild.className).not.toMatch(/shadow/)
  })
})

describe('Badge', () => {
  it.each([
    ['neutral', 'bg-surface-muted'],
    ['brand', 'bg-brand-soft'],
    ['danger', 'bg-danger-soft'],
  ])('%s tone', (tone, token) => {
    render(<Badge tone={tone}>Label</Badge>)
    expect(screen.getByText('Label')).toHaveClass(token)
  })

  it('has no risk tones', () => {
    render(<Badge tone="LOW">Label</Badge>)
    expect(screen.getByText('Label').className).not.toMatch(/risk-/)
  })

  it('icon is decorative', () => {
    const { container } = render(
      <Badge tone="brand" icon={BadgeCheck}>
        Verified
      </Badge>,
    )
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })
})

describe('RiskBadge', () => {
  it.each([
    ['LOW', 'Low risk', 'bg-risk-low-soft'],
    ['MEDIUM', 'Medium risk', 'bg-risk-medium-soft'],
    ['HIGH', 'High risk', 'bg-risk-high-soft'],
    ['high', 'High risk', 'bg-risk-high-soft'],
  ])('%s shows words, an icon and the risk colour', (level, label, token) => {
    const { container } = render(<RiskBadge level={level} />)
    const badge = screen.getByText(label)
    expect(badge).toHaveClass(token)
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('each level has a different icon shape', () => {
    const icons = ['LOW', 'MEDIUM', 'HIGH'].map((level) => {
      const { container, unmount } = render(<RiskBadge level={level} />)
      const markup = container.querySelector('svg').innerHTML
      unmount()
      return markup
    })
    expect(new Set(icons).size).toBe(3)
  })

  it('shows the score with a screen-reader word', () => {
    const { container } = render(<RiskBadge level="HIGH" score={75} />)
    expect(container.textContent).toBe('High risk·score 75')
  })

  it('unknown levels render a neutral badge, never a risk colour', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<RiskBadge level="SEVERE" />)
    const badge = screen.getByText('Risk not available')
    expect(badge.className).not.toMatch(/risk-/)
    expect(error).toHaveBeenCalled()
  })
})
