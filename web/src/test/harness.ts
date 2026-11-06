import { setTokens } from '../shared/auth/tokens'
import type { Session } from '../shared/api/types'
import { mockFetch } from './fetchMock'
import { BRANDING, makeSession } from './fixtures'

export type MockRoutes = Parameters<typeof mockFetch>[0]
type Routes = MockRoutes

/**
 * Вход в тестах: токены + мок fetch. Маршруты теста идут первыми (первый совпавший побеждает), затем
 * сессия/брендинг и пустые справочники. Возвращает заглушку (calls, count).
 */
export function loggedIn(routes: Routes = [], opts: { session?: Partial<Session> } = {}) {
  setTokens({ access: 'a', refresh: 'r' })
  return mockFetch([
    ...routes,
    ['GET', /^\/api\/branding\//, { body: BRANDING }],
    ['GET', '/api/session/', { body: makeSession(opts.session) }],
    ['GET', /^\/api\/handbooks\/\?code=/, { body: { code: 'x', name: 'x', group: 'x', values: [] } }],
  ])
}
