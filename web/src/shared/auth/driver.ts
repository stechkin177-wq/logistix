import type { Session } from '../api/types'

/** Только вход в мобильную версию (роль «Водитель»): офисные страницы такому пользователю недоступны. */
export function isDriverOnly(session: Session | null | undefined): boolean {
  return !!session && session.permissions.length > 0 && session.permissions.every((p) => p === 'driver.use')
}
