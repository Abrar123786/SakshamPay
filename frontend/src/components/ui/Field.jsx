import { CircleAlert } from 'lucide-react'
import { useId } from 'react'

import { cx } from '../../utils/cx'
import Label from './Label'

/**
 * Label + control + hint + error, wired for assistive technology.
 *
 * The control is a render function so any input can be used:
 *
 *   <Field label="Email" hint="We never share it." error={errors.email}>
 *     {(control) => <Input type="email" autoComplete="email" {...control} />}
 *   </Field>
 *
 * `control` carries id, aria-describedby (hint and error), aria-invalid and `invalid`.
 */
export default function Field({ label, hint, error, optional = false, id, className, children }) {
  const generatedId = useId()
  const controlId = id ?? `field-${generatedId}`
  const hintId = hint ? `${controlId}-hint` : undefined
  const errorId = error ? `${controlId}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined

  const control = {
    id: controlId,
    'aria-describedby': describedBy,
    'aria-required': optional ? undefined : true,
    invalid: Boolean(error),
  }

  return (
    <div className={cx('space-y-1.5', className)}>
      <Label htmlFor={controlId} optional={optional}>
        {label}
      </Label>
      {children(control)}
      {hint && (
        <p id={hintId} className="text-sm text-ink-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="flex items-start gap-1.5 text-sm font-medium text-danger">
          <CircleAlert aria-hidden="true" focusable="false" strokeWidth={1.75} className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </p>
      )}
    </div>
  )
}
