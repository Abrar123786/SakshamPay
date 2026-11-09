import { useRef, useState } from 'react'
import { Link, useLocation } from 'react-router'

import Button from '../../components/ui/Button'
import Field from '../../components/ui/Field'
import InlineAlert from '../../components/ui/InlineAlert'
import Input from '../../components/ui/Input'
import PasswordInput from '../../components/ui/PasswordInput'
import { SESSION_ENDED_MESSAGES, useAuth } from '../../context/authContext'
import { REGISTER_PATH } from '../../utils/authPaths'
import { validateLogin } from '../../utils/authValidation'
import { formErrorsFromApiError } from '../../utils/formErrors'
import AuthPageLayout from './AuthPageLayout'
import FormErrorAlert from './FormErrorAlert'

const FIELD_ORDER = ['email', 'password']

/**
 * Sign-in. On success the auth state changes and GuestOnly sends the user on
 * (back to the page they were sent here from, or the default page), so this page
 * does not navigate itself.
 */
export default function LoginPage() {
  const { login, endedReason } = useAuth()
  const location = useLocation()
  const registeredEmail = typeof location.state?.registeredEmail === 'string' ? location.state.registeredEmail : ''

  const [values, setValues] = useState({ email: registeredEmail, password: '' })
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [attempted, setAttempted] = useState(false)
  const inputs = { email: useRef(null), password: useRef(null) }

  const notice = attempted
    ? null
    : registeredEmail
      ? { tone: 'success', title: 'Account created', message: 'Sign in with your new password to continue.' }
      : endedReason
        ? { tone: endedReason === 'signedOut' ? 'success' : 'info', title: SESSION_ENDED_MESSAGES[endedReason] }
        : null

  function update(field) {
    return (event) => {
      const next = { ...values, [field]: event.target.value }
      setValues(next)
      if (attempted) setErrors(validateLogin(next).errors)
    }
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (submitting) return
    setAttempted(true)
    setFormError(null)

    const { errors: found, data } = validateLogin(values)
    setErrors(found)
    const firstInvalid = FIELD_ORDER.find((field) => found[field])
    if (firstInvalid) {
      inputs[firstInvalid].current?.focus()
      return
    }

    setSubmitting(true)
    try {
      await login(data)
    } catch (error) {
      if (error.code === 'INVALID_CREDENTIALS') {
        setFormError(error)
        setValues((current) => ({ ...current, password: '' }))
        inputs.password.current?.focus()
      } else {
        const mapped = formErrorsFromApiError(error, { fieldNames: { email: 'email', password: 'password' } })
        setErrors(mapped.fieldErrors)
        setFormError(mapped.formError)
      }
      setSubmitting(false)
    }
  }

  return (
    <AuthPageLayout
      title="Sign in"
      description="Check payments for risk before they leave your account."
      footer={
        <>
          New to SakshamPay?{' '}
          <Link to={REGISTER_PATH} className="font-medium text-brand underline-offset-4 hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form noValidate onSubmit={handleSubmit} aria-label="Sign in" className="space-y-5">
        {notice && <InlineAlert tone={notice.tone} title={notice.title}>{notice.message}</InlineAlert>}
        <FormErrorAlert error={formError} />

        <Field label="Email address" error={errors.email}>
          {(control) => (
            <Input
              {...control}
              ref={inputs.email}
              type="email"
              name="email"
              autoComplete="username"
              inputMode="email"
              autoCapitalize="none"
              spellCheck={false}
              value={values.email}
              onChange={update('email')}
            />
          )}
        </Field>

        <Field label="Password" error={errors.password}>
          {(control) => (
            <PasswordInput
              {...control}
              ref={inputs.password}
              name="password"
              autoComplete="current-password"
              value={values.password}
              onChange={update('password')}
            />
          )}
        </Field>

        <Button type="submit" size="lg" fullWidth loading={submitting}>
          Sign in
        </Button>
      </form>
    </AuthPageLayout>
  )
}
