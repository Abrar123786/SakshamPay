import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import Button from '../../components/ui/Button'
import Field from '../../components/ui/Field'
import Input from '../../components/ui/Input'
import PasswordInput from '../../components/ui/PasswordInput'
import { useAuth } from '../../context/authContext'
import { LOGIN_PATH } from '../../utils/authPaths'
import { PASSWORD_MIN_LENGTH, validateRegistration } from '../../utils/authValidation'
import { formErrorsFromApiError } from '../../utils/formErrors'
import AuthPageLayout from './AuthPageLayout'
import FormErrorAlert from './FormErrorAlert'

const FIELD_ORDER = ['fullName', 'email', 'phoneNumber', 'password', 'confirmPassword']
const BACKEND_FIELDS = { full_name: 'fullName', email: 'email', phone_number: 'phoneNumber', password: 'password' }
const CONFLICT_FIELDS = { EMAIL_ALREADY_REGISTERED: 'email', PHONE_ALREADY_REGISTERED: 'phoneNumber' }
const EMPTY = { fullName: '', email: '', phoneNumber: '', password: '', confirmPassword: '' }

/**
 * Registration. On success the user is sent to sign in with only the email
 * prefilled; the password is never kept or passed on.
 */
export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()

  const [values, setValues] = useState(EMPTY)
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [attempted, setAttempted] = useState(false)
  const inputs = {
    fullName: useRef(null),
    email: useRef(null),
    phoneNumber: useRef(null),
    password: useRef(null),
    confirmPassword: useRef(null),
  }

  function focusFirst(found) {
    const firstInvalid = FIELD_ORDER.find((field) => found[field])
    if (firstInvalid) inputs[firstInvalid].current?.focus()
    return Boolean(firstInvalid)
  }

  function update(field) {
    return (event) => {
      const next = { ...values, [field]: event.target.value }
      setValues(next)
      if (attempted) setErrors(validateRegistration(next).errors)
    }
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (submitting) return
    setAttempted(true)
    setFormError(null)

    const { errors: found, data } = validateRegistration(values)
    setErrors(found)
    if (focusFirst(found)) return

    setSubmitting(true)
    try {
      await register(data)
      setValues(EMPTY)
      navigate(LOGIN_PATH, { state: { registeredEmail: data.email } })
    } catch (error) {
      const mapped = formErrorsFromApiError(error, { fieldNames: BACKEND_FIELDS, codeFields: CONFLICT_FIELDS })
      setErrors(mapped.fieldErrors)
      setFormError(mapped.formError)
      focusFirst(mapped.fieldErrors) // a form-level alert announces itself (role="alert")
      setSubmitting(false)
    }
  }

  return (
    <AuthPageLayout
      title="Create your account"
      description="SakshamPay is a prototype. All payments are simulated, so use a password you don't use anywhere else."
      footer={
        <>
          Already have an account?{' '}
          <Link to={LOGIN_PATH} className="font-medium text-brand underline-offset-4 hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form noValidate onSubmit={handleSubmit} aria-label="Create your account" className="space-y-5">
        <FormErrorAlert error={formError} />

        <Field label="Full name" error={errors.fullName}>
          {(control) => (
            <Input {...control} ref={inputs.fullName} name="fullName" autoComplete="name" value={values.fullName} onChange={update('fullName')} />
          )}
        </Field>

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

        <Field
          label="Mobile number"
          optional
          hint="10-digit Indian mobile number, or an international number starting with +."
          error={errors.phoneNumber}
        >
          {(control) => (
            <Input
              {...control}
              ref={inputs.phoneNumber}
              type="tel"
              name="phoneNumber"
              autoComplete="tel"
              inputMode="tel"
              value={values.phoneNumber}
              onChange={update('phoneNumber')}
            />
          )}
        </Field>

        <Field label="Password" hint={`At least ${PASSWORD_MIN_LENGTH} characters. A few unrelated words work well.`} error={errors.password}>
          {(control) => (
            <PasswordInput
              {...control}
              ref={inputs.password}
              name="password"
              autoComplete="new-password"
              value={values.password}
              onChange={update('password')}
            />
          )}
        </Field>

        <Field label="Confirm password" error={errors.confirmPassword}>
          {(control) => (
            <PasswordInput
              {...control}
              ref={inputs.confirmPassword}
              name="confirmPassword"
              autoComplete="new-password"
              value={values.confirmPassword}
              onChange={update('confirmPassword')}
            />
          )}
        </Field>

        <Button type="submit" size="lg" fullWidth loading={submitting}>
          Create account
        </Button>
      </form>
    </AuthPageLayout>
  )
}
