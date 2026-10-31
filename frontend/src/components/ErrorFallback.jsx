import { RefreshCw, TriangleAlert } from 'lucide-react'

/**
 * Full-page fallback shown when rendering fails.
 * Used by both the global ErrorBoundary and the router's errorElement.
 */
export default function ErrorFallback({ title = 'Something went wrong', detail }) {
  return (
    <main
      role="alert"
      className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-16"
    >
      <div className="flex items-center gap-2 text-risk-high">
        <TriangleAlert aria-hidden="true" className="size-5" strokeWidth={1.75} />
        <p className="text-sm font-medium">Application error</p>
      </div>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight text-ink">{title}</h1>
      <p className="mt-2 text-ink-muted">
        The page could not be displayed. No payment was made. Reload the page to try again.
      </p>
      {detail && import.meta.env.DEV && (
        <pre className="mt-6 overflow-x-auto rounded-md border border-line bg-surface-raised p-4 font-mono text-xs text-ink-muted">
          {detail}
        </pre>
      )}
      <div className="mt-8">
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="inline-flex items-center gap-2 rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-hover"
        >
          <RefreshCw aria-hidden="true" className="size-4" strokeWidth={1.75} />
          Reload page
        </button>
      </div>
    </main>
  )
}
