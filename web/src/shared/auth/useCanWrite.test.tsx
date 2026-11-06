import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ReadonlyBanner } from '../../layout/ReadonlyBanner'
import { mockFetch } from '../../test/fetchMock'
import { BRANDING, makeSession } from '../../test/fixtures'
import { renderWithProviders } from '../../test/renderApp'
import type { Session, SubscriptionState } from '../api/types'
import { WriteButton } from '../ui/WriteButton'
import { setTokens } from './tokens'
import { useCanWrite } from './useCanWrite'

function CanWrite({ permission }: { permission?: string }) {
  return <span data-testid="can">{String(useCanWrite(permission))}</span>
}

function withStatus(status: SubscriptionState, permissions?: string[]): Session {
  const s = makeSession(permissions ? { permissions } : {})
  return { ...s, subscription: { ...s.subscription, status, grace_days_left: status === 'grace' ? 9 : null } }
}

function setup(session: Session) {
  setTokens({ access: 'a', refresh: 'r' })
  mockFetch([
    ['GET', '/api/session/', { body: session }],
    ['GET', /^\/api\/branding\//, { body: BRANDING }],
    ['GET', '/api/company/branding/', { body: BRANDING }],
  ])
}

describe('useCanWrite / WriteButton', () => {
  it.each(['readonly', 'blocked'] as const)('отключены в статусе %s', async (status) => {
    setup(withStatus(status))
    renderWithProviders(
      <>
        <CanWrite permission="orders.create" />
        <WriteButton permission="orders.create">Создать</WriteButton>
      </>,
    )
    const button = screen.getByRole('button', { name: 'Создать' })
    await waitFor(() => {
      expect(button).toHaveAttribute('title', 'Недоступно: подписка в режиме только чтения')
    })
    expect(button).toBeDisabled()
    expect(screen.getByTestId('can')).toHaveTextContent('false')
  })

  it.each(['active', 'trial', 'grace'] as const)('включены в статусе %s при наличии права', async (status) => {
    setup(withStatus(status))
    renderWithProviders(
      <>
        <CanWrite permission="orders.create" />
        <WriteButton permission="orders.create">Создать</WriteButton>
      </>,
    )
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Создать' })).toBeEnabled()
    })
    expect(screen.getByTestId('can')).toHaveTextContent('true')
  })

  it('отключены без права даже при активной подписке', async () => {
    setup(withStatus('active', ['orders.view']))
    renderWithProviders(
      <>
        <CanWrite permission="orders.create" />
        <WriteButton permission="orders.create">Создать</WriteButton>
        <CanWrite />
      </>,
    )
    await waitFor(() => {
      expect(screen.getAllByTestId('can')[1]).toHaveTextContent('true')
    })
    expect(screen.getAllByTestId('can')[0]).toHaveTextContent('false')
    expect(screen.getByRole('button', { name: 'Создать' })).toBeDisabled()
  })
})

describe('ReadonlyBanner', () => {
  it('grace: предупреждение с числом дней', async () => {
    setup(withStatus('grace'))
    renderWithProviders(<ReadonlyBanner />)
    expect(await screen.findByText('Срок лицензии истёк, осталось 9 дн.')).toBeInTheDocument()
  })

  it('readonly: «Режим только чтения»', async () => {
    setup(withStatus('readonly'))
    renderWithProviders(<ReadonlyBanner />)
    expect(await screen.findByText('Режим только чтения')).toBeInTheDocument()
  })

  it('active: баннера нет', async () => {
    setup(withStatus('active'))
    renderWithProviders(<ReadonlyBanner />)
    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
  })
})
