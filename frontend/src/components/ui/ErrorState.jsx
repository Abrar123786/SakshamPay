import { CircleAlert, RefreshCw } from 'lucide-react'

import { cx } from '../../utils/cx'
import Button from './Button'

/**
 * Replaces a section whose content could not load.
 *
 * Accepts an `error` from the API client (ApiError: message + requestId) or explicit
 * `message` / `requestId`. The request ID is shown as a reference the user can quote,
 * which matches the server log entry. Uses the danger tokens, never risk colours.
 */
export default function ErrorState({
  title = 'Something went wrong',
  titleAs: Heading = 'h2',
  message,
  error,
  requestId,
  onRetry,
  retryLabel = 'Try again',
  className,
}) {
  const text = message ?? error?.message ?? 'Please try again.'
  const reference = requestId ?? error?.requestId
  return (
    <div role="alert" className={cx('flex flex-col items-start gap-3 py-8', className)}>
      <div className="flex items-center gap-2 text-danger">
        <CircleAlert aria-hidden="true" focusable="false" strokeWidth={1.75} className="size-5" />
        <Heading className="text-base font-semibold text-ink">{title}</Heading>
      </div>
      <p className="max-w-prose text-sm text-ink-muted">{text}</p>
      {reference && (
        <p className="text-xs text-ink-subtle">
          Reference <span className="font-mono select-all">{reference}</span>
        </p>
      )}
      {onRetry && (
        <Button variant="secondary" size="sm" leadingIcon={RefreshCw} onClick={onRetry}>
          {retryLabel}
        </Button>
      )}
    </div>
  )
}
