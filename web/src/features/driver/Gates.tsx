import { Navigate, Outlet } from 'react-router'
import { isDriverOnly } from '../../shared/auth/driver'
import { useSession } from '../../shared/auth/useSession'

/** Область /driver требует права driver.use (иначе - на главную офисного сайта). */
export function RequireDriver() {
  const { session } = useSession()
  if (session && !session.permissions.includes('driver.use')) return <Navigate to="/" replace />
  return <Outlet />
}

/** Водитель (роль только с driver.use) офисных страниц не видит: его место - /driver. */
export function DriverRedirect() {
  const { session } = useSession()
  if (isDriverOnly(session)) return <Navigate to="/driver" replace />
  return <Outlet />
}
