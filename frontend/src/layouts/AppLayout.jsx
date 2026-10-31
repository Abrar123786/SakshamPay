import { Link, Outlet } from 'react-router'

import Logo from '../components/Logo'

/**
 * Base public layout: header, page content, footer.
 * Authenticated pages will get their own layout in a later prompt.
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
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <Link to="/" className="rounded-sm" aria-label="SakshamPay home">
            <Logo />
          </Link>
          <p className="hidden text-sm text-ink-subtle sm:block">Prototype environment</p>
        </div>
      </header>

      <main id="main-content" className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto max-w-6xl px-6 py-6 text-sm text-ink-subtle">
          SakshamPay is a hackathon prototype. All payments are simulated; it is not connected to
          UPI, NPCI or any bank.
        </div>
      </footer>
    </div>
  )
}
