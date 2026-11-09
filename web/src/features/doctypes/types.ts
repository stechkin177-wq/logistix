export type DocSubject = 'tractor' | 'trailer' | 'driver'
export const DOC_SUBJECTS: readonly DocSubject[] = ['tractor', 'trailer', 'driver']
export type StdField = 'number' | 'issued_by' | 'issued_at' | 'expires_at' | 'comment'
export const STD_FIELDS: readonly StdField[] = ['number', 'issued_by', 'issued_at', 'expires_at', 'comment']

export interface ExtraField {
  key: string
  label: string
  required: boolean
}

export interface DocumentType {
  id: number
  subject: DocSubject
  name: string
  fields: StdField[]
  required: StdField[]
  extra: ExtraField[]
  remind: boolean
  remind_days: number[]
  is_active: boolean
  archived_at: string | null
  sort_order: number
}

export type DocumentTypePayload = Partial<Omit<DocumentType, 'id' | 'archived_at'>>
