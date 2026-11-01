export type Module = 'forwarding' | 'fleet'
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
}
