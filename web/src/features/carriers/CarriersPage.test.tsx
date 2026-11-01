import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page } from '../../test/fixtures'
import { loggedIn } from '../../test/harness'
import { renderApp } from '../../test/renderApp'

const CARRIER = {
  id: 3, name: 'ИП Быстров', bin_iin: '', type: null, type_name: null, status: 'inactive', rating: '4.5', notes: '',
  contacts: [], created_at: '2026-10-01T05:00:00Z',
}

describe('Перевозчики', () => {
  it('строки, рейтинг и сортировка по рейтингу уходит в ordering', async () => {
    const m = loggedIn([['GET', /^\/api\/carriers\/\?/, { body: page([CARRIER]) }]])
    const { router } = renderApp('/carriers')
    expect(await screen.findByText('ИП Быстров')).toBeInTheDocument()
    expect(screen.getByText('4.5')).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByText('Неактивен')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Сортировать по: Рейтинг' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path.includes('ordering=rating')) ).toBe(true) })
    expect(router.state.location.search).toContain('ordering=rating')
    expect(screen.getByRole('columnheader', { name: /Рейтинг/ })).toHaveAttribute('aria-sort', 'ascending')
  })

  it('создание отправляет рейтинг строкой и закрывает панель', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/carriers\/\?/, { body: page([]) }],
      ['POST', '/api/carriers/', { status: 201, body: CARRIER }],
    ])
    renderApp('/carriers')
    await userEvent.click((await screen.findAllByRole('button', { name: 'Новый перевозчик' }))[0]!)
    const drawer = await screen.findByRole('dialog')
    await userEvent.type(within(drawer).getByLabelText(/Название/), 'ИП Быстров')
    await userEvent.type(within(drawer).getByLabelText('Рейтинг'), '4.5')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(screen.queryByRole('dialog')).not.toBeInTheDocument() })
    expect(m.calls.find((c) => c.method === 'POST')!.body).toMatchObject({ name: 'ИП Быстров', rating: '4.5', type: null })
  })

  it('неверный рейтинг блокирует отправку', async () => {
    const m = loggedIn([['GET', /^\/api\/carriers\/\?/, { body: page([]) }]])
    renderApp('/carriers')
    await userEvent.click((await screen.findAllByRole('button', { name: 'Новый перевозчик' }))[0]!)
    const drawer = await screen.findByRole('dialog')
    await userEvent.type(within(drawer).getByLabelText(/Название/), 'X')
    await userEvent.type(within(drawer).getByLabelText('Рейтинг'), '9')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    expect(await within(drawer).findByText(/Рейтинг от 0 до 5/)).toBeInTheDocument()
    expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })
})
