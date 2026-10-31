import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router'

export default function NotFoundPage() {
  return (
    <div className="mx-auto max-w-xl px-6 py-24">
      <p className="font-mono text-sm text-ink-subtle">404</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink">Page not found</h1>
      <p className="mt-2 text-ink-muted">The address you opened does not match any SakshamPay page.</p>
      <Link
        to="/"
        className="mt-8 inline-flex items-center gap-2 text-sm font-medium text-brand hover:text-brand-hover"
      >
        <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={1.75} />
        Back to home
      </Link>
    </div>
  )
}
