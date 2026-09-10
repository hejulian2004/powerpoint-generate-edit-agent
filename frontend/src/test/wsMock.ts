export interface FakeWebSocketMessage {
  data: string
}

export class FakeWebSocket {
  static OPEN = 1
  static CLOSED = 3
  static CONNECTING = 0
  static CLOSING = 2
  static instances: FakeWebSocket[] = []

  url: string
  readyState = FakeWebSocket.OPEN
  sent: string[] = []
  onopen: ((event: unknown) => void) | null = null
  onclose: ((event: unknown) => void) | null = null
  onerror: ((event: unknown) => void) | null = null
  onmessage: ((event: FakeWebSocketMessage) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.({})
  }

  emit(type: string, payload: Record<string, unknown> = {}) {
    this.onmessage?.({ data: JSON.stringify({ type, ...payload }) })
  }

  sentMessages(): Array<Record<string, any>> {
    return this.sent.map((raw) => JSON.parse(raw))
  }

  static reset() {
    FakeWebSocket.instances = []
  }

  static latest(): FakeWebSocket {
    const instance = FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
    if (!instance) {
      throw new Error('No FakeWebSocket instance has been created')
    }
    return instance
  }
}

export function installFakeWebSocket() {
  FakeWebSocket.reset()
  ;(globalThis as any).WebSocket = FakeWebSocket
}
