import { useCallback, useEffect, useState } from 'react'

import { getDashboardSummary } from '../services/dashboardService'

/**
 * Loads the dashboard summary once on mount and again on retry().
 * status: 'loading' | 'ready' | 'error'. The request is aborted when the page
 * unmounts (e.g. on sign-out), so a late response is never applied.
 * Data is kept in component state only; nothing is stored.
 */
export function useDashboardSummary() {
  const [state, setState] = useState({ status: 'loading', summary: null, error: null })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    getDashboardSummary({ signal: controller.signal })
      .then((summary) => setState({ status: 'ready', summary, error: null }))
      .catch((error) => {
        if (error.code === 'REQUEST_CANCELLED') return
        // A 401 has already ended the session (apiClient); the route guard takes over.
        setState({ status: 'error', summary: null, error })
      })
    return () => controller.abort()
  }, [attempt])

  const retry = useCallback(() => {
    setState({ status: 'loading', summary: null, error: null })
    setAttempt((n) => n + 1)
  }, [])

  return { ...state, retry }
}
