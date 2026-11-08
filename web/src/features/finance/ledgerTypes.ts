/** Типы новых финансовых сущностей (API /finance/incomes, /expenses, /settings, /periods, /migration). */

export type FinanceEngine = 'legacy' | 'shadow' | 'new'

export interface EngineInfo {
  engine: FinanceEngine
  financial_writes_frozen: boolean
  base_currency: { id: number; code: string; name: string } | null
}

export interface HandbookRef { id: number; code: string; name: string }

export interface IncomeRow {
  id: number
  order: { id: number; number: string }
  kind: 'freight' | 'service'
  title: string
  category: string
  amount: string
  currency: HandbookRef | null
  status: 'planned' | 'recognized' | 'void'
  recognized_on: string | null
  recognition_basis: string
  delivered_on: string | null
  base_amount: string | null
  fx_rate: string | null
  trip: { id: number; number: string } | null
  void_reason: string
  legacy: boolean
}

export type AllocationMethod = 'equal' | 'proportional' | 'manual'

export interface AllocationRow {
  id: number
  order: { id: number; number: string } | null
  trip: { id: number; number: string } | null
  amount: string
}

export interface ExpenseRow {
  id: number
  kind: 'carrier_transport' | 'other'
  title: string
  category: HandbookRef
  amount: string
  currency: HandbookRef | null
  expense_date: string
  status: 'active' | 'void'
  source: string
  trip: { id: number; number: string } | null
  carrier: { id: number; name: string } | null
  needs_review: boolean
  review_reason: string
  /** Метод распределения по заказам рейса (старые ответы без поля = equal). */
  allocation_method?: AllocationMethod
  allocations: AllocationRow[]
  allocated: string
  unallocated: string
  linked_total: string | null
  invoice_variance: string | null
  void_reason: string
  order_amount?: string
}

export interface LedgerFilters {
  status: string
  date_from: string
  date_to: string
  needs_review: string
  page: number
  pageSize: number
}

export interface InvoiceBrief {
  id: number
  number: string
  direction: 'in' | 'out'
  status: string
  currency: HandbookRef | null
  total_gross: string
  issue_date: string | null
}

export interface OrderFinance {
  engine: FinanceEngine
  order: { id: number; number: string; currency: HandbookRef | null }
  incomes: IncomeRow[]
  expenses: ExpenseRow[]
  invoices: InvoiceBrief[]
  totals: { revenue: string; cost: string; profit: string; margin_pct: string | null }
  needs_review: boolean
}

export interface TripFinance {
  engine: FinanceEngine
  trip: { id: number; number: string; carrier: { id: number; name: string } | null; carrier_price: string; currency: HandbookRef | null }
  expense: ExpenseRow | null
  expenses: ExpenseRow[]
  invoices: InvoiceBrief[]
  can_create_expense: boolean
  needs_review: boolean
  invoice_variance: string | null
}

export interface Blocker { code: string; message: string }

export interface FinanceSettings {
  base_currency: HandbookRef | null
  accounting_method: string
  default_vat_rate: HandbookRef | null
  fiscal_year_start_month: number
  allow_backdating: boolean
  engine: FinanceEngine
  cutover_date: string | null
  completed_status: HandbookRef | null
  expense_creation_mode: 'manual' | 'on_assign'
  sync_carrier_price: boolean
  engine_switched_at: string | null
  financial_writes_frozen: boolean
  unmapped: string[]
  switch_blocked: boolean
  blockers: Blocker[]
}

export interface StatusValue {
  id: number
  name: string
  code: string
  is_active: boolean
  is_final: boolean
  is_initial: boolean
}

export interface StatusMappingReport {
  values: StatusValue[]
  unmapped: { code: string; reason: string; candidates: { id: number; name: string }[] }[]
  unmapped_system_codes: string[]
  completed_status: { id: number; name: string; code: string } | null
  switch_blocked: boolean
  blockers: Blocker[]
}

export interface PeriodRow {
  id: number
  year: number
  month: number
  status: 'open' | 'closed'
  closed_at: string | null
  closed_by: string | null
  comment: string
  events: { action: string; user: string | null; reason: string; created_at: string }[]
}

export interface MigrationRun {
  id: number
  kind: string
  mode: string
  status: string
  started_at: string
  finished_at: string | null
  unexplained: number | null
  not_reflected: number
}

export interface MigrationIssue {
  id: number
  issue_type: string
  severity: string
  source_model: string
  source_id: number | null
  message: string
  status: string
  resolution: string
}

export interface MigrationData {
  runs: MigrationRun[]
  open_issues: MigrationIssue[]
  open_count: number
}
