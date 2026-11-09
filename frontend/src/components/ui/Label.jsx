import { cx } from '../../utils/cx'

/**
 * Form label. Optional fields say "(optional)" in words; required is the default,
 * so forms do not depend on asterisks or colour to communicate it.
 */
export default function Label({ htmlFor, optional = false, className, children, ...rest }) {
  return (
    <label htmlFor={htmlFor} className={cx('block text-sm font-medium text-ink', className)} {...rest}>
      {children}
      {optional && <span className="ml-1 font-normal text-ink-subtle">(optional)</span>}
    </label>
  )
}
