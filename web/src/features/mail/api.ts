import { api } from '../../shared/api/client'
import type { Paginated } from '../../shared/ui/Pagination'
import type { MailAccount, MailAccountForm, MailCompose, MailMessage, MailTemplate } from './types'

export const getMailStatus = (signal?: AbortSignal) =>
  api.get<{ configured: boolean; from_email: string }>('/mail/status/', undefined, { signal })
export const getMailAccount = (signal?: AbortSignal) => api.get<MailAccount>('/mail/account/', undefined, { signal })
export const saveMailAccount = (body: MailAccountForm) => api.put<MailAccount>('/mail/account/', body)
export const testMailAccount = () => api.post<{ state: string; error: string; to: string }>('/mail/account/test/', {})

export const listMailTemplates = (signal?: AbortSignal) => api.get<MailTemplate[]>('/mail/templates/', undefined, { signal })
export const createMailTemplate = (body: Omit<MailTemplate, 'id'>) => api.post<MailTemplate>('/mail/templates/', body)
export const updateMailTemplate = (id: number, body: Partial<Omit<MailTemplate, 'id'>>) =>
  api.patch<MailTemplate>(`/mail/templates/${String(id)}/`, body)
export const deleteMailTemplate = (id: number) => api.delete(`/mail/templates/${String(id)}/`)
export const renderMailTemplate = (id: number, ctx: { order?: number; trip?: number; client?: number }) =>
  api.post<{ subject: string; body: string }>(`/mail/templates/${String(id)}/render/`, ctx)

export interface MailFilters { page: number; q?: string; state?: string; order?: number; trip?: number; client?: number }
export const listMailMessages = (f: MailFilters, signal?: AbortSignal) =>
  api.get<Paginated<MailMessage>>(
    '/mail/messages/',
    { page: f.page, q: f.q || undefined, state: f.state || undefined, order: f.order, trip: f.trip, client: f.client },
    { signal },
  )
export const sendMail = (body: MailCompose) => api.post<MailMessage>('/mail/messages/', body)
export const resendMail = (id: number) => api.post<MailMessage>(`/mail/messages/${String(id)}/send/`, {})
