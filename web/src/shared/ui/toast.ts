import { useSyncExternalStore } from 'react'

export interface Toast {
  id: number
  kind: 'info' | 'warning' | 'error'
  message: string
  /** Ссылка действия (например, на созданный рейс). */
  action?: { label: string; to: string }
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

/** Показывает уведомление на 6 секунд (с ссылкой - на 12). message и action.label - уже переведённый текст. */
export function pushToast(kind: Toast['kind'], message: string, action?: Toast['action']): void {
  const id = nextId++
  toasts = [...toasts, { id, kind, message, action }].slice(-4)
  emit()
  setTimeout(() => {
    dismissToast(id)
  }, action ? 12000 : 6000)
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
