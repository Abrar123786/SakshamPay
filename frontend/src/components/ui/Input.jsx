import { cx } from '../../utils/cx'

const HEIGHTS = { md: 'h-10', lg: 'h-12' }

const FRAME = cx(
  'flex w-full items-center rounded-md border text-ink transition-colors',
  'focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-brand',
)

/**
 * Text input (text, email, password, tel, number, search...).
 *
 * - 16px text so mobile Safari does not zoom on focus
 * - outline colour line-input (3.63:1), danger when `invalid`
 * - `prefix` / `suffix`: short adornments such as "₹" or a unit; decorative
 *   (the label must still describe the field)
 *
 * Prefer using it through Field, which wires up label, hint and error.
 */
export default function Input({ invalid = false, size = 'md', prefix, suffix, disabled, className, ...rest }) {
  const borderColour = invalid ? 'border-danger' : 'border-line-input hover:border-ink-subtle'
  return (
    <div
      className={cx(FRAME, HEIGHTS[size], borderColour, disabled ? 'cursor-not-allowed bg-surface-muted' : 'bg-surface-raised', className)}
    >
      {prefix && (
        <span aria-hidden="true" className="pl-3 text-base text-ink-muted select-none">
          {prefix}
        </span>
      )}
      <input
        disabled={disabled}
        aria-invalid={invalid || undefined}
        className={cx(
          'h-full w-full min-w-0 rounded-md bg-transparent px-3 text-base text-ink',
          'placeholder:text-ink-subtle focus:outline-none disabled:cursor-not-allowed disabled:text-ink-disabled',
          prefix && 'pl-2',
          suffix && 'pr-2',
        )}
        {...rest}
      />
      {suffix && (
        <span aria-hidden="true" className="pr-3 text-sm text-ink-muted select-none">
          {suffix}
        </span>
      )}
    </div>
  )
}
