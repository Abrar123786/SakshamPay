import { apiClient } from './apiClient'

/** The three P-6 endpoints (relative to VITE_API_BASE_URL, i.e. under /api/v1). */
export const AUTH_PATHS = Object.freeze({
  register: '/auth/register',
  login: '/auth/login',
  me: '/auth/me',
})

/**
 * POST /auth/register → UserProfile (201). Does not sign in: the caller sends the
 * user to the sign-in page. The backend forbids unknown fields, so the body is
 * built from explicit keys only (never `confirmPassword`).
 */
export async function registerAccount({ fullName, email, phoneNumber, password }, { signal } = {}) {
  const body = { full_name: fullName, email, phone_number: phoneNumber || null, password }
  const { data } = await apiClient.post(AUTH_PATHS.register, body, { signal, skipAuth: true })
  return data
}

/** POST /auth/login → { access_token, token_type, expires_in, expires_at }. */
export async function requestAccessToken({ email, password }, { signal } = {}) {
  const { data } = await apiClient.post(AUTH_PATHS.login, { email, password }, { signal, skipAuth: true })
  return data
}

/** GET /auth/me with the stored bearer token → UserProfile. */
export async function fetchCurrentUser({ signal } = {}) {
  const { data } = await apiClient.get(AUTH_PATHS.me, { signal })
  return data
}
