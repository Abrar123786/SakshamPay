import { describe, expect, it } from 'vitest'

import { ApiError } from '../services/apiClient'
import { DEFAULT_SIGNED_IN_PATH, safeReturnPath } from './authPaths'
import { MESSAGES, normalisePhone, validateLogin, validateRegistration } from './authValidation'
import { formErrorsFromApiError } from './formErrors'
import { formatDate } from './format'

const VALID = {
  fullName: 'Asha Rao',
  email: 'asha@example.com',
  phoneNumber: '',
  password: 'a-long-passphrase',
  confirmPassword: 'a-long-passphrase',
}

describe('normalisePhone', () => {
  it.each([
    ['9876543210', '+919876543210'],
    ['98765 43210', '+919876543210'],
    ['98765-43210', '+919876543210'],
    ['6000000000', '+916000000000'],
    ['+919876543210', '+919876543210'],
    ['+91 98765 43210', '+919876543210'],
    ['+91-98765-43210', '+919876543210'],
  ])('accepts the Indian mobile number %s as %s', (input, expected) => {
    expect(normalisePhone(input)).toEqual({ value: expected })
  })

  it.each(['', '   ', undefined, null])('treats %j as no phone number', (input) => {
    expect(normalisePhone(input)).toEqual({ value: null })
  })

  it.each([
    ['5876543210', MESSAGES.phoneUnrecognised], // Indian mobiles start with 6-9
    ['987654321', MESSAGES.phoneUnrecognised], // 9 digits
    ['98765432101', MESSAGES.phoneUnrecognised], // 11 digits
    ['09876543210', MESSAGES.phoneUnrecognised], // trunk prefix: not guessed
    ['919876543210', MESSAGES.phoneUnrecognised], // country code without +: not guessed
    ['+915876543210', MESSAGES.phoneIndianInvalid],
    ['+9198765432', MESSAGES.phoneIndianInvalid],
    ['+91987654321012', MESSAGES.phoneIndianInvalid],
    ['+0123456789', MESSAGES.phoneInternationalInvalid],
    ['+1234567', MESSAGES.phoneInternationalInvalid],
    ['+44 (20) 7946 0958', MESSAGES.phoneInternationalInvalid], // brackets are not stripped (backend does not either)
    ['abc', MESSAGES.phoneUnrecognised],
  ])('rejects %s with a clear message', (input, message) => {
    expect(normalisePhone(input)).toEqual({ error: message })
  })

  it.each([
    ['+14155552671', '+14155552671'],
    ['+44 20 7946 0958', '+442079460958'],
    ['+971-50-123-4567', '+971501234567'],
  ])('keeps the international number %s (only spaces and hyphens removed)', (input, expected) => {
    expect(normalisePhone(input)).toEqual({ value: expected })
  })
})

describe('validateRegistration', () => {
  it('accepts valid details and normalises them for the API', () => {
    const { errors, data } = validateRegistration({
      ...VALID,
      fullName: '  Asha   Rao ',
      email: '  Asha@Example.COM ',
      phoneNumber: '98765 43210',
    })
    expect(errors).toEqual({})
    expect(data).toEqual({ fullName: 'Asha Rao', email: 'asha@example.com', phoneNumber: '+919876543210', password: 'a-long-passphrase' })
  })

  it('never alters the password (no trimming)', () => {
    const password = '  spaces around  '
    expect(validateRegistration({ ...VALID, password, confirmPassword: password }).data.password).toBe(password)
  })

  it('does not return confirmPassword in the data to send', () => {
    expect(validateRegistration(VALID).data).not.toHaveProperty('confirmPassword')
  })

  it('reports every empty required field', () => {
    const { errors } = validateRegistration({})
    expect(errors).toEqual({
      fullName: MESSAGES.fullNameRequired,
      email: MESSAGES.emailRequired,
      password: MESSAGES.passwordRequired,
      confirmPassword: MESSAGES.confirmRequired,
    })
  })

  it.each([
    ['name too long', { fullName: 'a'.repeat(101) }, 'fullName', MESSAGES.fullNameTooLong],
    ['blank name', { fullName: '   ' }, 'fullName', MESSAGES.fullNameRequired],
    ['email without domain', { email: 'asha@' }, 'email', MESSAGES.emailInvalid],
    ['email with spaces inside', { email: 'as ha@example.com' }, 'email', MESSAGES.emailInvalid],
    ['email too long', { email: `${'a'.repeat(250)}@b.co` }, 'email', MESSAGES.emailInvalid],
    ['9-character password', { password: 'x'.repeat(9), confirmPassword: 'x'.repeat(9) }, 'password', MESSAGES.passwordTooShort],
    ['129-character password', { password: 'x'.repeat(129), confirmPassword: 'x'.repeat(129) }, 'password', MESSAGES.passwordTooLong],
    ['only spaces', { password: ' '.repeat(12), confirmPassword: ' '.repeat(12) }, 'password', MESSAGES.passwordBlank],
    ['password equals email', { password: 'ASHA@example.com', confirmPassword: 'ASHA@example.com' }, 'password', MESSAGES.passwordIsEmail],
    ['mismatched confirmation', { confirmPassword: 'something-else' }, 'confirmPassword', MESSAGES.confirmMismatch],
    ['invalid phone', { phoneNumber: '12345' }, 'phoneNumber', MESSAGES.phoneUnrecognised],
  ])('rejects %s', (_label, change, field, message) => {
    expect(validateRegistration({ ...VALID, ...change }).errors[field]).toBe(message)
  })

  it('counts length in characters, as the backend does (emoji count once)', () => {
    const password = '🙂'.repeat(10) // 10 code points, 20 UTF-16 units
    expect(validateRegistration({ ...VALID, password, confirmPassword: password }).errors.password).toBeUndefined()
    const short = '🙂'.repeat(9)
    expect(validateRegistration({ ...VALID, password: short, confirmPassword: short }).errors.password).toBe(MESSAGES.passwordTooShort)
  })
})

describe('validateLogin', () => {
  it('accepts and normalises the email', () => {
    expect(validateLogin({ email: ' Asha@Example.com ', password: 'x' })).toEqual({ errors: {}, data: { email: 'asha@example.com', password: 'x' } })
  })

  it('does not apply registration password rules (short passwords just fail sign-in)', () => {
    expect(validateLogin({ email: 'a@b.co', password: 'short' }).errors).toEqual({})
  })

  it('requires both fields', () => {
    expect(validateLogin({ email: '', password: '' }).errors).toEqual({ email: MESSAGES.emailRequired, password: MESSAGES.passwordRequired })
  })

  it('rejects an invalid email and an over-long password', () => {
    expect(validateLogin({ email: 'nope', password: 'x'.repeat(129) }).errors).toEqual({ email: MESSAGES.emailInvalid, password: MESSAGES.passwordTooLong })
  })
})

describe('formErrorsFromApiError', () => {
  const fieldNames = { full_name: 'fullName', email: 'email', phone_number: 'phoneNumber', password: 'password' }
  const codeFields = { EMAIL_ALREADY_REGISTERED: 'email', PHONE_ALREADY_REGISTERED: 'phoneNumber' }

  it('places 422 details on fields and removes the "Value error, " prefix', () => {
    const error = new ApiError({
      status: 422,
      code: 'VALIDATION_ERROR',
      message: 'Some fields are missing or invalid.',
      details: [
        { location: ['body', 'email'], message: 'Value error, Enter a valid email address.', type: 'value_error' },
        { location: ['body', 'phone_number'], message: 'Value error, Phone number must be in international format, e.g. +919876543210.', type: 'value_error' },
      ],
    })
    expect(formErrorsFromApiError(error, { fieldNames })).toEqual({
      fieldErrors: { email: 'Enter a valid email address.', phoneNumber: 'Phone number must be in international format, e.g. +919876543210.' },
      formError: null,
    })
  })

  it('keeps a form-level alert for details that are not about one field', () => {
    const error = new ApiError({
      status: 422,
      code: 'VALIDATION_ERROR',
      message: 'Some fields are missing or invalid.',
      details: [
        { location: ['body', 'email'], message: 'Value error, Enter a valid email address.' },
        { location: ['body'], message: 'Value error, Password must not be the same as the email address.' },
      ],
    })
    const { fieldErrors, formError } = formErrorsFromApiError(error, { fieldNames })
    expect(fieldErrors).toEqual({ email: 'Enter a valid email address.' })
    expect(formError).toBe(error)
  })

  it('maps conflict codes to their field', () => {
    const error = new ApiError({ status: 409, code: 'EMAIL_ALREADY_REGISTERED', message: 'An account with this email already exists.' })
    expect(formErrorsFromApiError(error, { fieldNames, codeFields })).toEqual({
      fieldErrors: { email: 'An account with this email already exists.' },
      formError: null,
    })
  })

  it('falls back to a form-level error', () => {
    const error = new ApiError({ status: 503, code: 'AUTH_NOT_CONFIGURED', message: 'Authentication is not available right now.' })
    expect(formErrorsFromApiError(error, { fieldNames, codeFields })).toEqual({ fieldErrors: {}, formError: error })
  })
})

describe('safeReturnPath', () => {
  it.each([
    [{ pathname: '/account' }, '/account'],
    [{ pathname: '/history', search: '?page=2', hash: '#top' }, '/history?page=2#top'],
  ])('returns in-app paths', (from, expected) => {
    expect(safeReturnPath(from)).toBe(expected)
  })

  it.each([
    undefined,
    null,
    {},
    { pathname: 'account' },
    { pathname: '//evil.example/x' },
    { pathname: '/\\evil.example' },
    { pathname: 'https://evil.example' },
    { pathname: '/login' },
    { pathname: '/register' },
    { pathname: 42 },
  ])('falls back to the default for %j', (from) => {
    expect(safeReturnPath(from)).toBe(DEFAULT_SIGNED_IN_PATH)
  })

  it('drops a malformed search or hash', () => {
    expect(safeReturnPath({ pathname: '/account', search: 'x', hash: 'y' })).toBe('/account')
  })
})

describe('formatDate', () => {
  it('formats an ISO date for India', () => {
    expect(formatDate('2026-11-09T10:00:00Z')).toBe('9 November 2026')
  })

  it('rejects an invalid date', () => {
    expect(() => formatDate('soon')).toThrow(TypeError)
  })
})
