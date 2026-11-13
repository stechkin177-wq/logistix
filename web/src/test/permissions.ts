const SECTIONS = [
  'clients', 'carriers', 'orders', 'consignments', 'trips', 'finance', 'trash',
  'users', 'roles', 'company', 'handbooks', 'numbering', 'documents', 'drivers', 'fleet',
]
const ACTIONS = ['view', 'create', 'update', 'delete']

/** Как ALL_PERMISSIONS бэкенда (apps/core/permissions_catalog.py). */
export const ALL_PERMISSIONS: string[] = [
  ...SECTIONS.flatMap((s) => ACTIONS.map((a) => `${s}.${a}`)),
  'finance.override_limit',
  'finance.cancel_invoice',
  'trips.revert_completed',
  'finance.close_period',
  'finance.reopen_period',
  'finance.adjust_closed',
  'finance.backdate',
  'finance.manage_settings',
  'company.manage_modules',
  'consignments.transfer',
  'audit.view',
  'labels.manage',
]
