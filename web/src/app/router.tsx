import { createBrowserRouter, type RouteObject } from 'react-router'
import { DashboardPage } from '../features/dashboard/DashboardPage'
import { LoginPage } from '../features/auth/LoginPage'
import { NotFoundPage } from '../features/errors/NotFoundPage'
import { RequireAccess } from '../features/errors/RequireAccess'
import { PlaceholderPage } from '../features/placeholder/PlaceholderPage'
import { AppLayout } from '../layout/AppLayout'
import { NAV, flattenNav, type NavItem } from '../layout/nav'
import { RequireAuth } from '../shared/auth/RequireAuth'
import { RootRoute } from './RootRoute'

function pageFor(item: NavItem) {
  if (item.path === '/') return <DashboardPage />
  return <PlaceholderPage titleKey={item.labelKey} />
}

/** Маршруты: каждый пункт меню с path получает страницу (заглушку до Task 16) под проверкой доступа. */
export function createRoutes(): RouteObject[] {
  const pages: RouteObject[] = flattenNav(NAV)
    .filter((item): item is NavItem & { path: string } => item.path !== undefined)
    .map((item) => ({
      path: item.path,
      element: <RequireAccess item={item}>{pageFor(item)}</RequireAccess>,
    }))
  return [
    {
      element: <RootRoute />,
      children: [
        { path: '/login', element: <LoginPage /> },
        {
          element: <RequireAuth />,
          children: [{ element: <AppLayout />, children: [...pages, { path: '*', element: <NotFoundPage /> }] }],
        },
      ],
    },
  ]
}

export function createAppRouter() {
  return createBrowserRouter(createRoutes())
}
