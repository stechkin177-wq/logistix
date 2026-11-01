import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'
import { ApiError } from '../shared/api/errors'
import i18n from '../shared/i18n'

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        // повторяем только сбои сети и 5xx; ошибки 4xx повтор не лечит
        retry: (count, error) =>
          count < 2 && (!(error instanceof ApiError) || error.status === 0 || error.status >= 500),
      },
    },
  })
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient)
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </I18nextProvider>
  )
}
