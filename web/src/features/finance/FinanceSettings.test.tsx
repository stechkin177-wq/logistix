import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ALL_PERMISSIONS } from '../../test/permissions'
import { loggedIn, type MockRoutes } from '../../test/harness'
import { renderApp } from '../../test/renderApp'
import type { FinanceSettings, StatusMappingReport } from './ledgerTypes'

const KZT = { id: 1, code: 'KZT', name: 'Тенге' }
const SETTINGS: FinanceSettings = {
  base_currency: KZT, accounting_method: 'ACCRUAL', default_vat_rate: null, fiscal_year_start_month: 1, allow_backdating: true,
  engine: 'shadow', cutover_date: null, completed_status: null, expense_creation_mode: 'manual', sync_carrier_price: true,
  engine_switched_at: null, financial_writes_frozen: false, unmapped: ['COMPLETED'], switch_blocked: true,
  blockers: [{ code: 'unmapped_system_codes', message: 'Не сопоставлены системные коды статусов рейса: COMPLETED' }],
}
const MAPPING: StatusMappingReport = {
  values: [
    { id: 11, name: 'Доставлен', code: '', is_active: true, is_final: true, is_initial: false },
    { id: 12, name: 'Планируется', code: 'PLANNED', is_active: true, is_final: false, is_initial: true },
  ],
  unmapped: [{ code: 'COMPLETED', reason: 'нет значения', candidates: [{ id: 11, name: 'Доставлен' }] }],
  unmapped_system_codes: ['COMPLETED'], completed_status: null, switch_blocked: true, blockers: SETTINGS.blockers,
}
const base: MockRoutes = [
  ['GET', '/api/finance/settings/', { body: SETTINGS }],
  ['GET', '/api/finance/settings/status-mapping/', { body: MAPPING }],
  ['GET', '/api/finance/periods/', { body: [{ id: 3, year: 2026, month: 6, status: 'closed', closed_at: '2026-07-01T10:00:00Z', closed_by: 'a@b.kz', comment: '', events: [] }] }],
  ['GET', '/api/finance/migration/', { body: { runs: [], open_issues: [{ id: 21, issue_type: 'ambiguous_trip_expense', severity: 'error', source_model: 'forwarding.orderservice', source_id: 5, message: 'Рейс не найден', status: 'open', resolution: '' }], open_count: 1 } }],
  ['GET', /^\/api\/handbooks\/\?code=currency/, { body: { code: 'currency', name: 'Валюты', group: 'x', values: [
    { id: 1, name: 'Тенге', code: 'KZT', order: 1, is_initial: false, is_final: false, is_active: true },
    { id: 2, name: 'Доллар', code: 'USD', order: 2, is_initial: false, is_final: false, is_active: true },
  ] } }],
]

afterEach(() => { vi.unstubAllGlobals() })

describe('Настройки финансов', () => {
  it('пункт меню и страница недоступны без finance.manage_settings', async () => {
    loggedIn([], { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.manage_settings') } })
    renderApp('/settings/finance')
    await screen.findByRole('navigation')
    expect(screen.queryByRole('link', { name: 'Настройки финансов' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Настройки финансов' })).not.toBeInTheDocument()
  })

  it('смена базовой валюты отправляет валюту и причину; без причины кнопка отключена', async () => {
    const m = loggedIn([
      ...base,
      ['PATCH', '/api/finance/settings/', { body: { ...SETTINGS, base_currency: { id: 2, code: 'USD', name: 'Доллар' } } }],
    ])
    const user = userEvent.setup()
    renderApp('/settings/finance')
    await screen.findByRole('heading', { name: 'Настройки финансов' })
    const section = screen.getByRole('region', { name: 'Базовая валюта' })
    const change = within(section).getByRole('button', { name: 'Сменить валюту' })
    expect(change).toBeDisabled()
    await user.selectOptions(await within(section).findByLabelText('Новая валюта'), 'USD')
    expect(change).toBeDisabled() // нужна причина
    await user.type(within(section).getByLabelText('Причина'), 'Переход на доллар')
    await user.click(change)
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'PATCH')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ base_currency: 2, reason: 'Переход на доллар' })
  })

  it('флаги правил отправляются сразу, ошибка сервера показывается', async () => {
    loggedIn([
      ...base,
      ['PATCH', '/api/finance/settings/', { status: 400, body: { detail: 'Нельзя', code: 'setting_invalid' } }],
    ])
    const user = userEvent.setup()
    renderApp('/settings/finance')
    await user.click(await screen.findByRole('checkbox', { name: /задним числом/ }))
    expect(await screen.findByText('Нельзя')).toBeInTheDocument()
  })

  it('сопоставление статусов: блокировка переключения и назначение кода', async () => {
    const m = loggedIn([
      ...base,
      ['POST', '/api/finance/settings/status-mapping/', { status: 201, body: { ...MAPPING, unmapped: [], unmapped_system_codes: [], switch_blocked: false, blockers: [] } }],
    ])
    const user = userEvent.setup()
    renderApp('/settings/finance')
    const section = await screen.findByRole('region', { name: 'Сопоставление статусов рейса' })
    expect(await within(section).findByText(/Переключение на новый учёт заблокировано/)).toBeInTheDocument()
    const assign = within(section).getByRole('button', { name: 'Назначить' })
    expect(assign).toBeDisabled()
    await user.selectOptions(within(section).getByLabelText('Статус рейса'), '11')
    await user.click(assign)
    await waitFor(() => { expect(m.calls.some((c) => c.method === 'POST')).toBe(true) })
    expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ value: 11, code: 'COMPLETED' })
  })

  it('закрытие месяца и повторное открытие требуют отдельных прав', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'finance.reopen_period') } })
    renderApp('/settings/finance')
    const section = await screen.findByRole('region', { name: 'Закрытые месяцы' })
    expect(within(section).getByRole('button', { name: 'Закрыть месяц' })).toBeEnabled()
    expect(await within(section).findByRole('button', { name: 'Открыть повторно' })).toBeDisabled()
  })

  it('миграция: спорную строку нельзя разрешить без решения; решение уходит на сервер', async () => {
    const m = loggedIn([...base, ['POST', '/api/finance/migration/issues/21/resolve/', { body: { id: 21 } }]])
    const user = userEvent.setup()
    renderApp('/settings/finance')
    const section = await screen.findByRole('region', { name: 'Статус миграции' })
    await user.click(await within(section).findByRole('button', { name: 'Разрешить' }))
    const dialog = await screen.findByRole('dialog')
    const submit = within(dialog).getByRole('button', { name: 'Разрешить' })
    expect(submit).toBeDisabled()
    await user.selectOptions(within(dialog).getByLabelText(/^Решение/), 'justified_exclusion')
    await user.type(within(dialog).getByLabelText(/^Комментарий/), 'Списано по акту №7')
    await user.click(submit)
    await waitFor(() => { expect(m.calls.some((c) => c.path.endsWith('/resolve/'))).toBe(true) })
    expect(m.calls.find((c) => c.path.endsWith('/resolve/'))?.body).toEqual({ resolution: 'justified_exclusion', note: 'Списано по акту №7' })
  })
})
