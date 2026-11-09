export type PlanStatus = 'draft' | 'active' | 'archived'
export type BillingType = 'monthly' | 'yearly' | 'lifetime'

export interface AdminPlan {
  code: string
  name: string
  description: string
  billing_type: BillingType
  price: string
  currency: string
  sort_order: number
  status: PlanStatus
  is_default: boolean
  limits: Record<string, number | null>
  modules: string[]
  features: Record<string, boolean | string>
  archived_at: string | null
  free_period_days: number
  limit_warn_percent: number
  subscriptions_count: number
}

export interface CatalogModule { code: string; name: string; description: string; requires: string[]; status: string }
export interface CatalogFeature { code: string; module: string; kind: 'bool' | 'level'; name: string; description: string; levels?: string[] }
export interface CatalogLimit { code: string; name: string; unit: string; scope: 'total' | 'month'; enforced: boolean }
export interface Catalog { modules: CatalogModule[]; features: CatalogFeature[]; limits: CatalogLimit[] }

export interface PlatformCompany {
  id: number
  name: string
  plan: string
  plan_name: string
  status: string
  is_free_period: boolean
  ends_at: string | null
}

export interface PeriodRow { plan: string; reason: string; starts_at: string; ends_at: string | null; price: string; currency: string; is_free?: boolean }

export interface SubscriptionInfo {
  company: number
  plan: string
  status: string
  is_free_period: boolean
  starts_at: string
  ends_at: string | null
  current_period: PeriodRow | null
  periods: PeriodRow[]
}

export interface ChangePreview {
  from_plan: string
  to_plan: string
  price: { current_period: string | null; new: string; currency: string }
  lost_modules: string[]
  gained_modules: string[]
  lost_features: string[]
  gained_features: string[]
  limits_exceeded: { code: string; name: string; usage: number | null; old_limit: number | null; new_limit: number | null }[]
  limits_tightened: { code: string; name: string; usage: number | null; old_limit: number | null; new_limit: number | null }[]
}

export interface HistoryRow {
  id: number
  kind: 'plan' | 'subscription'
  key: string
  action: string
  changes: Record<string, unknown>
  actor: string
  created_at: string
}
