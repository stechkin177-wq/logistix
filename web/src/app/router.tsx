import type { ReactElement } from 'react'
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
import { ConsignmentsPage } from '../features/consignments/pages/ConsignmentsPage'
import { DocumentsPage } from '../features/documents/DocumentsPage'
import { TemplatesPage } from '../features/documents/TemplatesPage'
import { FinancePage } from '../features/finance/FinancePage'
import { InvoiceDetailPage } from '../features/finance/InvoiceDetailPage'
import { InvoiceFormPage } from '../features/finance/InvoiceFormPage'
import { CompanyPage } from '../features/settings/company/CompanyPage'
import { DepartmentsPage } from '../features/settings/departments/DepartmentsPage'
import { HandbooksPage } from '../features/settings/handbooks/HandbooksPage'
import { NumberingPage } from '../features/settings/numbering/NumberingPage'
import { RolesPage } from '../features/settings/roles/RolesPage'
import { SettingsIndex } from '../features/settings/SettingsIndex'
import { UsersPage } from '../features/settings/users/UsersPage'
import { TrashPage } from '../features/trash/TrashPage'
import { TripsPage } from '../features/trips/pages/TripsPage'
import { AppLayout } from '../layout/AppLayout'
import { NAV, flattenNav, type NavItem } from '../layout/nav'
import { RequireAuth } from '../shared/auth/RequireAuth'
import { RootRoute } from './RootRoute'

const PAGES: Record<string, () => ReactElement> = {
  '/': DashboardPage,
  '/clients': ClientsPage,
  '/carriers': CarriersPage,
  '/orders': OrdersPage,
  '/consignments': ConsignmentsPage,
  '/trips': TripsPage,
  '/finance': FinancePage,
  '/documents': DocumentsPage,
  '/trash': TrashPage,
  '/settings/company': CompanyPage,
  '/settings/users': UsersPage,
  '/settings/departments': DepartmentsPage,
  '/settings/roles': RolesPage,
  '/settings/handbooks': HandbooksPage,
  '/settings/numbering': NumberingPage,
  '/settings/document-templates': TemplatesPage,
}

function pageFor(item: NavItem) {
  const Page = item.path === undefined ? undefined : PAGES[item.path]
  return Page ? <Page /> : <NotFoundPage />
}

/** Маршруты: каждый пункт меню с path получает страницу под проверкой доступа; /settings ведёт на первый доступный подраздел. */
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
  const financeItem = flattenNav(NAV).find((item) => item.key === 'finance')
  const financePages: RouteObject[] = financeItem
    ? [
        { path: '/finance/invoices/new', element: <RequireAccess item={financeItem}><InvoiceFormPage /></RequireAccess> },
        { path: '/finance/invoices/:id/edit', element: <RequireAccess item={financeItem}><InvoiceFormPage /></RequireAccess> },
        { path: '/finance/invoices/:id', element: <RequireAccess item={financeItem}><InvoiceDetailPage /></RequireAccess> },
      ]
    : []
  return [
    {
      element: <RootRoute />,
      children: [
        { path: '/login', element: <LoginPage /> },
        {
          element: <RequireAuth />,
          children: [{ element: <AppLayout />, children: [...pages, ...orderPages, ...financePages, { path: '/settings', element: <SettingsIndex /> }, { path: '*', element: <NotFoundPage /> }] }],
        },
      ],
    },
  ]
}

export function createAppRouter() {
  return createBrowserRouter(createRoutes())
}
