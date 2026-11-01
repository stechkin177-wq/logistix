import { createBrowserRouter, type RouteObject } from 'react-router'
import { CarriersPage } from '../features/carriers/CarriersPage'
import { ClientsPage } from '../features/clients/ClientsPage'
import { OrderDetailPage } from '../features/orders/pages/OrderDetailPage'
import { OrderFormPage } from '../features/orders/pages/OrderFormPage'
import { OrdersPage } from '../features/orders/pages/OrdersPage'
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
  if (item.path === '/clients') return <ClientsPage />
  if (item.path === '/carriers') return <CarriersPage />
  if (item.path === '/orders') return <OrdersPage />
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
  // страницы заказа живут под разделом «Заказы» и наследуют его проверку доступа
  const ordersItem = flattenNav(NAV).find((item) => item.key === 'orders')
  const orderPages: RouteObject[] = ordersItem
    ? [
        { path: '/orders/new', element: <RequireAccess item={ordersItem}><OrderFormPage /></RequireAccess> },
        { path: '/orders/:id', element: <RequireAccess item={ordersItem}><OrderDetailPage /></RequireAccess> },
      ]
    : []
  return [
    {
      element: <RootRoute />,
      children: [
        { path: '/login', element: <LoginPage /> },
        {
          element: <RequireAuth />,
          children: [{ element: <AppLayout />, children: [...pages, ...orderPages, { path: '*', element: <NotFoundPage /> }] }],
        },
      ],
    },
  ]
}

export function createAppRouter() {
  return createBrowserRouter(createRoutes())
}
