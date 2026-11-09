import { AxiosError } from 'axios'

/**
 * Test helper: an Axios adapter that answers without a network.
 * `handler(config)` returns `[status, data, headers?]`, or throws to simulate a network failure.
 * Requests are recorded in `adapter.requests` for assertions.
 */
export function fakeAdapter(handler) {
  const adapter = async (config) => {
    adapter.requests.push(config)
    const [status, data, headers = {}] = await handler(config)
    const response = { status, statusText: '', data, headers, config, request: {} }
    if (status >= 200 && status < 300) return response
    throw new AxiosError(`Request failed with status code ${status}`, AxiosError.ERR_BAD_REQUEST, config, {}, response)
  }
  adapter.requests = []
  return adapter
}

export function networkFailure() {
  return (config) => {
    throw new AxiosError('Network Error', AxiosError.ERR_NETWORK, config, {})
  }
}

export function errorBody(code, message, extra = {}) {
  return { error: { code, message, request_id: 'req-test', ...extra } }
}
