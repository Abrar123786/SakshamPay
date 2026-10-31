import { useCallback, useEffect, useState } from 'react'

import { getHealth } from '../services/systemService'

/**
 * Checks the backend health endpoint once on mount and again on demand (no polling).
 * status: 'checking' | 'online' | 'offline'
 */
export function useBackendHealth() {
  const [state, setState] = useState({ status: 'checking', data: null, error: null })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()

    getHealth({ signal: controller.signal })
      .then((data) => setState({ status: 'online', data, error: null }))
      .catch((error) => {
        if (error.code === 'REQUEST_CANCELLED') return
        setState({ status: 'offline', data: null, error })
      })

    return () => controller.abort()
  }, [attempt])

  const retry = useCallback(() => {
    setState({ status: 'checking', data: null, error: null })
    setAttempt((n) => n + 1)
  }, [])

  return { ...state, retry }
}
