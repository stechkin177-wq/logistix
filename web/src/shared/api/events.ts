/** Шина событий клиента API: клиент не знает о React, провайдеры подписываются. */
export type ApiEvent = 'logout' | 'blocked' | 'readonly'

type Listener = () => void

const listeners: Record<ApiEvent, Set<Listener>> = {
  logout: new Set(),
  blocked: new Set(),
  readonly: new Set(),
}

export function onApiEvent(event: ApiEvent, listener: Listener): () => void {
  listeners[event].add(listener)
  return () => {
    listeners[event].delete(listener)
  }
}

export function emitApiEvent(event: ApiEvent): void {
  for (const listener of [...listeners[event]]) listener()
}
