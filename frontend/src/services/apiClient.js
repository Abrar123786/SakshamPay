import axios from 'axios'

import { env } from '../utils/env'

/**
 * Normalised error thrown by every API call.
 *
 * The backend always answers errors as:
 *   { "error": { "code": "...", "message": "...", "request_id": "..." } }
 * Network failures and timeouts are mapped onto the same shape so the UI
 * only ever handles one kind of error.
 */
export class ApiError extends Error {
  constructor({ status, code, message, requestId, cause }) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.cause = cause
  }
}

export const REQUEST_TIMEOUT_MS = 15_000

export const apiClient = axios.create({
  baseURL: env.apiBaseUrl,
  timeout: REQUEST_TIMEOUT_MS,
  headers: {
    Accept: 'application/json',
    'Content-Type': 'application/json',
  },
})

// Request interceptor: the single place where the access token, device ID and
// Idempotency-Key headers will be attached once authentication and payments
// are implemented (later prompts). Intentionally a pass-through for now.
apiClient.interceptors.request.use((config) => config)

function toApiError(error) {
  if (axios.isCancel(error)) {
    return new ApiError({ status: 0, code: 'REQUEST_CANCELLED', message: 'The request was cancelled.', cause: error })
  }

  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
    return new ApiError({
      status: 0,
      code: 'TIMEOUT',
      message: 'The server took too long to respond. It may be starting up; please try again.',
      cause: error,
    })
  }

  if (!error.response) {
    return new ApiError({
      status: 0,
      code: 'NETWORK_ERROR',
      message: 'Could not reach the SakshamPay server. Check that the backend is running.',
      cause: error,
    })
  }

  const { status, data, headers } = error.response
  const body = data?.error ?? {}
  return new ApiError({
    status,
    code: body.code ?? `HTTP_${status}`,
    message: body.message ?? 'Something went wrong. Please try again.',
    requestId: body.request_id ?? headers?.['x-request-id'],
    cause: error,
  })
}

apiClient.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(toApiError(error)),
)
