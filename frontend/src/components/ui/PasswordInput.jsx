import { Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'

import IconButton from './IconButton'
import Input from './Input'

/**
 * Password input with a show/hide toggle.
 *
 * The toggle is a real button inside the input frame with a stable name
 * ("Show password") and aria-pressed for its state, so screen readers hear
 * "Show password, toggle button, pressed/not pressed". It never submits the form.
 * Use through Field, like Input.
 */
export default function PasswordInput({ id, disabled, ...rest }) {
  const [visible, setVisible] = useState(false)

  return (
    <Input
      {...rest}
      id={id}
      disabled={disabled}
      type={visible ? 'text' : 'password'}
      autoCapitalize="none"
      autoCorrect="off"
      spellCheck={false}
      endAction={
        <IconButton
          size="sm"
          icon={visible ? EyeOff : Eye}
          label="Show password"
          aria-pressed={visible}
          aria-controls={id}
          disabled={disabled}
          onClick={() => setVisible((current) => !current)}
        />
      }
    />
  )
}
