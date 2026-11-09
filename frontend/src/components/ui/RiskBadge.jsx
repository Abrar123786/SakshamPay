import { CircleCheck, CircleHelp, OctagonAlert, TriangleAlert } from 'lucide-react'

import { cx } from '../../utils/cx'

/*
 * The ONLY component allowed to use the risk-* colour tokens (a test enforces this).
 * Each level is told apart three ways (colour, icon shape and words), so it works
 * for colour-blind users, in greyscale and for screen readers.
 */
const LEVELS = {
  LOW: { label: 'Low risk', icon: CircleCheck, classes: 'bg-risk-low-soft text-risk-low' },
  MEDIUM: { label: 'Medium risk', icon: TriangleAlert, classes: 'bg-risk-medium-soft text-risk-medium' },
  HIGH: { label: 'High risk', icon: OctagonAlert, classes: 'bg-risk-high-soft text-risk-high' },
}

const UNKNOWN = { label: 'Risk not available', icon: CircleHelp, classes: 'bg-surface-muted text-ink-muted' }

const SIZES = {
  sm: { box: 'gap-1 px-2 py-0.5 text-xs', icon: 'size-3.5' },
  md: { box: 'gap-1.5 px-2.5 py-1 text-sm', icon: 'size-4' },
}

/**
 * Risk category of an assessment (P-1 bands: LOW, MEDIUM, HIGH).
 * `score` (0-100) is optional and shown after the label, e.g. "High risk · 75".
 */
export default function RiskBadge({ level, score, size = 'md', className }) {
  const config = LEVELS[String(level ?? '').toUpperCase()] ?? UNKNOWN
  if (config === UNKNOWN && import.meta.env.DEV) {
    console.error(`[SakshamPay] RiskBadge received an unknown level: ${level}`)
  }
  const IconComponent = config.icon
  const sizes = SIZES[size]
  return (
    <span
      className={cx(
        'inline-flex items-center rounded-sm font-medium whitespace-nowrap',
        sizes.box,
        config.classes,
        className,
      )}
    >
      <IconComponent aria-hidden="true" focusable="false" strokeWidth={2} className={sizes.icon} />
      {config.label}
      {Number.isInteger(score) && (
        <>
          <span aria-hidden="true">·</span>
          <span>
            <span className="sr-only">score </span>
            {score}
          </span>
        </>
      )}
    </span>
  )
}
