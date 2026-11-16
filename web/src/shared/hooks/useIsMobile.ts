import { useSyncExternalStore } from 'react'

const QUERY = '(max-width: 767px)'

function subscribe(listener: () => void): () => void {
  if (typeof window.matchMedia !== 'function') return () => undefined
  const mql = window.matchMedia(QUERY)
  mql.addEventListener('change', listener)
  return () => { mql.removeEventListener('change', listener) }
}

function snapshot(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(QUERY).matches
}

/** Узкий экран (телефон): тот же порог, что у md: в Tailwind. Без matchMedia (тесты) - false. */
export function useIsMobile(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false)
}
