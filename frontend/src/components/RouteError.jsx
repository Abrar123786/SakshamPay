import { isRouteErrorResponse, useRouteError } from 'react-router'

import NotFoundPage from '../pages/NotFoundPage'
import ErrorFallback from './ErrorFallback'

/** Router-level error element: 404s get the not-found page, everything else the fallback. */
export default function RouteError() {
  const error = useRouteError()

  if (isRouteErrorResponse(error) && error.status === 404) {
    return <NotFoundPage />
  }

  console.error('[SakshamPay] Route error', error)
  const detail = error instanceof Error ? error.stack : JSON.stringify(error, null, 2)
  return <ErrorFallback detail={detail} />
}
