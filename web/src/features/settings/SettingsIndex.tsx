import { Navigate } from 'react-router'
import { ForbiddenPage } from '../errors/ForbiddenPage'
import { flattenNav, isAllowed, NAV } from '../../layout/nav'
import { useSession } from '../../shared/auth/useSession'

/** /settings без подраздела: первая доступная страница настроек, иначе 403. */
export function SettingsIndex() {
  const { session } = useSession()
  const group = NAV.find((item) => item.key === 'settings')
  const first = session
    ? flattenNav(group?.children ?? []).find((item) => item.path !== undefined && isAllowed(item, session))
    : undefined
  if (!first?.path) return <ForbiddenPage />
  return <Navigate to={first.path} replace />
}
