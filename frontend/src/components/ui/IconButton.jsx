import { cx } from '../../utils/cx'

const VARIANTS = {
  ghost: 'text-ink-muted hover:bg-surface-muted hover:text-ink',
  secondary: 'border border-line-input bg-surface-raised text-ink hover:bg-surface-muted',
}

const SIZES = { sm: 'size-8', md: 'size-10' }
const ICON_SIZES = { sm: 'size-4', md: 'size-5' }

/**
 * Icon-only button. `label` is required: it becomes the accessible name
 * (icon-only controls are otherwise silent to screen readers).
 */
export default function IconButton({
  icon: IconComponent,
  label,
  variant = 'ghost',
  size = 'md',
  type = 'button',
  className,
  ...rest
}) {
  if (!label && import.meta.env.DEV) {
    console.error('[SakshamPay] IconButton needs a `label` for its accessible name.')
  }
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={cx(
        'inline-flex shrink-0 items-center justify-center rounded-md transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-60',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      <IconComponent aria-hidden="true" focusable="false" strokeWidth={1.75} className={ICON_SIZES[size]} />
    </button>
  )
}
