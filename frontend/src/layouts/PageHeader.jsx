import { cx } from '../utils/cx'

/**
 * Title area at the top of a page: the page's single h1, an optional short
 * eyebrow above it, a description and actions. Actions sit beside the title from
 * 640px and stack below it on phones.
 */
export default function PageHeader({ title, eyebrow, description, actions, className }) {
  return (
    <header className={cx('flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between', className)}>
      <div className="min-w-0">
        {eyebrow && <p className="text-sm font-medium text-brand">{eyebrow}</p>}
        <h1 className={cx('text-3xl font-semibold tracking-tight text-ink', eyebrow && 'mt-1')}>{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-base break-words text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-3">{actions}</div>}
    </header>
  )
}
