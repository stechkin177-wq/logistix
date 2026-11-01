import { vi } from 'vitest'

export interface MockCall {
  method: string
  path: string
  headers: Record<string, string>
  body: unknown
}

export interface MockReply {
  status?: number
  body?: unknown
}

type Handler = MockReply | ((call: MockCall) => MockReply | Promise<MockReply>)

interface Route {
  method: string
  path: string | RegExp
  handler: Handler
}

/** Заглушка fetch без зависимостей: маршруты по методу+пути (без хоста), журнал вызовов. */
export function mockFetch(routes: [string, string | RegExp, Handler][]) {
  const table: Route[] = routes.map(([method, path, handler]) => ({ method, path, handler }))
  const calls: MockCall[] = []
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost')
    const method = (init?.method ?? 'GET').toUpperCase()
    const path = url.pathname + url.search
    const headers = Object.fromEntries(Object.entries((init?.headers ?? {}) as Record<string, string>))
    const raw = init?.body
    const call: MockCall = {
      method,
      path,
      headers,
      body: typeof raw === 'string' ? (JSON.parse(raw) as unknown) : raw,
    }
    calls.push(call)
    const route = table.find(
      (r) => r.method === method && (typeof r.path === 'string' ? r.path === path : r.path.test(path)),
    )
    if (!route) return new Response(JSON.stringify({ detail: `no mock ${method} ${path}` }), { status: 599 })
    const reply = typeof route.handler === 'function' ? await route.handler(call) : route.handler
    const status = reply.status ?? 200
    return new Response(reply.body === undefined ? null : JSON.stringify(reply.body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fn)
  return { fn, calls, count: (method: string, path: string | RegExp) =>
    calls.filter((c) => c.method === method && (typeof path === 'string' ? c.path === path : path.test(c.path))).length }
}
