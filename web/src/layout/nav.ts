import type { Session } from '../shared/api/types'
import {
  Blocks, BookOpen, Boxes, Building, Building2, CarFront, FileCog, FileStack, FileText, Hash, LayoutDashboard, Network,
  KeyRound, Package, Route, Settings, Tag, ShieldCheck, SlidersHorizontal, Trash2, Truck, UserRound, Users, Wallet, ArrowLeftRight,
  type LucideIcon,
} from '../shared/ui/icons'

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
  /** Иконка пункта меню. */
  icon?: LucideIcon
  /** Раздел страницы настроек, в котором стоит пункт (для боковой навигации настроек). */
  section?: 'organization' | 'data' | 'finance'
  children?: NavItem[]
}

export const NAV: NavItem[] = [
  { key: 'dashboard', labelKey: 'nav.dashboard', path: '/', permission: 'orders.view', icon: LayoutDashboard },
  { key: 'clients', labelKey: 'nav.clients', path: '/clients', permission: 'clients.view', module: 'logistics', icon: Building2 },
  { key: 'carriers', labelKey: 'nav.carriers', path: '/carriers', permission: 'carriers.view', module: 'forwarding', icon: Truck },
  {
    key: 'orders',
    labelKey: 'nav.orders',
    path: '/orders',
    permission: 'orders.view',
    module: 'logistics',
    icon: Package,
    children: [
      { key: 'consignments', labelKey: 'nav.consignments', path: '/consignments', permission: 'consignments.view', module: 'logistics', icon: Boxes },
      { key: 'trips', labelKey: 'nav.trips', path: '/trips', permission: 'trips.view', module: 'logistics', icon: Route },
      { key: 'transfers', labelKey: 'nav.transfers', path: '/transfers', permission: 'consignments.view', module: 'logistics', icon: ArrowLeftRight },
    ],
  },
  { key: 'vehicles', labelKey: 'nav.vehicles', path: '/vehicles', permission: 'fleet.view', module: 'fleet', icon: CarFront },
  { key: 'drivers', labelKey: 'nav.drivers', path: '/drivers', permission: 'drivers.view', module: 'drivers', icon: UserRound },
  { key: 'finance', labelKey: 'nav.finance', path: '/finance', permission: 'finance.view', module: 'finance', icon: Wallet },
  { key: 'documents', labelKey: 'nav.documents', path: '/documents', permission: 'documents.view', module: 'documents', icon: FileText },
  { key: 'trash', labelKey: 'nav.trash', path: '/trash', permission: 'trash.view', icon: Trash2 },
  {
    key: 'settings',
    labelKey: 'nav.settings',
    icon: Settings,
    children: [
      { key: 'company', labelKey: 'nav.company', path: '/settings/company', permission: 'company.view', icon: Building, section: 'organization' },
      { key: 'users', labelKey: 'nav.users', path: '/settings/users', permission: 'users.view', icon: Users, section: 'organization' },
      { key: 'departments', labelKey: 'nav.departments', path: '/settings/departments', permission: 'users.view', icon: Network, section: 'organization' },
      { key: 'roles', labelKey: 'nav.roles', path: '/settings/roles', permission: 'roles.view', icon: ShieldCheck, section: 'organization' },
      { key: 'audit', labelKey: 'nav.audit', path: '/settings/audit', permission: 'audit.view', icon: KeyRound, section: 'organization' },
      { key: 'modules', labelKey: 'nav.modules', path: '/settings/modules', permission: 'company.manage_modules', icon: Blocks, section: 'organization' },
      { key: 'labels', labelKey: 'nav.labels', path: '/settings/labels', permission: 'labels.manage', icon: Tag, section: 'data' },
      { key: 'handbooks', labelKey: 'nav.handbooks', path: '/settings/handbooks', permission: 'handbooks.view', icon: BookOpen, section: 'data' },
      { key: 'doctypes', labelKey: 'nav.docTypes', path: '/settings/document-types', anyModule: ['fleet', 'drivers'], anyPermission: ['fleet.view', 'drivers.view'], icon: FileCog, section: 'data' },
      { key: 'numbering', labelKey: 'nav.numbering', path: '/settings/numbering', permission: 'numbering.view', icon: Hash, section: 'data' },
      { key: 'doctemplates', labelKey: 'nav.doctemplates', path: '/settings/document-templates', permission: 'documents.view', module: 'documents', icon: FileStack, section: 'data' },
      { key: 'financesettings', labelKey: 'nav.financeSettings', path: '/settings/finance', permission: 'finance.manage_settings', module: 'finance', icon: SlidersHorizontal, section: 'finance' },
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
