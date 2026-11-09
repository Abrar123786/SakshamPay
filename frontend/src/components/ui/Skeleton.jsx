import { cx } from '../../utils/cx'

/**
 * Placeholder block shaped like content that is loading. Purely visual
 * (aria-hidden): mark the loading region with aria-busy and include a
 * LoadingState or visually hidden text for screen readers. The pulse stops
 * when the user prefers reduced motion.
 */
export default function Skeleton({ className }) {
  return <div aria-hidden="true" className={cx('animate-pulse rounded-md bg-surface-muted', className)} />
}
