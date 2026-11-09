import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import '@fontsource-variable/ibm-plex-sans/wght.css' // self-hosted IBM Plex Sans (variable weight)

import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import './styles/index.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
