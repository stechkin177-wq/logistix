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

  it('реквизиты: поля заполняются из ответа и уходят в PATCH', async () => {
    const m = loggedIn([
      ['GET', /^\/api\/carriers\/\?/, { body: page([{ ...CARRIER, address: 'г. Астана, ул. 1', bank: 'Halyk', iban: 'KZ123' }]) }], ['GET', '/api/carriers/3/', { body: { ...CARRIER, address: 'г. Астана, ул. 1', bank: 'Halyk', iban: 'KZ123' } }],
        ['PATCH', '/api/carriers/3/', { body: CARRIER }],
    ])
    renderApp('/carriers')
    await userEvent.click(await screen.findByRole('link', { name: 'ИП Быстров' }))
    const drawer = await screen.findByRole('main')
    await userEvent.click(await within(drawer).findByRole('tab', { name: /Реквизиты/ }))
    expect(within(drawer).getByLabelText('Адрес')).toHaveValue('г. Астана, ул. 1')
    expect(within(drawer).getByLabelText('Банк')).toHaveValue('Halyk')
    const iban = within(drawer).getByLabelText('IBAN')
    expect(iban).toHaveValue('KZ123')
    await userEvent.clear(iban)
    await userEvent.type(iban, 'KZ999')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PATCH')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'PATCH')!.body).toMatchObject({ address: 'г. Астана, ул. 1', bank: 'Halyk', iban: 'KZ999' })
  })

  it('создание без реквизитов отправляет пустые строки', async () => {
    const m = loggedIn([['GET', /^\/api\/carriers\/\?/, { body: page([]) }], ['POST', '/api/carriers/', { status: 201, body: CARRIER }]])
    renderApp('/carriers')
    await userEvent.click((await screen.findAllByRole('button', { name: 'Новый перевозчик' }))[0]!)
    const drawer = await screen.findByRole('dialog')
    await userEvent.type(within(drawer).getByLabelText(/Название/), 'Новый')
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'POST')!.body).toMatchObject({ address: '', bank: '', iban: '' })
  })

  it('ошибка 400 по iban показывается у поля', async () => {
    loggedIn([
      ['GET', /^\/api\/carriers\/\?/, { body: page([CARRIER]) }], ['GET', '/api/carriers/3/', { body: CARRIER }],
        ['PATCH', '/api/carriers/3/', { status: 400, body: { iban: ['Убедитесь, что это значение содержит не более 34 символов.'] } }],
    ])
    renderApp('/carriers')
    await userEvent.click(await screen.findByRole('link', { name: 'ИП Быстров' }))
    const drawer = await screen.findByRole('main')
    await userEvent.click(await within(drawer).findByRole('tab', { name: /Реквизиты/ }))
    await userEvent.type(within(drawer).getByLabelText('IBAN'), 'X'.repeat(40))
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    const field = await within(drawer).findByLabelText('IBAN')
    await waitFor(() => { expect(field).toHaveAttribute('aria-invalid', 'true') })
    expect(within(drawer).getByText(/не более 34 символов/)).toBeInTheDocument()
  })
})
