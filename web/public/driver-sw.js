/* Service worker мобильной версии водителя (область /driver/).
   - оболочка приложения и ресурсы сборки: сначала сеть, при её отсутствии кэш (приложение открывается без связи);
   - данные водителя (GET /api/driver/): сначала сеть, при отсутствии связи последние сохранённые;
   - всё остальное (запись, чужие адреса) не трогаем. Кэш данных стирается при выходе (clearDriverCache). */
const SHELL = 'driver-shell-v1'
const API = 'driver-api-v1'

self.addEventListener('install', () => { self.skipWaiting() })
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith('driver-shell-') && key !== SHELL) await caches.delete(key)
    }
    await self.clients.claim()
  })())
})

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName)
  try {
    const response = await fetch(request)
    if (response.ok) await cache.put(request, response.clone())
    return response
  } catch (error) {
    const cached = await cache.match(request)
    if (cached) return cached
    throw error
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/driver/')) {
    event.respondWith(networkFirst(request, API))
  } else if (request.mode === 'navigate' && url.pathname.startsWith('/driver')) {
    event.respondWith(networkFirst(new Request('/driver'), SHELL))
  } else if (url.pathname.startsWith('/assets/') || url.pathname.startsWith('/driver-')) {
    event.respondWith(networkFirst(request, SHELL))
  }
})
