import { cx } from '../../utils/cx'

/**
 * Bordered surface for a group of related content. No shadow: borders separate
 * content; shadows are reserved for floating layers.
 *
 * Give a card an accessible name by pointing aria-labelledby at its title:
 *   <Card aria-labelledby="limits-title">
 *     <CardHeader titleId="limits-title" title="Payment limits" />
 */
export function Card({ as: Element = 'section', className, children, ...rest }) {
  return (
    <Element className={cx('rounded-lg border border-line bg-surface-raised', className)} {...rest}>
      {children}
    </Element>
  )
}

export function CardHeader({ title, titleId, titleAs: Heading = 'h2', description, actions, className }) {
  return (
    <div className={cx('flex items-start justify-between gap-4 border-b border-line px-5 py-4', className)}>
      <div className="min-w-0">
        <Heading id={titleId} className="text-base font-semibold text-ink">
          {title}
        </Heading>
        {description && <p className="mt-1 text-sm text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

export function CardBody({ className, children }) {
  return <div className={cx('px-5 py-4', className)}>{children}</div>
}

export function CardFooter({ className, children }) {
  return (
    <div className={cx('flex flex-wrap items-center justify-end gap-3 border-t border-line px-5 py-3', className)}>
      {children}
    </div>
  )
}
