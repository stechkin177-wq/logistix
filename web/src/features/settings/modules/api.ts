import { api } from '../../../shared/api/client'

export interface Blocker {
  code: string
  detail: string
  modules: string[] | null
}

export interface CompanyModuleInfo {
  code: string
  name: string
  description: string
  status: 'available' | 'beta' | 'retired'
  is_core: boolean
  enabled: boolean
  available_in_plan: boolean
  effective: boolean
  requires: string[]
  enhances: string[]
  dependents: string[]
  can_enable: boolean
  can_disable: boolean
  blocker: Blocker | null
}

export interface ModulesResponse {
  plan_code: string | null
  modules: CompanyModuleInfo[]
  result?: ProfileResult
}

export interface ProfileResult {
  enabled: string[]
  disabled: string[]
  skipped: { code: string; error_code: string; detail: string }[]
}

export interface ActivityProfile {
  code: string
  name: string
  description: string
  modules: string[]
  unavailable_modules: string[]
  already_enabled: string[]
}

export const getModules = (signal?: AbortSignal) => api.get<ModulesResponse>('/company/modules/', undefined, { signal })
export const getProfiles = (signal?: AbortSignal) => api.get<ActivityProfile[]>('/activity-profiles/', undefined, { signal })
export const enableModule = (code: string, reason: string) =>
  api.post<ModulesResponse>(`/company/modules/${code}/enable/`, { reason })
export const disableModule = (code: string, reason: string, cascade: boolean) =>
  api.post<ModulesResponse>(`/company/modules/${code}/disable/`, { reason, cascade })
export const applyProfile = (profile: string, replace: boolean, reason: string) =>
  api.post<ModulesResponse>('/company/modules/apply-profile/', { profile, replace, reason })
