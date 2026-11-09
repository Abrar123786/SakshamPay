import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Unmount rendered trees and reset per-tab storage between tests.
afterEach(() => {
  cleanup()
  window.sessionStorage.clear()
})
