import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn } from '../../test/harness'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { renderApp } from '../../test/renderApp'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('/settings и финансы', () => {
  it('/settings ведёт на первый доступный подраздел', async () => {
    loggedIn([], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'company.view') } })
    const { router } = renderApp('/settings')
    await waitFor(() => { expect(router.state.location.pathname).toBe('/settings/users') })
  })

  it('без прав на настройки /settings - 403', async () => {
    loggedIn([], { session: { permissions: ['orders.view'] } })
    renderApp('/settings')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })

  it('/finance - честное пояснение, без «Раздел готовится»', async () => {
    loggedIn([])
    renderApp('/finance')
    expect(await screen.findByText('Счета и платежи появятся на следующем этапе')).toBeInTheDocument()
    expect(screen.queryByText('Раздел готовится')).not.toBeInTheDocument()
  })
})
