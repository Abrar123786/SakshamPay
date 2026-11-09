import InlineAlert from '../../components/ui/InlineAlert'

/**
 * Form-level error from an ApiError: the backend's message, plus the request ID
 * for server-side failures so support can find the request in the logs.
 */
export default function FormErrorAlert({ error, title }) {
  if (!error) return null
  const showReference = error.requestId && (error.status >= 500 || error.status === 0)
  return (
    <InlineAlert tone="danger" title={title ?? error.message}>
      {title && <p>{error.message}</p>}
      {showReference && (
        <p className="text-ink-muted">
          Reference <span className="font-mono text-xs select-all">{error.requestId}</span>
        </p>
      )}
    </InlineAlert>
  )
}
