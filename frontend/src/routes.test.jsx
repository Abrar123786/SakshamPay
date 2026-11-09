import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AuthProvider from './context/AuthProvider'
import { createRoutes, UI_GALLERY_PATH } from './routes'
import * as systemService from './services/systemService'

function renderAt(path, options) {
  const router = createMemoryRouter(createRoutes(options), { initialEntries: [path] })
  return render(
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>,
  )
}

// Paths under the root layout, in order. P-8 groups some routes under pathless
// guard routes (GuestOnly, RequireAuth); their children are listed in place.
function childPaths(routes) {
  return routes[0].children.flatMap((route) =>
    route.index ? ['(index)'] : route.path ? [route.path] : route.children.map((child) => child.path),
  )
}

describe('route table', () => {
  beforeEach(() => {
    vi.spyOn(systemService, 'getHealth').mockReturnValue(new Promise(() => {}))
  })

  it('keeps the existing routes', () => {
    expect(childPaths(createRoutes({ includeDevRoutes: false }))).toEqual(['(index)', 'login', 'register', 'account', '*'])
  })

  it('production route table has no UI gallery', () => {
    expect(childPaths(createRoutes({ includeDevRoutes: false }))).not.toContain(UI_GALLERY_PATH)
  })

  it('/__ui is a 404 when dev routes are excluded (as in production)', () => {
    renderAt('/__ui', { includeDevRoutes: false })
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('development route table includes the gallery before the catch-all', () => {
    expect(childPaths(createRoutes({ includeDevRoutes: true }))).toEqual(['(index)', 'login', 'register', 'account', '__ui', '*'])
  })

  it('/__ui renders the gallery in development', async () => {
    renderAt('/__ui', { includeDevRoutes: true })
    expect(await screen.findByRole('heading', { level: 1, name: 'UI gallery' })).toBeInTheDocument()
  })

  it('home still renders the landing placeholder', () => {
    renderAt('/', { includeDevRoutes: false })
    expect(screen.getByRole('heading', { level: 1, name: 'Check a payment before it leaves.' })).toBeInTheDocument()
  })
})
