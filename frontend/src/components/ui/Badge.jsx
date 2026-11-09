import { cx } from '../../utils/cx'

const TONES = {
  neutral: 'border-line bg-surface-muted text-ink-muted',
  brand: 'border-transparent bg-brand-soft text-brand',
  danger: 'border-transparent bg-danger-soft text-danger',
}

/**
 * Small text label for status or category (for example "Verified", "New payee").
 * Always text, never colour alone. Risk levels use RiskBadge, not this.
 */
export default function Badge({ tone = 'neutral', icon: IconComponent, className, children }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-xs font-medium whitespace-nowrap',
        TONES[tone],
        className,
      )}
    >
      {IconComponent && <IconComponent aria-hidden="true" focusable="false" strokeWidth={2} className="size-3.5" />}
      {children}
    </span>
  )
}
