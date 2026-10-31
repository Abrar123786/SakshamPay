/**
 * Central, validated access to build-time environment variables.
 *
 * Only variables prefixed with VITE_ reach the browser bundle, and anything
 * in the bundle is public. Never put secrets in frontend .env files.
 */

const DEV_FALLBACK_API_BASE_URL = 'http://localhost:8000/api/v1'

function readApiBaseUrl() {
  const raw = import.meta.env.VITE_API_BASE_URL?.trim()

  if (!raw) {
    if (import.meta.env.PROD) {
      throw new Error(
        'VITE_API_BASE_URL is not set. Configure it in the hosting environment before building.',
      )
    }
    console.warn(
      `[SakshamPay] VITE_API_BASE_URL is not set; falling back to ${DEV_FALLBACK_API_BASE_URL}. ` +
        'Copy frontend/.env.example to frontend/.env to silence this warning.',
    )
    return DEV_FALLBACK_API_BASE_URL
  }

  try {
    // Validates the format early; a typo here otherwise shows up as a vague network error.
    new URL(raw)
  } catch {
    throw new Error(`VITE_API_BASE_URL is not a valid absolute URL: "${raw}"`)
  }

  return raw.replace(/\/+$/, '')
}

export const env = Object.freeze({
  apiBaseUrl: readApiBaseUrl(),
  mode: import.meta.env.MODE,
  isProduction: import.meta.env.PROD,
})
