import { env } from '../utils/env'
import { apiClient } from './apiClient'

/** Liveness URL. /health is a system endpoint at the server root, outside /api/v1. */
export const HEALTH_URL = `${env.apiOrigin}/health`

/**
 * GET {server origin}/health
 * Resolves to { status, application, version }.
 * An absolute URL bypasses the client's /api/v1 base URL but keeps its error handling.
 */
export async function getHealth({ signal } = {}) {
  const { data } = await apiClient.get(HEALTH_URL, { signal })
  return data
}
