// Frontend Authentication and Secure Transport
// PR #28 Hardening: Token in memory + sessionStorage, base64url WebSocket subprotocol,
// authenticated fetch wrapper, Blob export.

const SESSION_STORAGE_KEY = 'ppt_api_token'

let inMemoryToken: string = ''

// Initialize from sessionStorage if available
try {
  if (typeof window !== 'undefined' && window.sessionStorage) {
    inMemoryToken = window.sessionStorage.getItem(SESSION_STORAGE_KEY) || ''
  }
} catch {
  // Ignore sessionStorage access errors
}

export function getApiToken(): string {
  return inMemoryToken
}

export function setApiToken(token: string): void {
  inMemoryToken = (token || '').trim()
  try {
    if (typeof window !== 'undefined' && window.sessionStorage) {
      if (inMemoryToken) {
        window.sessionStorage.setItem(SESSION_STORAGE_KEY, inMemoryToken)
      } else {
        window.sessionStorage.removeItem(SESSION_STORAGE_KEY)
      }
    }
  } catch {
    // Ignore sessionStorage errors
  }
}

export function clearApiToken(): void {
  setApiToken('')
}

/**
 * Base64URL encode a string (handles full UTF-8 reliably via TextEncoder)
 */
export function toBase64Url(str: string): string {
  if (!str) return ''
  const bytes = new TextEncoder().encode(str)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

/**
 * Builds WebSocket protocols array for authenticated handshake
 */
export function getWebSocketProtocols(): string[] | undefined {
  const token = getApiToken()
  if (!token) return undefined
  return [`ppt-token.${toBase64Url(token)}`]
}

export interface AuthFetchOptions extends RequestInit {
  onUnauthorized?: () => void
}

/**
 * Authenticated fetch wrapper that injects Authorization Bearer if token is set.
 */
export async function authFetch(input: RequestInfo | URL, init?: AuthFetchOptions): Promise<Response> {
  const token = getApiToken()
  const headers = new Headers(init?.headers || {})

  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(input, {
    ...init,
    headers
  })

  if (response.status === 401) {
    if (init?.onUnauthorized) {
      init.onUnauthorized()
    }
  }

  return response
}
