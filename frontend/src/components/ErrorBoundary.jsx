import { Component } from 'react'

import ErrorFallback from './ErrorFallback'

/**
 * Global error boundary: the last line of defence for render errors that
 * happen outside the router (providers, the router itself). Errors inside
 * routes are handled by the router's errorElement (see RouteError).
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // Single hook for future client-side error reporting.
    console.error('[SakshamPay] Unhandled render error', error, info?.componentStack)
  }

  render() {
    if (this.state.error) {
      return <ErrorFallback detail={String(this.state.error?.stack ?? this.state.error)} />
    }
    return this.props.children
  }
}
