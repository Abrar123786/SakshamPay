import { Link } from 'react-router'

import { cx } from '../../utils/cx'
import Spinner from './Spinner'

const VARIANTS = {
  primary: 'bg-brand text-white hover:bg-brand-hover',
  secondary: 'border border-line-input bg-surface-raised text-ink hover:bg-surface-muted',
  ghost: 'text-brand hover:bg-brand-soft',
  danger: 'bg-danger text-white hover:bg-danger-hover',
}

const SIZES = {
  sm: 'h-8 gap-1.5 px-3 text-sm',
  md: 'h-10 gap-2 px-4 text-sm',
  lg: 'h-12 gap-2 px-5 text-base',
}

const ICON_SIZES = { sm: 'size-4', md: 'size-4', lg: 'size-5' }

function buttonClasses({ variant = 'primary', size = 'md', fullWidth = false, className } = {}) {
  return cx(
    'inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-md font-medium',
    'transition-colors select-none disabled:cursor-not-allowed disabled:opacity-60',
    VARIANTS[variant],
    SIZES[size],
    fullWidth && 'w-full',
    className,
  )
}

function Icon({ icon: IconComponent, size }) {
  if (!IconComponent) return null
  return <IconComponent aria-hidden="true" focusable="false" strokeWidth={1.75} className={ICON_SIZES[size]} />
}

/**
 * Button for actions. Pass `to` to render a router link styled as a button
 * (navigation should be a link, not a button with an onClick).
 *
 * - variant: primary (one per view) | secondary | ghost | danger (destructive only)
 * - size: sm (32px) | md (40px) | lg (48px)
 * - loading: disables the button, shows a spinner and sets aria-busy; the label stays,
 *   so the width does not jump and screen readers keep the button's name
 * - leadingIcon / trailingIcon: a Lucide icon component, rendered decoratively
 */
export default function Button({
  variant = 'primary',
  size = 'md',
  fullWidth = false,
  loading = false,
  leadingIcon,
  trailingIcon,
  to,
  type = 'button',
  disabled,
  className,
  children,
  ...rest
}) {
  const classes = buttonClasses({ variant, size, fullWidth, className })

  if (to !== undefined) {
    return (
      <Link to={to} className={classes} {...rest}>
        <Icon icon={leadingIcon} size={size} />
        {children}
        <Icon icon={trailingIcon} size={size} />
      </Link>
    )
  }

  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Spinner size={size === 'lg' ? 'md' : 'sm'} /> : <Icon icon={leadingIcon} size={size} />}
      {children}
      {!loading && <Icon icon={trailingIcon} size={size} />}
    </button>
  )
}
