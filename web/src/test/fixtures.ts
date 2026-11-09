import { ALL_PERMISSIONS } from './permissions'
import type { Session } from '../shared/api/types'

export function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    user: { id: 1, email: 'admin@example.kz', phone: null, full_name: 'Админ Админов', platform_role: '' },
    company: { id: 10, name: 'Альфа', timezone: 'Asia/Almaty', language: 'ru' },
    companies: [{ id: 10, name: 'Альфа' }],
    role: { id: 1, name: 'Администратор' },
    modules: ['logistics', 'forwarding', 'finance', 'documents'],
    permissions: ALL_PERMISSIONS,
    branding: { app_name: 'Logistix', logo_url: null, primary_color: '#2563EB', theme: 'light' },
    subscription: {
      status: 'active',
      plan_code: 'start',
      days_left: 30,
      grace_days_left: null,
      is_free_period: false,
    },
    ...overrides,
  }
}

export const BRANDING = {
  app_name: 'Logistix',
  logo_url: null,
  primary_color: '#2563EB',
  theme: 'light',
}

/** Конверт постраничного ответа бэкенда. */
export function page<T>(results: T[], count = results.length) {
  return { count, next: null, previous: null, results }
}
