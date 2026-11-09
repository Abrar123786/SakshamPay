import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { errorBody, fakeAdapter, networkFailure } from '../test/fakeAdapter'
import { ApiError, apiClient } from './apiClient'

const PASSWORD = 'correct-horse-battery-staple'
const TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.signature-value'

let originalAdapter

beforeEach(() => {
  originalAdapter = apiClient.defaults.adapter
})

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter
})

async function failingRequest(handler, config = {}) {
  apiClient.defaults.adapter = fakeAdapter(handler)
  try {
    await apiClient.post('/auth/login', { email: 'asha@example.com', password: PASSWORD }, {
      headers: { Authorization: `Bearer ${TOKEN}` },
      ...config,
    })
  } catch (error) {
    return error
  }
  throw new Error('request unexpectedly succeeded')
}

describe('ApiError never carries credentials or tokens', () => {
  it.each([
    ['an HTTP error', () => [401, errorBody('INVALID_CREDENTIALS', 'Invalid email or password.')]],
    ['a network failure', networkFailure()],
  ])('after %s', async (_label, handler) => {
    const error = await failingRequest(handler)
    expect(error).toBeInstanceOf(ApiError)

    // What console.error / an error reporter could see: own properties, deeply.
    const seen = JSON.stringify(error, Object.getOwnPropertyNames(error).concat(Object.keys(error.cause ?? {})))
    const everything = `${seen} ${JSON.stringify(error.cause)} ${String(error.cause?.message)}`
    expect(everything).not.toContain(PASSWORD)
    expect(everything).not.toContain(TOKEN)
    expect(error.cause).not.toHaveProperty('config')
    expect(error.cause).not.toHaveProperty('request')
    expect(error.cause).not.toHaveProperty('response')
  })

  it('keeps a small, safe summary of the cause for debugging', async () => {
    const error = await failingRequest(networkFailure())
    expect(error.cause).toEqual({ name: 'AxiosError', code: 'ERR_NETWORK', message: 'Network Error' })
  })
})

describe('error mapping (unchanged from P-3)', () => {
  it('maps the backend error envelope', async () => {
    const error = await failingRequest(() => [503, errorBody('DATABASE_UNAVAILABLE', 'Try again shortly.')])
    expect(error).toMatchObject({ status: 503, code: 'DATABASE_UNAVAILABLE', message: 'Try again shortly.', requestId: 'req-test' })
  })

  it('falls back to the X-Request-ID header and a generic message', async () => {
    const error = await failingRequest(() => [502, '<html>Bad gateway</html>', { 'x-request-id': 'req-header' }])
    expect(error).toMatchObject({ status: 502, code: 'HTTP_502', requestId: 'req-header' })
    expect(error.message).toBe('Something went wrong. Please try again.')
  })

  it('maps network failures', async () => {
    const error = await failingRequest(networkFailure())
    expect(error).toMatchObject({ status: 0, code: 'NETWORK_ERROR' })
  })

  it('keeps validation details from 422 responses', async () => {
    const details = [{ location: ['body', 'email'], message: 'Value error, Enter a valid email address.', type: 'value_error' }]
    const error = await failingRequest(() => [422, errorBody('VALIDATION_ERROR', 'Some fields are missing or invalid.', { details })])
    expect(error.details).toEqual(details)
  })

  it('has no details for other errors', async () => {
    const error = await failingRequest(() => [401, errorBody('INVALID_CREDENTIALS', 'Invalid email or password.')])
    expect(error.details).toBeUndefined()
  })
})
