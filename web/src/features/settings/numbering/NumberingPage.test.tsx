import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn, type MockRoutes } from '../../../test/harness'
import { ALL_PERMISSIONS } from '../../../test/permissions'
import { renderApp } from '../../../test/renderApp'

const rules = [
  { kind: 'order', name: 'Заявки', description: 'Номер заявки клиента', template: 'ORD-{year}-{index}', digits: 5, next_value: 42, sample: 'ORD-2026-00042' },
  { kind: 'trip', name: 'Рейсы', description: 'Номер рейса внутри заявки', template: '{order}-{n}', digits: 5, next_value: 1, sample: 'ORD-2026-00042-1' },
]
const base: MockRoutes = [['GET', '/api/numbering/', { body: rules }]]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Нумерация', () => {
  it('таблица правил с примером от сервера', async () => {
    loggedIn(base)
    renderApp('/settings/numbering')
    const row = (await screen.findByText('Заявки')).closest('tr')!
    expect(within(row).getByText('ORD-{year}-{index}')).toBeInTheDocument()
    expect(within(row).getByText('ORD-2026-00042')).toBeInTheDocument()
    expect(within(row).getByText('42')).toBeInTheDocument()
  })

  it('ошибка шаблона сервера ложится на поле; перечислены допустимые части', async () => {
    const m = loggedIn([['PATCH', '/api/numbering/order/', { status: 400, body: { template: ['Недопустимые плейсхолдеры: {foo}. Допустимы: {index}, {year}'] } }], ...base])
    renderApp('/settings/numbering')
    await userEvent.click(await screen.findByRole('button', { name: 'Нумерация: Заявки' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/\{year\} \{index\} \{order\} \{n\}/)).toBeInTheDocument()
    const template = within(dialog).getByLabelText(/^Шаблон/)
    await userEvent.clear(template)
    await userEvent.type(template, 'X-{{foo}')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findByText(/Недопустимые плейсхолдеры/)).toBeInTheDocument()
    expect(template).toHaveAttribute('aria-invalid', 'true')
    expect(m.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ template: 'X-{foo}', digits: 5, next_value: 42 })
  })

  it('уменьшение счётчика показывает предупреждение о дубликатах', async () => {
    loggedIn(base)
    renderApp('/settings/numbering')
    await userEvent.click(await screen.findByRole('button', { name: 'Нумерация: Заявки' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).queryByText(/возможны дубликаты/)).not.toBeInTheDocument()
    const next = within(dialog).getByLabelText('Следующее значение')
    await userEvent.clear(next)
    await userEvent.type(next, '10')
    expect(within(dialog).getByText(/возможны дубликаты, если такие номера уже выданы/)).toBeInTheDocument()
    await userEvent.clear(next)
    await userEvent.type(next, '50')
    expect(within(dialog).queryByText(/возможны дубликаты/)).not.toBeInTheDocument()
  })

  it('локальная проверка: разрядность 0..10 и счётчик от 1', async () => {
    const m = loggedIn(base)
    renderApp('/settings/numbering')
    await userEvent.click(await screen.findByRole('button', { name: 'Нумерация: Заявки' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.clear(within(dialog).getByLabelText('Разрядность'))
    await userEvent.type(within(dialog).getByLabelText('Разрядность'), '11')
    await userEvent.clear(within(dialog).getByLabelText('Следующее значение'))
    await userEvent.type(within(dialog).getByLabelText('Следующее значение'), '0')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }))
    expect(await within(dialog).findByText('Целое число от 0 до 10')).toBeInTheDocument()
    expect(within(dialog).getByText('Целое число от 1')).toBeInTheDocument()
    expect(m.calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('без numbering.update и в readonly «Изменить» отключена; без numbering.view - 403', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'numbering.update') } })
    renderApp('/settings/numbering')
    expect(await screen.findByRole('button', { name: 'Нумерация: Заявки' })).toBeDisabled()
  })

  it('в режиме только чтения правка отключена', async () => {
    loggedIn(base, { session: { subscription: { status: 'readonly', plan_code: 'start', days_left: 0, grace_days_left: null, is_free_period: false } } })
    renderApp('/settings/numbering')
    expect(await screen.findByRole('button', { name: 'Нумерация: Заявки' })).toBeDisabled()
  })

  it('без numbering.view прямой заход даёт 403', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'numbering.view') } })
    renderApp('/settings/numbering')
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument()
  })
})
