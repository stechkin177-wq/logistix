import type { ReactNode } from 'react'
import { useSession } from '../../shared/auth/useSession'
import { type NavItem, isAllowed } from '../../layout/nav'
import { ForbiddenPage } from './ForbiddenPage'

/** Прямой заход по URL в раздел без права или модуля - страница 403. Сервер всё равно проверяет. */
export function RequireAccess({ item, children }: { item: NavItem; children: ReactNode }) {
  const { session } = useSession()
  if (!session || !isAllowed(item, session)) return <ForbiddenPage />
  return children
}
