import { CircleAlert, CircleCheck, Info } from 'lucide-react'

import { cx } from '../../utils/cx'

const TONES = {
  info: { icon: Info, classes: 'border-transparent bg-info-soft text-info', role: 'status' },
  success: { icon: CircleCheck, classes: 'border-transparent bg-success-soft text-success', role: 'status' },
  danger: { icon: CircleAlert, classes: 'border-danger-line bg-danger-soft text-danger', role: 'alert' },
  neutral: { icon: Info, classes: 'border-line bg-surface-muted text-ink-muted', role: 'status' },
}

/**
 * Message banner inside a page or form. Danger alerts are announced immediately
 * (role="alert"); the others politely (role="status"). Success uses brand teal,
 * because green is reserved for LOW risk. There is deliberately no amber
 * "warning" tone: amber means MEDIUM risk.
 */
export default function InlineAlert({ tone = 'info', title, className, children }) {
  const config = TONES[tone]
  const IconComponent = config.icon
  return (
    <div role={config.role} className={cx('flex gap-3 rounded-md border px-4 py-3 text-sm', config.classes, className)}>
      <IconComponent aria-hidden="true" focusable="false" strokeWidth={1.75} className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 space-y-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className="text-ink">{children}</div>}
      </div>
    </div>
  )
}
