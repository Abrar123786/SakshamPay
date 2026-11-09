import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'

import AuthProvider from '../context/AuthProvider'

import AppLayout from './AppLayout'
import PageContainer from './PageContainer'
import PageHeader from './PageHeader'

describe('PageContainer', () => {
  it.each([
    ['narrow', 'max-w-xl'],
    ['default', 'max-w-6xl'],
    ['wide', 'max-w-7xl'],
  ])('%s width', (size, width) => {
    const { container } = render(<PageContainer size={size}>x</PageContainer>)
    expect(container.firstChild).toHaveClass(width, 'mx-auto', 'px-4', 'sm:px-6', 'lg:px-8')
  })

  it('can render as another element', () => {
    render(<PageContainer as="section" aria-label="Area">x</PageContainer>)
    expect(screen.getByRole('region', { name: 'Area' })).toBeInTheDocument()
  })
})

describe('PageHeader', () => {
  it('renders the page h1 with eyebrow, description and actions', () => {
    render(<PageHeader eyebrow="History" title="Transactions" description="Last 30 days" actions={<button>Export</button>} />)
    expect(screen.getByRole('heading', { level: 1, name: 'Transactions' })).toBeInTheDocument()
    expect(screen.getByText('History')).toBeInTheDocument()
    expect(screen.getByText('Last 30 days')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Export' })).toBeInTheDocument()
  })
})

describe('AppLayout (existing behaviour preserved)', () => {
  it('keeps the skip link, landmarks, home link and prototype notice', () => {
    render(
      <AuthProvider>
        <MemoryRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<p>Page content</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>,
    )
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main-content')
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content')
    expect(screen.getByRole('main')).toHaveTextContent('Page content')
    expect(screen.getByRole('link', { name: 'SakshamPay home' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('contentinfo')).toHaveTextContent('All payments are simulated')
    // P-8: signed-out visitors see the sign-in action in the header.
    expect(screen.getByRole('navigation', { name: 'Account' })).toContainElement(screen.getByRole('link', { name: 'Sign in' }))
  })
})
