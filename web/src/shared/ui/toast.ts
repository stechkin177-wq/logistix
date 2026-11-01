import { useSyncExternalStore } from 'react'

export interface Toast {
  id: number
  kind: 'info' | 'warning' | 'error'
  message: string
}

let toasts: Toast[] = []
let nextId = 1
const subscribers = new Set<() => void>()

function emit(): void {
  for (const fn of subscribers) fn()
}

export function dismissToast(id: number): void {
  toasts = toasts.filter((t) => t.id !== id)
  emit()
}

/** Показывает уведомление на 6 секунд. message - уже переведённый текст. */
export function pushToast(kind: Toast['kind'], message: string): void {
  const id = nextId++
  toasts = [...toasts, { id, kind, message }].slice(-4)
  emit()
  setTimeout(() => {
    dismissToast(id)
  }, 6000)
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(
    (fn) => {
      subscribers.add(fn)
      return () => {
        subscribers.delete(fn)
      }
    },
    () => toasts,
  )
}
