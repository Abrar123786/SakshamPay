import { lazy, Suspense } from 'react'

import RouteError from './components/RouteError'
import LoadingState from './components/ui/LoadingState'
import AppLayout from './layouts/AppLayout'
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
 * Route table. Later prompts add /login, /register, /dashboard, /pay,
 * /transactions/:id/review, /history and /alerts under the appropriate layouts.
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
      children: [{ index: true, element: <LandingPage /> }, ...devRoutes, { path: '*', element: <NotFoundPage /> }],
    },
  ]
}
