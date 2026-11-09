import type { ReactElement } from 'react'
import { Navigate, createBrowserRouter, type RouteObject } from 'react-router'
import { CarriersPage } from '../features/carriers/CarriersPage'
import { CompaniesPage } from '../features/platform/CompaniesPage'
import { HistoryPage } from '../features/platform/HistoryPage'
import { PlansPage } from '../features/platform/PlansPage'
import { DriversPage } from '../features/drivers/DriversPage'
import { VehiclesPage } from '../features/fleet/VehiclesPage'
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
import { FinanceSettingsPage } from '../features/finance/FinanceSettingsPage'
import { CompanyPage } from '../features/settings/company/CompanyPage'
import { DepartmentsPage } from '../features/settings/departments/DepartmentsPage'
import { HandbooksPage } from '../features/settings/handbooks/HandbooksPage'
import { ModulesPage } from '../features/settings/modules/ModulesPage'
import { NumberingPage } from '../features/settings/numbering/NumberingPage'
import { RolesPage } from '../features/settings/roles/RolesPage'
import { SettingsIndex } from '../features/settings/SettingsIndex'
import { UsersPage } from '../features/settings/users/UsersPage'
import { TrashPage } from '../features/trash/TrashPage'
import { TransfersPage } from '../features/tracking/pages/TransfersPage'
import { TripsPage } from '../features/trips/pages/TripsPage'
import { AppLayout } from '../layout/AppLayout'
import { NAV, flattenNav, type NavItem } from '../layout/nav'
import { PlatformLayout } from '../features/platform/PlatformLayout'
import { RequirePlatform } from '../shared/auth/RequirePlatform'
import { RequireAuth } from '../shared/auth/RequireAuth'
import { RootRoute } from './RootRoute'

const PAGES: Record<string, () => ReactElement> = {
  '/': DashboardPage,
  '/clients': ClientsPage,
  '/carriers': CarriersPage,
  '/orders': OrdersPage,
  '/consignments': ConsignmentsPage,
  '/trips': TripsPage,
  '/transfers': TransfersPage,
  '/vehicles': VehiclesPage,
  '/drivers': DriversPage,
  '/finance': FinancePage,
  '/documents': DocumentsPage,
  '/trash': TrashPage,
  '/settings/company': CompanyPage,
  '/settings/users': UsersPage,
  '/settings/departments': DepartmentsPage,
  '/settings/roles': RolesPage,
  '/settings/handbooks': HandbooksPage,
  '/settings/finance': FinanceSettingsPage,
  '/settings/modules': ModulesPage,
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
          // Центр управления платформы: отдельный контекст, свои маршруты и оболочка
          path: '/platform',
          element: <RequirePlatform />,
          children: [
            {
              element: <PlatformLayout />,
              children: [
                { index: true, element: <Navigate to="/platform/plans" replace /> },
                { path: 'plans', element: <PlansPage /> },
                { path: 'companies', element: <CompaniesPage /> },
                { path: 'history', element: <HistoryPage /> },
                { path: '*', element: <NotFoundPage /> },
              ],
            },
          ],
        },
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
