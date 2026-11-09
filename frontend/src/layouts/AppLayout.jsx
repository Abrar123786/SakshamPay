import { Link, Outlet } from 'react-router'

import AuthNav from '../components/auth/AuthNav'
import Logo from '../components/Logo'
import PageContainer from './PageContainer'

/**
 * Base layout: header (with sign-in or account actions), page content, footer.
 * Used by public, signed-out and signed-in pages alike.
 */
export default function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-10 focus:rounded-md focus:bg-surface-raised focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to content
      </a>

      <header className="border-b border-line bg-surface-raised">
        <PageContainer className="flex h-16 items-center justify-between gap-4">
          <Link to="/" className="rounded-sm" aria-label="SakshamPay home">
            <Logo />
          </Link>
          <div className="flex items-center gap-4">
            <p className="hidden text-sm text-ink-subtle lg:block">Prototype environment</p>
            <AuthNav />
          </div>
        </PageContainer>
      </header>

      <main id="main-content" className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-line">
        <PageContainer className="py-6 text-sm text-ink-subtle">
          SakshamPay is a hackathon prototype. All payments are simulated; it is not connected to
          UPI, NPCI or any bank.
        </PageContainer>
      </footer>
    </div>
  )
}
