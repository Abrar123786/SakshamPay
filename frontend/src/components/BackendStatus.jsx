import { CircleCheck, CircleX } from 'lucide-react'

import { useBackendHealth } from '../hooks/useBackendHealth'
import { HEALTH_URL } from '../services/systemService'
import Button from './ui/Button'
import { Card, CardBody, CardHeader } from './ui/Card'
import Spinner from './ui/Spinner'

/**
 * Setup-verification widget: shows whether the frontend can reach the API.
 * Uses neutral/brand colours, not risk colours, because it is not a risk signal.
 */
export default function BackendStatus() {
  const { status, data, error, retry } = useBackendHealth()

  return (
    <Card aria-labelledby="backend-status-heading">
      <CardHeader
        title="API connection"
        titleId="backend-status-heading"
        actions={
          <Button variant="ghost" size="sm" onClick={retry} disabled={status === 'checking'}>
            Check again
          </Button>
        }
      />

      <CardBody>
        <div aria-live="polite">
          {status === 'checking' && (
            <p className="flex items-center gap-2 text-sm text-ink-muted">
              <Spinner />
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
        </div>

        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs text-ink-subtle">
          <dt>Endpoint</dt>
          <dd className="truncate font-mono">{HEALTH_URL}</dd>
        </dl>
      </CardBody>
    </Card>
  )
}
