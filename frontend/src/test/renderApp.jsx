import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'

import AuthProvider from '../context/AuthProvider'
import { createRoutes } from '../routes'

/**
 * Render the real app (AuthProvider + production route table) at `path`.
 * Returns the router so tests can check where the user ended up.
 */
export function renderApp(path = '/') {
  const router = createMemoryRouter(createRoutes({ includeDevRoutes: false }), { initialEntries: [path] })
  const view = render(
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>,
  )
  return { ...view, router, pathname: () => router.state.location.pathname }
}

export const TEST_USER = Object.freeze({
  id: '9f1c2a5e-0000-4000-8000-000000000001',
  full_name: 'Asha Rao',
  email: 'asha@example.com',
  phone_number: '+919876543210',
  is_active: true,
  created_at: '2026-11-09T10:00:00Z',
})

export const TEST_TOKEN = Object.freeze({
  access_token: 'tok-test',
  token_type: 'bearer',
  expires_in: 1800,
  expires_at: '2026-11-09T10:30:00Z',
})
