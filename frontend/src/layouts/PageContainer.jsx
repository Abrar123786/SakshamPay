import { cx } from '../utils/cx'

/*
 * Page widths:
 *   narrow  576px  forms, sign-in, the payment and risk-review screens
 *   default 1152px most pages (the P-2 width)
 *   wide    1280px data-heavy pages such as history tables
 * Side padding grows with the viewport: 16px, 24px from 640px, 32px from 1024px.
 */
const WIDTHS = { narrow: 'max-w-xl', default: 'max-w-6xl', wide: 'max-w-7xl' }

export default function PageContainer({ size = 'default', as: Element = 'div', className, children, ...rest }) {
  return (
    <Element className={cx('mx-auto w-full px-4 sm:px-6 lg:px-8', WIDTHS[size], className)} {...rest}>
      {children}
    </Element>
  )
}
