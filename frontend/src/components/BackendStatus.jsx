import { CircleCheck, CircleX, LoaderCircle } from 'lucide-react'

import { useBackendHealth } from '../hooks/useBackendHealth'
import { HEALTH_URL } from '../services/systemService'

/**
 * Setup-verification widget: shows whether the frontend can reach the API.
 * Uses neutral/brand colours, not risk colours, because it is not a risk signal.
 */
export default function BackendStatus() {
  const { status, data, error, retry } = useBackendHealth()

  return (
    <section
      aria-labelledby="backend-status-heading"
      className="rounded-lg border border-line bg-surface-raised"
    >
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <h2 id="backend-status-heading" className="text-sm font-medium text-ink">
          API connection
        </h2>
        <button
          type="button"
          onClick={retry}
          disabled={status === 'checking'}
          className="text-sm font-medium text-brand hover:text-brand-hover disabled:cursor-not-allowed disabled:text-ink-subtle"
        >
          Check again
        </button>
      </div>

      <div className="px-5 py-4" aria-live="polite">
        {status === 'checking' && (
          <p className="flex items-center gap-2 text-sm text-ink-muted">
            <LoaderCircle aria-hidden="true" className="size-4 animate-spin" strokeWidth={1.75} />
            Contacting the server
          </p>
        )}

        {status === 'online' && (
          <div>
            <p className="flex items-center gap-2 text-sm font-medium text-ink" data-testid="backend-status">
              <CircleCheck aria-hidden="true" className="size-4 text-brand" strokeWidth={1.75} />
              Connected to {data.application} API v{data.version}
            </p>
            <p className="mt-1 text-sm text-ink-muted">Server reports status: {data.status}</p>
          </div>
        )}

        {status === 'offline' && (
          <div>
            <p className="flex items-center gap-2 text-sm font-medium text-ink" data-testid="backend-status">
              <CircleX aria-hidden="true" className="size-4 text-ink-muted" strokeWidth={1.75} />
              Not connected
            </p>
            <p className="mt-1 text-sm text-ink-muted">{error.message}</p>
          </div>
        )}

        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs text-ink-subtle">
          <dt>Endpoint</dt>
          <dd className="truncate font-mono">{HEALTH_URL}</dd>
        </dl>
      </div>
    </section>
  )
}
