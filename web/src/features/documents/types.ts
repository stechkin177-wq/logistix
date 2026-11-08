export const DOCUMENT_KINDS = ['contract', 'order_request', 'carrier_order', 'act', 'invoice_print', 'cmr', 'letter'] as const
export type DocumentKind = (typeof DOCUMENT_KINDS)[number]

export interface UserRef { id: number; full_name: string }

export interface DocTemplateVersion {
  id: number
  number: number
  sha256: string
  is_starter: boolean
  uploaded_by: UserRef | null
  created_at: string
}

export interface DocTemplate {
  id: number
  kind: DocumentKind
  name: string
  language: string
  is_active: boolean
  current_version: DocTemplateVersion | null
  versions_count: number
}

export interface Placeholder { name: string; description: string }

export interface IssuedDocument {
  id: number
  kind: DocumentKind
  number: string
  issue_date: string
  language: string
  client: { id: number; name: string } | null
  order: { id: number; number: string } | null
  trip: { id: number; number: string } | null
  invoice: { id: number; number: string } | null
  /** Универсальный субъект документа (например, drivers.driver); null у документов без субъекта. */
  subject_type?: string | null
  subject_id?: number | null
  template_version: { id: number; number: number; template: number }
  created_by: UserRef | null
  created_at: string
}

export interface IssuedFilters {
  kind: DocumentKind | ''
  date_from: string
  date_to: string
  search: string
  page: number
  pageSize: number
}

/** Источник документа: ровно одно поле (письмо можно привязать к заказу). */
export interface IssueSource {
  client?: number
  order?: number
  trip?: number
  invoice?: number
  /** Универсальный субъект поставщика модуля (например, drivers.driver, fleet.vehicle). */
  subject_type?: string
  subject_id?: number
}

export interface LetterPayload { recipient: string; subject: string; body: string }

export interface IssuePayload extends IssueSource {
  kind: DocumentKind
  letter?: LetterPayload
  language?: string
}

export interface Capabilities { pdf_available: boolean }

export type FileFormat = 'docx' | 'pdf'
