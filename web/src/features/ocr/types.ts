/** Код типа документа компании (настраивается в «Настройки распознавания»). */
export type OcrDocType = string
export type OcrStatus = 'processing' | 'done' | 'failed'
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

/** Результат сверки с фото: правки значений и подтверждённые (по путям значений листа). */
export interface ReviewData { edits: Record<string, string>; checked: string[] }
export interface OcrGroup { id: number; name: string; total: number; pending: number }
export type OcrGrouping = 'driver' | 'vehicle' | 'all'
export interface OcrDocTypeRow {
  id: number
  code: string
  name: string
  handler: 'receipt' | 'sheet' | 'generic'
  driver_visible: boolean
  is_active: boolean
  sort_order: number
  used: number
}

export interface OcrDocument {
  id: number
  doc_type: OcrDocType
  doc_type_name: string
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
  source: 'office' | 'driver_app'
  trip: number | null
  trip_number: string
  driver: number | null
  driver_name: string
  vehicle: number | null
  vehicle_plate: string
  route: string
  review: Partial<ReviewData>
  reviewed_at: string | null
  archived_at: string | null
  driver_archived_at: string | null
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
export type OcrTestResult = Record<string, { ok: boolean; error: string }>
