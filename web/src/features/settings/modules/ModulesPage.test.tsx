import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loggedIn, type MockRoutes } from '../../../test/harness'
import { ALL_PERMISSIONS } from '../../../test/permissions'
import { renderApp } from '../../../test/renderApp'
import type { CompanyModuleInfo } from './api'

const mod = (over: Partial<CompanyModuleInfo> & { code: string; name: string }): CompanyModuleInfo => ({
  description: '', status: 'available', is_core: false, enabled: false, available_in_plan: true, effective: false,
  requires: ['core'], enhances: [], dependents: [], can_enable: true, can_disable: false, blocker: null, ...over,
})

const MODULES: CompanyModuleInfo[] = [
  mod({ code: 'core', name: 'Основа', is_core: true, enabled: true, effective: true, requires: [], can_enable: false }),
  mod({
    code: 'forwarding', name: 'Экспедирование', enabled: true, effective: true, dependents: ['finance'], can_enable: false,
    blocker: { code: 'module_has_dependents', detail: 'x', modules: ['finance'] },
  }),
  mod({ code: 'finance', name: 'Финансы', enabled: true, effective: true, requires: ['core', 'forwarding'], can_enable: false, can_disable: true }),
  mod({ code: 'documents', name: 'Документы', enabled: true, effective: true, can_enable: false, can_disable: true }),
  mod({ code: 'fleet', name: 'Автопарк', can_enable: true }),
  mod({ code: 'gps', name: 'GPS-мониторинг', status: 'beta', requires: ['fleet'], can_enable: false, blocker: { code: 'module_requires', detail: 'y', modules: ['fleet'] } }),
  mod({ code: 'drivers', name: 'Водители', available_in_plan: false, can_enable: false, blocker: { code: 'module_not_in_plan', detail: 'z', modules: null } }),
]
const PROFILES = [
  { code: 'forwarder', name: 'Экспедитор', description: '', modules: ['forwarding', 'finance', 'documents'], unavailable_modules: [], already_enabled: [] },
  { code: 'carrier', name: 'Перевозчик', description: '', modules: ['forwarding', 'fleet', 'drivers', 'documents'], unavailable_modules: ['drivers'], already_enabled: [] },
]
const body = (modules = MODULES) => ({ plan_code: 'start', modules })
const base: MockRoutes = [
  ['GET', '/api/company/modules/', { body: body() }],
  ['GET', '/api/activity-profiles/', { body: PROFILES }],
]

afterEach(() => { vi.unstubAllGlobals() })

describe('Модули компании', () => {
  it('пункт меню и маршрут доступны только с company.manage_modules', async () => {
    loggedIn(base, { session: { permissions: ALL_PERMISSIONS.filter((p) => p !== 'company.manage_modules') } })
    renderApp('/settings/modules')
    expect(await screen.findByText(/нет доступа/i)).toBeInTheDocument()
    expect(screen.queryByText('Модули компании', { selector: 'h1' })).not.toBeInTheDocument()
  })

  it('список с переключателями, зависимостями и подсказками', async () => {
    loggedIn(base)
    renderApp('/settings/modules')
    expect(await screen.findByRole('heading', { name: 'Модули компании' })).toBeInTheDocument()
    expect(await screen.findByLabelText('Модуль «Основа»')).toBeDisabled()
    expect(screen.getByLabelText('Модуль «Финансы»')).toBeChecked()
    expect(screen.getByLabelText('Модуль «Автопарк»')).not.toBeChecked()
    expect(screen.getByText(/Сначала включите: Автопарк/)).toBeInTheDocument()
    expect(screen.getByText('Нет в тарифе')).toBeInTheDocument()
    expect(screen.getByLabelText('Модуль «Водители»')).toBeDisabled()
    expect(screen.getByLabelText('Модуль «GPS-мониторинг»')).toBeDisabled()
    expect(screen.getByText('Бета')).toBeInTheDocument()
  })

  it('включение отправляет POST и обновляет список', async () => {
    const after = MODULES.map((m) => (m.code === 'fleet' ? { ...m, enabled: true, can_enable: false, can_disable: true } : m))
    const m = loggedIn([['POST', '/api/company/modules/fleet/enable/', { body: body(after) }], ...base])
    renderApp('/settings/modules')
    await userEvent.click(await screen.findByLabelText('Модуль «Автопарк»'))
    await waitFor(() => { expect(screen.getByLabelText('Модуль «Автопарк»')).toBeChecked() })
    expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it('отключение требует причину и не отправляется без неё', async () => {
    const after = MODULES.map((x) => (x.code === 'documents' ? { ...x, enabled: false, can_enable: true, can_disable: false } : x))
    const m = loggedIn([['POST', '/api/company/modules/documents/disable/', { body: body(after) }], ...base])
    renderApp('/settings/modules')
    await userEvent.click(await screen.findByLabelText('Модуль «Документы»'))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отключить' }))
    expect(await within(dialog).findByText('Укажите причину отключения')).toBeInTheDocument()
    expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(0)
    await userEvent.type(within(dialog).getByLabelText(/Причина отключения/), 'Не используем')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отключить' }))
    await waitFor(() => { expect(screen.queryByRole('dialog')).not.toBeInTheDocument() })
    const post = m.calls.find((c) => c.method === 'POST')
    expect(post?.body).toEqual({ reason: 'Не используем', cascade: false })
    expect(screen.getByLabelText('Модуль «Документы»')).not.toBeChecked()
  })

  it('отключение с зависимыми требует подтверждения каскада', async () => {
    const m = loggedIn([['POST', '/api/company/modules/forwarding/disable/', { body: body() }], ...base])
    renderApp('/settings/modules')
    await userEvent.click(await screen.findByLabelText('Модуль «Экспедирование»'))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/От модуля зависят: Финансы/)).toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText(/Причина отключения/), 'Больше не нужен')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отключить' }))
    expect(await within(dialog).findByText('Подтвердите отключение зависимых модулей')).toBeInTheDocument()
    expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(0)
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /Отключить вместе с зависимыми/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отключить' }))
    await waitFor(() => { expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(1) })
    expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ reason: 'Больше не нужен', cascade: true })
  })

  it('двойной клик по «Отключить» отправляет один запрос', async () => {
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => { release = resolve })
    const m = loggedIn([
      ['POST', '/api/company/modules/documents/disable/', { body: async () => { await gate; return body() } }],
      ...base,
    ])
    renderApp('/settings/modules')
    await userEvent.click(await screen.findByLabelText('Модуль «Документы»'))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Причина отключения/), 'x')
    const button = within(dialog).getByRole('button', { name: 'Отключить' })
    await userEvent.dblClick(button)
    release()
    await waitFor(() => { expect(m.calls.filter((c) => c.method === 'POST')).toHaveLength(1) })
  })

  it('ошибка сервера показывается в диалоге', async () => {
    loggedIn([['POST', '/api/company/modules/finance/disable/', { status: 409, body: { detail: 'Нельзя', code: 'module_protected' } }], ...base])
    renderApp('/settings/modules')
    await userEvent.click(await screen.findByLabelText('Модуль «Финансы»'))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Причина отключения/), 'x')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отключить' }))
    expect(await within(dialog).findByText(/новый финансовый учёт/)).toBeInTheDocument()
  })

  it('профиль: выбор, подтверждение, отчёт о пропущенных модулях', async () => {
    const result = { enabled: ['fleet'], disabled: [], skipped: [{ code: 'drivers', error_code: 'module_not_in_plan', detail: '' }] }
    const m = loggedIn([['POST', '/api/company/modules/apply-profile/', { body: { ...body(), result } }], ...base])
    renderApp('/settings/modules')
    await screen.findByRole('option', { name: 'Перевозчик' })
    await userEvent.selectOptions(screen.getByLabelText('Профиль'), 'carrier')
    expect(screen.getByText(/нет в тарифе: Водители/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Применить профиль' }))
    const dialog = await screen.findByRole('alertdialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Применить профиль' }))
    expect(await screen.findByText(/Пропущено: Водители/)).toBeInTheDocument()
    expect(m.calls.find((c) => c.method === 'POST')?.body).toEqual({ profile: 'carrier', replace: false, reason: '' })
  })

  it('в режиме только чтения переключатели отключены', async () => {
    loggedIn(base, { session: { subscription: { status: 'readonly', plan_code: 'start', days_left: 0, grace_days_left: 0, is_free_period: false } } })
    renderApp('/settings/modules')
    expect(await screen.findByLabelText('Модуль «Автопарк»')).toBeDisabled()
  })
})
