import { cx } from '../../utils/cx'
import Spinner from './Spinner'

/**
 * Spinner with a message, announced politely to screen readers.
 * Use `inline` inside text flows; the default centres it in its container.
 */
export default function LoadingState({ label = 'Loading', inline = false, className }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cx(
        'flex items-center gap-2 text-sm text-ink-muted',
        !inline && 'justify-center py-10',
        className,
      )}
    >
      <Spinner size={inline ? 'sm' : 'md'} />
      <span>{label}</span>
    </div>
  )
}
