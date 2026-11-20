import { useEffect } from 'react'

/** Подключает манифест и service worker только в области /driver (на офисных страницах их нет). */
export function useDriverPwa(): void {
  useEffect(() => {
    const link = document.createElement('link')
    link.rel = 'manifest'
    link.href = '/driver.webmanifest'
    document.head.appendChild(link)
    if ('serviceWorker' in navigator) {
      void navigator.serviceWorker.register('/driver-sw.js', { scope: '/driver/' }).catch(() => undefined)
    }
    return () => { link.remove() }
  }, [])
}

/** Выход: кэш данных водителя (рейсы, профиль) стирается, чтобы на общем телефоне ничего не осталось. */
export async function clearDriverCache(): Promise<void> {
  if (typeof caches === 'undefined') return
  await caches.delete('driver-api-v1').catch(() => false)
}
