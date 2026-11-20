export type OcrDocType = 'fuel_receipt' | 'waybill' | 'cmr' | 'invoice' | 'report_sheet' | 'other'
export type OcrStatus = 'processing' | 'done' | 'failed'
export const OCR_DOC_TYPES: OcrDocType[] = ['fuel_receipt', 'waybill', 'cmr', 'invoice', 'report_sheet', 'other']
/** Поля, которые правит человек (ключи совпадают с серверным FIELD_KEYS). */
export const OCR_FIELD_KEYS = ['date', 'amount', 'liters', 'price_per_liter', 'fuel_type', 'plate', 'note'] as const
export type OcrFieldKey = (typeof OCR_FIELD_KEYS)[number]
export const FUEL_TYPES = ['diesel', 'ai98', 'ai95', 'ai92', 'ai80', 'gas'] as const

/** Прочитанный рукописный лист: значения, причины перепроверить (по путям) и что увидело второе чтение. */
export interface SheetPage {
  page_type: string
  raw: Record<string, unknown>
  flags: Record<string, string[]>
  alt: Record<string, string>
  notes: string[]
  models: string[]
}

export interface OcrDocument {
  id: number
  doc_type: OcrDocType
  status: OcrStatus
  engine: string
  original_name: string
  size: number
  has_file: boolean
  text: string
  fields: Partial<Record<OcrFieldKey, string>>
  sheet: Partial<SheetPage>
  error: string
  uploaded_by_name: string
  created_at: string
  processed_at: string | null
}

export interface OcrSettings {
  engine: string
  auto_fallback: boolean
  has_google_vision_key: boolean
  has_ocr_space_key: boolean
  has_gemini_key: boolean
  handwriting_enabled: boolean
  handwriting_crosscheck: boolean
  handwriting_model: string
  handwriting_check_model: string
  google_used: number
  google_limit: number
  tesseract_available: boolean
  storage_configured: boolean
  engines: { code: string; label: string }[]
}
export interface OcrSettingsForm {
  engine: string
  auto_fallback: boolean
  google_vision_key: string
  ocr_space_key: string
  gemini_key: string
  handwriting_enabled: boolean
  handwriting_crosscheck: boolean
  handwriting_model: string
  handwriting_check_model: string
}
export interface GeminiTestResult { ok: boolean; error?: string; models?: Record<string, { ok: boolean; error: string }> }
export type OcrTestResult = Record<string, { ok: boolean; error: string }>
