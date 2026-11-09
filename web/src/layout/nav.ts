import type { Session } from '../shared/api/types'

export interface NavItem {
  key: string
  /** Ключ i18n подписи. */
  labelKey: string
  /** Путь; у группы без собственной страницы (Настройки) его нет. */
  path?: string
  /** Право, нужное для пункта. У группы без path права нет - видна, если виден хоть один дочерний. */
  permission?: string
  /** Модуль, который должен быть включён (иначе пункт скрыт). */
  module?: string
  /** Достаточно любого из модулей (пункт скрыт, если не включён ни один). */
  anyModule?: string[]
  /** Достаточно любого из прав. */
  anyPermission?: string[]
  children?: NavItem[]
}

export const NAV: NavItem[] = [
  { key: 'dashboard', labelKey: 'nav.dashboard', path: '/', permission: 'orders.view' },
  { key: 'clients', labelKey: 'nav.clients', path: '/clients', permission: 'clients.view', module: 'logistics' },
  { key: 'carriers', labelKey: 'nav.carriers', path: '/carriers', permission: 'carriers.view', module: 'forwarding' },
  {
    key: 'orders',
    labelKey: 'nav.orders',
    path: '/orders',
    permission: 'orders.view',
    module: 'logistics',
    children: [
      { key: 'consignments', labelKey: 'nav.consignments', path: '/consignments', permission: 'consignments.view', module: 'logistics' },
      { key: 'trips', labelKey: 'nav.trips', path: '/trips', permission: 'trips.view', module: 'logistics' },
      { key: 'transfers', labelKey: 'nav.transfers', path: '/transfers', permission: 'consignments.view', module: 'logistics' },
    ],
  },
  { key: 'vehicles', labelKey: 'nav.vehicles', path: '/vehicles', permission: 'fleet.view', module: 'fleet' },
  { key: 'drivers', labelKey: 'nav.drivers', path: '/drivers', permission: 'drivers.view', module: 'drivers' },
  { key: 'finance', labelKey: 'nav.finance', path: '/finance', permission: 'finance.view', module: 'finance' },
  { key: 'documents', labelKey: 'nav.documents', path: '/documents', permission: 'documents.view', module: 'documents' },
  { key: 'trash', labelKey: 'nav.trash', path: '/trash', permission: 'trash.view' },
  {
    key: 'settings',
    labelKey: 'nav.settings',
    children: [
      { key: 'company', labelKey: 'nav.company', path: '/settings/company', permission: 'company.view' },
      { key: 'users', labelKey: 'nav.users', path: '/settings/users', permission: 'users.view' },
      { key: 'departments', labelKey: 'nav.departments', path: '/settings/departments', permission: 'users.view' },
      { key: 'roles', labelKey: 'nav.roles', path: '/settings/roles', permission: 'roles.view' },
      { key: 'handbooks', labelKey: 'nav.handbooks', path: '/settings/handbooks', permission: 'handbooks.view' },
      { key: 'financesettings', labelKey: 'nav.financeSettings', path: '/settings/finance', permission: 'finance.manage_settings', module: 'finance' },
      { key: 'modules', labelKey: 'nav.modules', path: '/settings/modules', permission: 'company.manage_modules' },
      { key: 'doctypes', labelKey: 'nav.docTypes', path: '/settings/document-types', anyModule: ['fleet', 'drivers'], anyPermission: ['fleet.view', 'drivers.view'] },
      { key: 'numbering', labelKey: 'nav.numbering', path: '/settings/numbering', permission: 'numbering.view' },
      { key: 'doctemplates', labelKey: 'nav.doctemplates', path: '/settings/document-templates', permission: 'documents.view', module: 'documents' },
    ],
  },
]

type Access = Pick<Session, 'permissions' | 'modules'>

export function isAllowed(item: NavItem, access: Access): boolean {
  if (item.permission && !access.permissions.includes(item.permission)) return false
  if (item.module && !access.modules.includes(item.module)) return false
  if (item.anyPermission && !item.anyPermission.some((p) => access.permissions.includes(p))) return false
  if (item.anyModule && !item.anyModule.some((m) => access.modules.includes(m))) return false
  return true
}

/** Пункты меню, доступные сессии. UI только скрывает - сервер всё равно проверяет. */
export function visibleNav(access: Access, items: NavItem[] = NAV): NavItem[] {
  const result: NavItem[] = []
  for (const item of items) {
    const children = item.children ? visibleNav(access, item.children) : undefined
    if (item.path === undefined) {
      if (children && children.length > 0) result.push({ ...item, children })
    } else if (isAllowed(item, access)) {
      result.push(children ? { ...item, children } : item)
    }
  }
  return result
}

export function flattenNav(items: NavItem[] = NAV): NavItem[] {
  return items.flatMap((item) => [item, ...flattenNav(item.children ?? [])])
}
