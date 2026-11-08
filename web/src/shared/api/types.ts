export type Module = 'logistics' | 'forwarding' | 'fleet' | 'drivers'
export type SubscriptionState = 'trial' | 'active' | 'grace' | 'readonly' | 'blocked'
export type Theme = 'light' | 'dark' | 'system'

export interface Session {
  user: { id: number; email: string | null; phone: string | null; full_name: string }
  company: { id: number; name: string; timezone: string; language: string }
  companies: { id: number; name: string }[]
  role: { id: number; name: string } | null
  modules: string[]
  permissions: string[]
  branding: Branding
  subscription: {
    status: SubscriptionState
    plan_code: string
    days_left: number | null
    grace_days_left: number | null
    is_free_period: boolean
  }
}

export interface LoginResponse {
  access: string
  refresh: string
  companies: { id: number; name: string }[]
}

export interface Branding {
  app_name: string
  logo_url: string | null
  primary_color: string
  theme: Theme
}

/** Записи, не вошедшие в итог в базовой валюте: суммы в исходной валюте, без пересчёта задним числом. */
export interface ExcludedPart {
  count: number
  by_currency: Record<string, { income: string; expense: string }>
}

export interface ExcludedBase {
  /** Общий итог неполный: часть записей в него не включена. */
  is_partial: boolean
  count: number
  orders: number
  /** Снимок курса сделан в прежней базовой валюте. */
  prior_base: ExcludedPart
  /** Курса нет (legacy_missing или плановый доход без снимка). */
  no_rate: ExcludedPart
}

export interface DashboardSummary {
  month: string
  active_orders: number
  completed_orders: number
  clients: number
  carriers: number
  unassigned_orders: number
  orders_by_status: { status_id: number; status: string; count: number }[]
  month_profit: string | null
  month_margin_pct: string | null
  /** Базовая валюта прибыли (null без права finance.view). */
  currency: string | null
  /** Заказов месяца в другой валюте: в прибыль не входят (null без finance.view). */
  excluded_orders: number | null
  /** Новая финансовая модель: что исключено из прибыли месяца (null - нечего исключать / прежний учёт). */
  excluded?: ExcludedBase | null
  is_partial?: boolean
}

export interface HandbookValue {
  id: number
  handbook: string
  name: string
  code: string
  order: number
  is_initial: boolean
  is_final: boolean
  is_active: boolean
  /** Системное значение: код защищён сервером (нельзя менять код, удалять, деактивировать, менять «конечное»). */
  is_system: boolean
}

export interface HandbookDetail {
  code: string
  name: string
  group: string
  values: HandbookValue[]
}
