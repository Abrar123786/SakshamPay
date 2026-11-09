/**
 * Client-side validation for sign-in and registration.
 *
 * The rules mirror backend/app/schemas/auth.py (P-6) so most mistakes are caught
 * before a request is sent; the backend still validates everything and its 422
 * errors are shown if the two ever disagree. Lengths count Unicode code points,
 * as Python does, not UTF-16 units.
 *
 * Each validator returns { errors, data }: `errors` maps field names to messages
 * (empty when valid) and `data` holds the normalised values to send.
 */

export const PASSWORD_MIN_LENGTH = 10
export const PASSWORD_MAX_LENGTH = 128
const FULL_NAME_MAX_LENGTH = 100
const EMAIL_MAX_LENGTH = 254

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const E164_PATTERN = /^\+[1-9][0-9]{7,14}$/
const INDIAN_MOBILE_PATTERN = /^[6-9][0-9]{9}$/

export const MESSAGES = Object.freeze({
  fullNameRequired: 'Enter your full name.',
  fullNameTooLong: `Full name must be ${FULL_NAME_MAX_LENGTH} characters or fewer.`,
  emailRequired: 'Enter your email address.',
  emailInvalid: 'Enter a valid email address, like name@example.com.',
  phoneIndianInvalid: 'Enter a valid Indian mobile number: 10 digits starting with 6, 7, 8 or 9.',
  phoneInternationalInvalid: 'Enter a valid international number: + then the country code and number, 8 to 15 digits.',
  phoneUnrecognised: 'Enter a 10-digit Indian mobile number, or an international number starting with +.',
  passwordRequired: 'Enter your password.',
  passwordTooShort: `Use at least ${PASSWORD_MIN_LENGTH} characters.`,
  passwordTooLong: `Use ${PASSWORD_MAX_LENGTH} characters or fewer.`,
  passwordBlank: "Password can't be only spaces.",
  passwordIsEmail: "Password can't be the same as your email address.",
  confirmRequired: 'Re-enter your password.',
  confirmMismatch: "Passwords don't match.",
})

const length = (value) => [...value].length

export function normaliseEmail(value) {
  return String(value ?? '').trim().toLowerCase()
}

export function normaliseFullName(value) {
  return String(value ?? '').split(/\s+/).filter(Boolean).join(' ')
}

/**
 * Indian numbers: a 10-digit mobile number (or one already written as +91…) is
 * sent as +91XXXXXXXXXX. Other numbers must already be in international format
 * and are only stripped of spaces and hyphens (as the backend does), never rewritten.
 * Returns { value } (null when empty) or { error }.
 */
export function normalisePhone(raw) {
  const compact = String(raw ?? '').replace(/[\s-]/g, '')
  if (!compact) return { value: null }
  if (INDIAN_MOBILE_PATTERN.test(compact)) return { value: `+91${compact}` }
  if (compact.startsWith('+91')) {
    return INDIAN_MOBILE_PATTERN.test(compact.slice(3)) ? { value: compact } : { error: MESSAGES.phoneIndianInvalid }
  }
  if (compact.startsWith('+')) {
    return E164_PATTERN.test(compact) ? { value: compact } : { error: MESSAGES.phoneInternationalInvalid }
  }
  return { error: MESSAGES.phoneUnrecognised }
}

function emailError(email) {
  if (!email) return MESSAGES.emailRequired
  if (length(email) > EMAIL_MAX_LENGTH || !EMAIL_PATTERN.test(email)) return MESSAGES.emailInvalid
  return undefined
}

function withoutEmpty(errors) {
  return Object.fromEntries(Object.entries(errors).filter(([, message]) => message))
}

export function validateLogin({ email, password }) {
  const data = { email: normaliseEmail(email), password: String(password ?? '') }
  const errors = withoutEmpty({
    email: emailError(data.email),
    // Sign-in does not repeat the registration rules (as in the backend): a short
    // password simply fails as invalid credentials.
    password: !data.password ? MESSAGES.passwordRequired : length(data.password) > PASSWORD_MAX_LENGTH ? MESSAGES.passwordTooLong : undefined,
  })
  return { errors, data }
}

export function registrationPasswordError(password, normalisedEmail) {
  if (!password) return MESSAGES.passwordRequired
  if (length(password) < PASSWORD_MIN_LENGTH) return MESSAGES.passwordTooShort
  if (length(password) > PASSWORD_MAX_LENGTH) return MESSAGES.passwordTooLong
  if (!password.trim()) return MESSAGES.passwordBlank
  if (normalisedEmail && password.trim().toLowerCase() === normalisedEmail) return MESSAGES.passwordIsEmail
  return undefined
}

export function validateRegistration({ fullName, email, phoneNumber, password, confirmPassword }) {
  const name = normaliseFullName(fullName)
  const normalisedEmail = normaliseEmail(email)
  const phone = normalisePhone(phoneNumber)
  const pass = String(password ?? '') // never trimmed or altered
  const confirm = String(confirmPassword ?? '')

  const errors = withoutEmpty({
    fullName: !name ? MESSAGES.fullNameRequired : length(name) > FULL_NAME_MAX_LENGTH ? MESSAGES.fullNameTooLong : undefined,
    email: emailError(normalisedEmail),
    phoneNumber: phone.error,
    password: registrationPasswordError(pass, emailError(normalisedEmail) ? '' : normalisedEmail),
    confirmPassword: !confirm ? MESSAGES.confirmRequired : confirm !== pass ? MESSAGES.confirmMismatch : undefined,
  })

  return {
    errors,
    data: { fullName: name, email: normalisedEmail, phoneNumber: phone.value ?? null, password: pass },
  }
}
