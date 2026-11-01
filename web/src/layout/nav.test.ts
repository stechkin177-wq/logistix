import { describe, expect, it } from 'vitest'
import { ALL_PERMISSIONS } from '../test/permissions'
import { NAV, flattenNav, visibleNav, type NavItem } from './nav'

const keys = (items: NavItem[]) => flattenNav(items).map((i) => i.key)
const admin = { permissions: ALL_PERMISSIONS, modules: ['forwarding'] }

describe('visibleNav', () => {
  it('показывает всё администратору с модулем forwarding', () => {
    expect(keys(visibleNav(admin))).toEqual(keys(NAV))
  })

  it('прячет пункты модуля, если модуль не включён', () => {
    const shown = keys(visibleNav({ permissions: ALL_PERMISSIONS, modules: ['fleet'] }))
    for (const k of ['clients', 'carriers', 'orders', 'consignments', 'trips']) {
      expect(shown).not.toContain(k)
    }
    expect(shown).toContain('finance')
  })

  it('прячет пункт модуля fleet (Автопарк) без модуля и показывает с ним', () => {
    const fleet: NavItem[] = [
      { key: 'vehicles', labelKey: 'nav.vehicles', path: '/vehicles', permission: 'trips.view', module: 'fleet' },
    ]
    const perms = { permissions: ['trips.view'] }
    expect(visibleNav({ ...perms, modules: ['forwarding'] }, fleet)).toEqual([])
    expect(visibleNav({ ...perms, modules: ['fleet'] }, fleet)).toHaveLength(1)
  })

  it('прячет «Пользователи» без users.view, но оставляет остальные настройки', () => {
    const permissions = ALL_PERMISSIONS.filter((p) => p !== 'users.view')
    const shown = keys(visibleNav({ permissions, modules: ['forwarding'] }))
    expect(shown).not.toContain('users')
    expect(shown).not.toContain('departments') // тоже users.view
    expect(shown).toContain('roles')
    expect(shown).toContain('settings')
  })

  it('прячет родителя без видимых дочерних', () => {
    const shown = keys(visibleNav({ permissions: ['clients.view'], modules: ['forwarding'] }))
    expect(shown).toEqual(['clients'])
    expect(shown).not.toContain('settings')
  })

  it('прячет вложенные грузы и рейсы по их правам, заказы остаются', () => {
    const shown = keys(visibleNav({ permissions: ['orders.view'], modules: ['forwarding'] }))
    expect(shown).toContain('orders')
    expect(shown).not.toContain('consignments')
    expect(shown).not.toContain('trips')
  })

  it('пустой набор прав - пустое меню', () => {
    expect(visibleNav({ permissions: [], modules: ['forwarding'] })).toEqual([])
  })
})
