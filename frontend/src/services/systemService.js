import { apiClient } from './apiClient'

/**
 * GET {VITE_API_BASE_URL}/health
 * Resolves to { status, application, version }.
 */
export async function getHealth({ signal } = {}) {
  const { data } = await apiClient.get('/health', { signal })
  return data
}
