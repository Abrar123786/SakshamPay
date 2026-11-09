import { LogOut } from 'lucide-react'
import { Navigate, Outlet, useLocation } from 'react-router'

import { useAuth } from '../../context/authContext'
import PageContainer from '../../layouts/PageContainer'
import { LOGIN_PATH, safeReturnPath } from '../../utils/authPaths'
import Button from '../ui/Button'
import ErrorState from '../ui/ErrorState'
import LoadingState from '../ui/LoadingState'

function CheckingSession() {
  return <LoadingState label="Checking your session" />
}

/**
 * Layout route for pages that need a signed-in user.
 * Signed out: redirect to sign-in, remembering this page (unless the user signed
 * out on purpose). Session check failed for a temporary reason: offer a retry
 * without discarding the session.
 */
export function RequireAuth() {
  const { status, endedReason, error, retry, logout } = useAuth()
  const location = useLocation()

  if (status === 'restoring') return <CheckingSession />

  if (status === 'error') {
    return (
      <PageContainer size="narrow" className="py-16">
        <ErrorState
          titleAs="h1"
          title="We couldn't confirm your session"
          error={error}
          onRetry={retry}
          retryLabel="Try again"
        />
        <div className="mt-4">
          <Button variant="ghost" size="sm" leadingIcon={LogOut} onClick={logout}>
            Sign out instead
          </Button>
        </div>
      </PageContainer>
    )
  }

  if (status === 'unauthenticated') {
    const state = endedReason === 'signedOut' ? undefined : { from: location }
    return <Navigate to={LOGIN_PATH} replace state={state} />
  }

  return <Outlet />
}

/**
 * Layout route for the sign-in and registration pages. A signed-in user is sent on
 * to where they were going (or the default page) instead of seeing the forms again.
 */
export function GuestOnly() {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'restoring') return <CheckingSession />
  if (status === 'authenticated') return <Navigate to={safeReturnPath(location.state?.from)} replace />
  return <Outlet />
}
