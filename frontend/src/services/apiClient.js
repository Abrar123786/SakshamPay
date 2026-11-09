import axios from 'axios'

import { env } from '../utils/env'
import { clearSession, getSession, isExpired } from './tokenStore'

/**
 * Normalised error thrown by every API call.
 *
 * The backend always answers errors as:
 *   { "error": { "code": "...", "message": "...", "request_id": "...", "details"?: [...] } }
 * Network failures and timeouts are mapped onto the same shape so the UI
 * only ever handles one kind of error.
 *
 * `cause` is a small summary ({ name, code, message }), never the raw Axios
 * error: that object holds the request body (passwords) and headers (the bearer
 * token), and errors can end up in console.error or an error reporter.
 */
export class ApiError extends Error {
  constructor({ status, code, message, requestId, details, cause }) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.details = details
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

// ---- authentication ------------------------------------------------------------------------

let unauthorizedHandler = null

/**
 * Register the function called when an authenticated request is rejected with 401,
 * or a stored token is found to have expired. AuthProvider registers itself here.
 * Returns an unregister function.
 */
export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null
  }
}

const API_BASE = new URL(env.apiBaseUrl)
const API_PATH_PREFIX = `${API_BASE.pathname.replace(/\/+$/, '')}/`

/** True only for requests to the versioned API (never /health, never another origin). */
export function isApiRequest(config) {
  try {
    const url = new URL(apiClient.getUri(config))
    return url.origin === API_BASE.origin && url.pathname.startsWith(API_PATH_PREFIX)
  } catch {
    return false
  }
}

// Attach the bearer token. `skipAuth: true` (login, register) sends no token.
apiClient.interceptors.request.use((config) => {
  if (config.skipAuth || !isApiRequest(config)) return config
  const session = getSession()
  if (!session) return config
  if (isExpired(session)) {
    // Never send a token we know has expired; the request goes out unauthenticated.
    clearSession()
    unauthorizedHandler?.(new ApiError({ status: 401, code: 'TOKEN_EXPIRED', message: 'The access token has expired. Please sign in again.' }))
    return config
  }
  config.headers.set('Authorization', `Bearer ${session.accessToken}`)
  config.sentAccessToken = true
  return config
})

// ---- errors ----------------------------------------------------------------------------------

function summarise(error) {
  return { name: error?.name, code: error?.code, message: error?.message }
}

function toApiError(error) {
  const cause = summarise(error)

  if (axios.isCancel(error)) {
    return new ApiError({ status: 0, code: 'REQUEST_CANCELLED', message: 'The request was cancelled.', cause })
  }

  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
    return new ApiError({
      status: 0,
      code: 'TIMEOUT',
      message: 'The server took too long to respond. It may be starting up; please try again.',
      cause,
    })
  }

  if (!error.response) {
    return new ApiError({
      status: 0,
      code: 'NETWORK_ERROR',
      message: 'Could not reach the SakshamPay server. Check that the backend is running.',
      cause,
    })
  }

  const { status, data, headers } = error.response
  const body = data?.error ?? {}
  return new ApiError({
    status,
    code: body.code ?? `HTTP_${status}`,
    message: body.message ?? 'Something went wrong. Please try again.',
    requestId: body.request_id ?? headers?.['x-request-id'],
    details: Array.isArray(body.details) ? body.details : undefined,
    cause,
  })
}

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const apiError = toApiError(error)
    // A 401 on a request that carried our token means the session is no longer valid
    // (expired, invalid, user deactivated). A 401 from /auth/login carries no token.
    if (apiError.status === 401 && error.config?.sentAccessToken) {
      clearSession()
      unauthorizedHandler?.(apiError)
    }
    return Promise.reject(apiError)
  },
)
