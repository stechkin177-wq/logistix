import { setTokens } from '../shared/auth/tokens'
import type { PlatformSession, Session } from '../shared/api/types'
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
    ['GET', '/api/billing/usage/', { body: { results: [], warnings: [] } }],
    ['GET', /^\/api\/handbooks\/\?code=/, { body: { code: 'x', name: 'x', group: 'x', values: [] } }],
  ])
}

/** Вход в платформенном контексте (Центр управления): платформенный токен и /api/platform/session/. */
export function platformLoggedIn(routes: Routes = [], opts: { role?: 'owner' | 'admin'; companies?: PlatformSession['companies'] } = {}) {
  const role = opts.role ?? 'owner'
  setTokens({ access: 'a', refresh: 'r', context: 'platform' })
  return mockFetch([
    ...routes,
    ['GET', /^\/api\/branding\//, { body: BRANDING }],
    [
      'GET',
      '/api/platform/session/',
      {
        body: {
          context: 'platform',
          user: { id: 1, email: 'owner@x.kz', phone: null, full_name: 'Владелец', platform_role: role },
          permissions: role === 'owner' ? ['platform.read', 'platform.subscriptions.manage', 'platform.plans.manage', 'platform.companies.manage'] : ['platform.read', 'platform.subscriptions.manage'],
          companies: opts.companies ?? [],
        } satisfies PlatformSession,
      },
    ],
  ])
}
