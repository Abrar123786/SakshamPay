import { useAuth } from '../../context/authContext'
import { LOGIN_PATH, REGISTER_PATH } from '../../utils/authPaths'
import SignedInNav from '../navigation/SignedInNav'
import Button from '../ui/Button'

/**
 * Header actions: sign in / create account when signed out; the main navigation
 * and sign out when signed in (SignedInNav). Text-only buttons, so the logo and
 * actions fit a 360px-wide screen.
 */
export default function AuthNav() {
  const { status, logout } = useAuth()

  if (status === 'restoring') return null

  if (status === 'authenticated') return <SignedInNav />

  if (status === 'error') {
    return (
      <Button variant="secondary" size="sm" onClick={logout}>
        Sign out
      </Button>
    )
  }

  return (
    <nav aria-label="Account" className="flex items-center gap-2">
      <Button to={LOGIN_PATH} variant="ghost" size="sm">
        Sign in
      </Button>
      {/* Wrapper controls visibility: Button sets its own display, so don't override it with className. */}
      <span className="hidden sm:block">
        <Button to={REGISTER_PATH} size="sm">
          Create account
        </Button>
      </span>
    </nav>
  )
}
