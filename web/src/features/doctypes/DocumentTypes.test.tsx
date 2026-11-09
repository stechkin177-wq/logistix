import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { loggedIn } from '../../test/harness'
import { renderApp } from '../../test/renderApp'
import { makeSession } from '../../test/fixtures'

const T = (over = {}) => ({
  id: 1, subject: 'driver', name: 'Права', fields: ['number', 'expires_at'], required: [], extra: [],
  remind: true, remind_days: [30, 7], is_active: true, archived_at: null, sort_order: 0, ...over,
})
const session = (modules: string[], permissions: string[]) => ({ session: { ...makeSession(), modules, permissions } })
const ALL = ['drivers.view', 'drivers.update', 'drivers.create', 'drivers.delete', 'fleet.view', 'fleet.update', 'fleet.create']

describe('Типы документов', () => {
  it('пункт настроек виден только при модуле и праве просмотра', async () => {
    loggedIn([], session(['drivers'], ['orders.view']))
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Основное меню' })
    expect(within(nav).queryByText('Типы документов')).not.toBeInTheDocument()
  })

  it('вкладки по видам объектов; создание типа отправляет настройки полей и напоминаний', async () => {
    const m = loggedIn(
      [
        ['GET', /^\/api\/document-types\/\?subject=driver/, { body: [T()] }],
        ['GET', /^\/api\/document-types\/\?subject=tractor/, { body: [] }],
        ['POST', '/api/document-types/', { status: 201, body: T({ id: 2 }) }],
      ],
      session(['drivers', 'fleet'], ALL),
    )
    renderApp('/settings/document-types')
    expect(await screen.findByRole('tab', { name: 'Тягачи' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Полуприцепы' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Водители' }))
    expect(await screen.findByText('Права')).toBeInTheDocument()
    expect(screen.getByText('Напоминание: за 30, 7 дн.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Новый тип' }))
    const drawer = await screen.findByRole('dialog')
    await userEvent.type(within(drawer).getByLabelText(/Название/), 'Допуск')
    await userEvent.click(within(drawer).getByLabelText('Напоминать об окончании срока'))
    await userEvent.click(within(drawer).getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/document-types/' && c.method === 'POST')).toBe(true) })
    expect(m.calls.find((c) => c.path === '/api/document-types/' && c.method === 'POST')!.body).toMatchObject({
      subject: 'driver', name: 'Допуск', required: [], remind: true, remind_days: [30, 7], is_active: true,
    })
  })

  it('архив: тип можно архивировать и вернуть, физического удаления нет', async () => {
    const m = loggedIn(
      [
        ['GET', /^\/api\/document-types\/\?subject=driver&archived=1/, { body: [T({ archived_at: '2026-11-01T00:00:00Z', is_active: false })] }],
        ['GET', /^\/api\/document-types\/\?subject=driver/, { body: [T()] }],
        ['POST', '/api/document-types/1/archive/', { body: T() }],
        ['POST', '/api/document-types/1/unarchive/', { body: T() }],
      ],
      session(['drivers'], ALL),
    )
    renderApp('/settings/document-types')
    await screen.findByText('Права')
    expect(screen.queryByRole('button', { name: 'Удалить' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'В архив' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/document-types/1/archive/')).toBe(true) })
    await userEvent.click(screen.getByLabelText('Показать архивные'))
    await userEvent.click(await screen.findByRole('button', { name: 'Вернуть из архива' }))
    await waitFor(() => { expect(m.calls.some((c) => c.path === '/api/document-types/1/unarchive/')).toBe(true) })
  })
})
