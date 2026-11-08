import { describe, expect, it } from 'vitest'
import { ALL_PERMISSIONS } from '../test/permissions'
import { NAV, flattenNav, visibleNav, type NavItem } from './nav'

const keys = (items: NavItem[]) => flattenNav(items).map((i) => i.key)
const ALL_MODULES = ['logistics', 'forwarding', 'finance', 'documents', 'fleet', 'drivers']
const admin = { permissions: ALL_PERMISSIONS, modules: ALL_MODULES }

describe('visibleNav', () => {
  it('показывает всё администратору со всеми модулями', () => {
    expect(keys(visibleNav(admin))).toEqual(keys(NAV))
  })

  it('прячет пункты модуля, если модуль не включён', () => {
    const shown = keys(visibleNav({ permissions: ALL_PERMISSIONS, modules: ['fleet'] }))
    for (const k of ['clients', 'carriers', 'orders', 'consignments', 'trips']) {
      expect(shown).not.toContain(k)
    }
    expect(shown).not.toContain('finance') // финансы теперь отдельный модуль
    expect(shown).not.toContain('documents')
  })

  it('финансы и настройки финансов зависят от модуля finance, документы и шаблоны - от documents', () => {
    const noFinance = keys(visibleNav({ permissions: ALL_PERMISSIONS, modules: ['logistics', 'forwarding', 'documents'] }))
    expect(noFinance).not.toContain('finance')
    expect(noFinance).not.toContain('financesettings')
    expect(noFinance).toContain('documents')
    expect(noFinance).toContain('doctemplates')
    const noDocs = keys(visibleNav({ permissions: ALL_PERMISSIONS, modules: ['logistics', 'forwarding', 'finance'] }))
    expect(noDocs).not.toContain('documents')
    expect(noDocs).not.toContain('doctemplates')
    expect(noDocs).toContain('finance')
    expect(noDocs).toContain('financesettings')
    // документы и финансы не требуют forwarding в меню
    const noFwd = keys(visibleNav({ permissions: ALL_PERMISSIONS, modules: ['documents'] }))
    expect(noFwd).toContain('documents')
    expect(noFwd).not.toContain('clients')
  })

  it('прячет пункт модуля fleet (Автопарк) без модуля и показывает с ним', () => {
    const fleet: NavItem[] = [
      { key: 'vehicles', labelKey: 'nav.vehicles', path: '/vehicles', permission: 'trips.view', module: 'fleet' },
    ]
    const perms = { permissions: ['trips.view'] }
    expect(visibleNav({ ...perms, modules: ['logistics'] }, fleet)).toEqual([])
    expect(visibleNav({ ...perms, modules: ['fleet'] }, fleet)).toHaveLength(1)
  })

  it('прячет «Пользователи» без users.view, но оставляет остальные настройки', () => {
    const permissions = ALL_PERMISSIONS.filter((p) => p !== 'users.view')
    const shown = keys(visibleNav({ permissions, modules: ALL_MODULES }))
    expect(shown).not.toContain('users')
    expect(shown).not.toContain('departments') // тоже users.view
    expect(shown).toContain('roles')
    expect(shown).toContain('settings')
  })

  it('прячет родителя без видимых дочерних', () => {
    const shown = keys(visibleNav({ permissions: ['clients.view'], modules: ALL_MODULES }))
    expect(shown).toEqual(['clients'])
    expect(shown).not.toContain('settings')
  })

  it('прячет вложенные грузы и рейсы по их правам, заказы остаются', () => {
    const shown = keys(visibleNav({ permissions: ['orders.view'], modules: ALL_MODULES }))
    expect(shown).toContain('orders')
    expect(shown).not.toContain('consignments')
    expect(shown).not.toContain('trips')
  })

  it('пустой набор прав - пустое меню', () => {
    expect(visibleNav({ permissions: [], modules: ALL_MODULES })).toEqual([])
  })

  it('«Документы» и «Шаблоны документов» видны только с documents.view и модулем documents', () => {
    const shown = keys(visibleNav({ permissions: ['documents.view'], modules: ALL_MODULES }))
    expect(shown).toEqual(['documents', 'settings', 'doctemplates'])
    const without = keys(visibleNav({ permissions: ALL_PERMISSIONS.filter((p) => p !== 'documents.view'), modules: ALL_MODULES }))
    expect(without).not.toContain('documents')
    expect(without).not.toContain('doctemplates')
    expect(keys(visibleNav({ permissions: ALL_PERMISSIONS, modules: ['fleet'] }))).not.toContain('documents')
  })
})
