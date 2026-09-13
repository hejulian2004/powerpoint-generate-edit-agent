import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  getApiToken,
  setApiToken,
  clearApiToken,
  getWebSocketProtocols,
  authFetch
} from './auth'

describe('frontend auth transport', () => {
  beforeEach(() => {
    clearApiToken()
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('stores token in memory and sessionStorage without touching localStorage', () => {
    setApiToken('tok-secret-123')
    expect(getApiToken()).toBe('tok-secret-123')
    expect(sessionStorage.getItem('ppt_api_token')).toBe('tok-secret-123')
    expect(localStorage.getItem('ppt_api_token')).toBeNull()

    clearApiToken()
    expect(getApiToken()).toBe('')
    expect(sessionStorage.getItem('ppt_api_token')).toBeNull()
  })

  it('correctly encodes token to base64url for WebSocket subprotocol', () => {
    setApiToken('my-secret-token')
    const protocols = getWebSocketProtocols()
    expect(protocols).toBeDefined()
    expect(protocols![0].startsWith('ppt-token.')).toBe(true)

    const encoded = protocols![0].replace('ppt-token.', '')
    // Decode base64url
    const base64 = encoded.replace(/-/g, '+').replace(/_/g, '/')
    const decoded = atob(base64)
    expect(decoded).toBe('my-secret-token')
  })

  it('injects Authorization Bearer in authFetch when token is present', async () => {
    setApiToken('test-bearer-token')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))

    await authFetch('/api/settings')
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/settings')
    const headers = init?.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer test-bearer-token')
  })

  it('calls onUnauthorized when response is 401', async () => {
    setApiToken('invalid-token')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
    const onUnauthorized = vi.fn()

    await authFetch('/api/settings', { onUnauthorized })
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })
})
