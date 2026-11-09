/**
 * Turn an ApiError from a form submission into messages for the form.
 *
 *   fieldNames: backend field → form field, e.g. { full_name: 'fullName' }
 *   codeFields: error code → form field, e.g. { EMAIL_ALREADY_REGISTERED: 'email' }
 *
 * Returns { fieldErrors, formError }: field messages (from 422 details or a mapped
 * error code) and, when the error cannot be placed on a field, the ApiError itself
 * for a form-level alert.
 */
export function formErrorsFromApiError(error, { fieldNames = {}, codeFields = {} } = {}) {
  if (codeFields[error?.code]) {
    return { fieldErrors: { [codeFields[error.code]]: error.message }, formError: null }
  }

  if (error?.code === 'VALIDATION_ERROR' && Array.isArray(error.details)) {
    const fieldErrors = {}
    let unplaced = false
    for (const detail of error.details) {
      const [where, name] = detail?.location ?? []
      const field = where === 'body' ? fieldNames[name] : undefined
      const message = String(detail?.message ?? '').replace(/^Value error, /, '')
      if (field && message && !fieldErrors[field]) fieldErrors[field] = message
      else if (!field) unplaced = true
    }
    if (Object.keys(fieldErrors).length > 0) return { fieldErrors, formError: unplaced ? error : null }
  }

  return { fieldErrors: {}, formError: error ?? null }
}
