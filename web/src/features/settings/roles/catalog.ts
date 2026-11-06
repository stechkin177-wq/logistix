/** Каталог прав: как backend/apps/core/permissions_catalog.py (13 разделов x 4 действия). */
export const SECTIONS = [
  'clients', 'carriers', 'orders', 'consignments', 'trips', 'finance', 'trash',
  'users', 'roles', 'company', 'handbooks', 'numbering', 'documents',
] as const
export const ACTIONS = ['view', 'create', 'update', 'delete'] as const

/** Особые права сверх сетки (как EXTRA_PERMISSIONS на бэкенде). */
export const EXTRA_CODES = ['finance.override_limit', 'finance.cancel_invoice'] as const

export const ALL_CODES: string[] = [...SECTIONS.flatMap((s) => ACTIONS.map((a) => `${s}.${a}`)), ...EXTRA_CODES]
