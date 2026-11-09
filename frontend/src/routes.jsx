import { lazy, Suspense } from 'react'

import { GuestOnly, RequireAuth } from './components/auth/RouteGuards'
import RouteError from './components/RouteError'
import LoadingState from './components/ui/LoadingState'
import AppLayout from './layouts/AppLayout'
import AccountPage from './pages/AccountPage'
import LoginPage from './pages/auth/LoginPage'
import RegisterPage from './pages/auth/RegisterPage'
import LandingPage from './pages/LandingPage'
import NotFoundPage from './pages/NotFoundPage'

/*
 * Development-only UI gallery at /__ui.
 * `import.meta.env.DEV` is replaced with `false` in production builds, so the
 * dynamic import below is removed and the gallery is not in the bundle at all.
 */
const UiGalleryPage = import.meta.env.DEV ? lazy(() => import('./pages/dev/UiGalleryPage')) : null

export const UI_GALLERY_PATH = '__ui'

/**
 * Route table.
 *   public:            /            (and the 404 page)
 *   signed-out only:   /login, /register   (GuestOnly)
 *   signed-in only:    /account             (RequireAuth)
 * Later prompts add /dashboard, /pay, /transactions/:id/review, /history and /alerts
 * under RequireAuth.
 */
export function createRoutes({ includeDevRoutes = import.meta.env.DEV } = {}) {
  const devRoutes =
    includeDevRoutes && UiGalleryPage
      ? [
          {
            path: UI_GALLERY_PATH,
            element: (
              <Suspense fallback={<LoadingState label="Loading UI gallery" />}>
                <UiGalleryPage />
              </Suspense>
            ),
          },
        ]
      : []

  return [
    {
      path: '/',
      element: <AppLayout />,
      errorElement: <RouteError />,
      children: [
        { index: true, element: <LandingPage /> },
        {
          element: <GuestOnly />,
          children: [
            { path: 'login', element: <LoginPage /> },
            { path: 'register', element: <RegisterPage /> },
          ],
        },
        {
          element: <RequireAuth />,
          children: [{ path: 'account', element: <AccountPage /> }],
        },
        ...devRoutes,
        { path: '*', element: <NotFoundPage /> },
      ],
    },
  ]
}
