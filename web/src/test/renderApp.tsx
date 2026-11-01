import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { makeQueryClient } from '../app/providers'
import { createRoutes } from '../app/router'
import { AuthProvider } from '../shared/auth/AuthProvider'
import i18n from '../shared/i18n'

function wrap(children: ReactNode) {
  const client = makeQueryClient()
  client.setDefaultOptions({ queries: { retry: false, staleTime: 0 } })
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </I18nextProvider>
  )
}

/** Всё приложение (маршруты, провайдеры) на memory-router. */
export function renderApp(path = '/') {
  const router = createMemoryRouter(createRoutes(), { initialEntries: [path] })
  const utils = render(wrap(<RouterProvider router={router} />))
  return { router, ...utils }
}

/** Отдельный компонент внутри провайдеров и роутера (для ReadonlyBanner, WriteButton и т.п.). */
export function renderWithProviders(ui: ReactNode, path = '/') {
  const router = createMemoryRouter(
    [{ path: '*', element: <RootWrapper>{ui}</RootWrapper> }],
    { initialEntries: [path] },
  )
  return { router, ...render(wrap(<RouterProvider router={router} />)) }
}

function RootWrapper({ children }: { children: ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
}
