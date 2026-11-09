import { LoaderCircle } from 'lucide-react'

import { cx } from '../../utils/cx'

const SIZES = { sm: 'size-4', md: 'size-5', lg: 'size-8' }

/**
 * Decorative spinning indicator. Hidden from assistive technology: pair it with
 * visible text, or use LoadingState, which announces itself.
 */
export default function Spinner({ size = 'sm', className }) {
  return (
    <LoaderCircle
      aria-hidden="true"
      focusable="false"
      strokeWidth={1.75}
      className={cx('shrink-0 animate-spin', SIZES[size], className)}
    />
  )
}
