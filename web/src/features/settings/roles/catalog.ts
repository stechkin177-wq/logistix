/** Каталог прав: как backend/apps/core/permissions_catalog.py (13 разделов x 4 действия). */
export const SECTIONS = [
  'clients', 'carriers', 'orders', 'consignments', 'trips', 'finance', 'trash',
  'users', 'roles', 'company', 'handbooks', 'numbering', 'documents',
] as const
export const ACTIONS = ['view', 'create', 'update', 'delete'] as const

/**
 * Особые права сверх сетки (как EXTRA_PERMISSIONS на бэкенде): финансы, выход рейса из «Завершён»
 * и права финансовой архитектуры (периоды, обратное датирование, настройки).
 */
export const EXTRA_CODES = [
  'finance.override_limit', 'finance.cancel_invoice', 'trips.revert_completed',
  'finance.close_period', 'finance.reopen_period', 'finance.adjust_closed', 'finance.backdate', 'finance.manage_settings',
] as const

/** Права модульной архитектуры (отдельный список, как MODULE_MANAGEMENT_PERMISSIONS на бэкенде). */
export const MODULE_CODES = ['company.manage_modules'] as const

/** Право передач груза (отдельный список, как TRANSFER_PERMISSIONS на бэкенде). */
export const TRANSFER_CODES = ['consignments.transfer'] as const

/** Право журнала аудита и входов (отдельный список, как AUDIT_PERMISSIONS на бэкенде). */
export const AUDIT_CODES = ['audit.view'] as const

export const ALL_CODES: string[] = [...SECTIONS.flatMap((s) => ACTIONS.map((a) => `${s}.${a}`)), ...EXTRA_CODES, ...MODULE_CODES, ...TRANSFER_CODES, ...AUDIT_CODES]
